from datetime import timedelta
from datetime import datetime
from contextlib import asynccontextmanager
import logging
from pathlib import Path
import re
from urllib.parse import urlencode
from datetime import date
from starlette.datastructures import UploadFile

from fastapi import FastAPI, Form, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .auth import (
    PHONE_COOKIE, SESSION_COOKIE, audit, clear_phone_cookie, clear_session_cookie,
    create_phone_session, create_session, current_phone_session, current_session,
    redirect, require_actor, set_phone_cookie, set_session_cookie, utcnow_naive,
    verify_csrf,
)
from .config import settings
from .db import connection, execute, fetch_all, fetch_one
from .security import (
    constant_time_equal, derive_delivery_otp, digest_token, hash_password,
    mask_phone, new_organisation_reference, normalize_phone, new_token, validate_password, validate_pin,
    verify_password,
)
from .signing import (
    allow_public_authenticity_check, parse_canonical, qr_data_url, validate_signing_configuration,
    verification_url, verify_receipt,
)
from .history import organisation_receipt, receipt_count, verification_history, wat_time
from .photographs import (
    allow_identity_photo, photograph_reference_for_verification, portrait_png, record_photo_view,
)
from .consent import (
    ConsentError, approve as approve_consent, citizen_requests, organisation_disclosure,
    expire_requests,
    record_view as record_consent_view, reject as reject_consent,
    request_detail as consent_request_detail, start_web_approval, ussd_decide,
)
from .abuse import security_incident, security_incidents, security_overview
from .resilience import (SERVICE_CODES, SERVICE_MESSAGES, change_status as change_service_status, is_available,
                         record_unavailable, service_change_history, services, unavailable_message)
from .verification.errors import VerificationError
from .policy import PolicyEngine
from .verifier import (
    CONSENT_CLAIMS, DISCLOSURE_CLAIMS, NIGERIAN_STATES, PreparedRequest, create_submission, display_verification,
    prepare_request, submit_request,
)
from .verification import ClaimCode
from .verification.catalog import CLAIM_CATALOG, condition_label
from .evidence import clean_document_number, validate_evidence

settings.validate()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    with connection() as conn:
        validate_signing_configuration(conn)
    yield


app = FastAPI(title="TrustID", version="0.2.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(Path(__file__).with_name("static"))), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).with_name("templates")))
templates.env.globals["phone_time"] = lambda: datetime.now().strftime("%H:%M")
logger = logging.getLogger("trustid")


def active_categories(conn):
    categories = fetch_all(conn, "SELECT id,code,name,description,registration_reference_required FROM organisation_categories WHERE active=TRUE ORDER BY name")
    requirements = fetch_all(conn, """SELECT id,category_id,name,instructions,requirement_mode,
        requires_document_number,requires_expiry_date FROM category_evidence_requirements
        WHERE active=TRUE ORDER BY category_id,sort_order,id""")
    by_category = {}
    for requirement in requirements:
        by_category.setdefault(requirement["category_id"], []).append(requirement)
    for category in categories:
        category["evidence_requirements"] = by_category.get(category["id"], [])
    return categories


@app.exception_handler(VerificationError)
async def verification_error_handler(request: Request, exc: VerificationError):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.code, "message": exc.safe_message})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=400, content={
        "error": "INVALID_REQUEST",
        "message": "Please check the information provided and try again.",
    })


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception):
    logger.error("An unexpected application error was handled safely.")
    return JSONResponse(status_code=500, content={
        "error": "INTERNAL_ERROR",
        "message": "TrustID could not complete this request. Please try again later.",
    })


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'"
    return response


def page(request: Request, name: str, **context):
    return templates.TemplateResponse(request=request, name=name, context=context)


def phone_unread_count(conn, phone) -> int:
    if not phone or not phone.get("citizen_id"):
        return 0
    row = fetch_one(conn, "SELECT COUNT(*) count FROM sms_deliveries WHERE citizen_id=%s AND delivery_status='SENT' AND opened_at IS NULL",
                    (phone["citizen_id"],))
    return row["count"] if row else 0


@app.get("/health")
def health():
    with connection() as conn:
        fetch_one(conn, "SELECT 1 AS ok")
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with connection() as conn:
        session = current_session(conn, request)
    return page(request, "home.html", session=session)


def _balanced_demo_citizens(rows: list[dict], limit: int = 5) -> list[dict]:
    """Prefer a useful male/female mix while keeping the demo selection random."""
    selected: list[dict] = []
    groups = {
        "FEMALE": [row for row in rows if row.get("gender") == "FEMALE"],
        "MALE": [row for row in rows if row.get("gender") == "MALE"],
    }
    for gender, count in (("FEMALE", 3), ("MALE", 2)):
        selected.extend(groups[gender][:count])
    selected_ids = {row["citizen_id"] for row in selected}
    selected.extend(row for row in rows if row["citizen_id"] not in selected_ids)
    return selected[:limit]


DEMO_PASSWORD = "NeuGombe@2026"


def _demo_administrator(conn):
    return fetch_one(conn, """SELECT username,email,full_name FROM admin_users
        WHERE active=TRUE AND (locked_until IS NULL OR locked_until<=UTC_TIMESTAMP())
        ORDER BY (username='admin') DESC,id LIMIT 1""")


def _demo_organization(conn, public_reference: str):
    if not re.fullmatch(r"ORG-[A-Z0-9]+", public_reference or ""):
        return None
    return fetch_one(conn, """SELECT o.public_reference,o.business_name,o.email,c.name category_name
        FROM organisations o JOIN organisation_categories c ON c.id=o.category_id
        WHERE o.public_reference=%s AND o.status='APPROVED' AND c.active=TRUE
          AND o.email LIKE '%%.test'
          AND (o.locked_until IS NULL OR o.locked_until<=UTC_TIMESTAMP())""",
        (public_reference,))


@app.get("/demo-credentials", response_class=HTMLResponse)
def demo_credentials(request: Request):
    with connection() as conn:
        session = current_session(conn, request)
        administrator = _demo_administrator(conn)
        organization_rows = fetch_all(conn, """SELECT o.public_reference,o.business_name,o.email,c.name category_name
            FROM organisations o JOIN organisation_categories c ON c.id=o.category_id
            WHERE o.status='APPROVED' AND c.active=TRUE AND o.email LIKE '%%.test'
              AND (o.locked_until IS NULL OR o.locked_until<=UTC_TIMESTAMP())
            ORDER BY c.name,o.business_name""")
        organizations, seen_categories = [], set()
        for row in organization_rows:
            if row["category_name"] not in seen_categories:
                organizations.append(row)
                seen_categories.add(row["category_name"])
        citizen_columns = """citizen_id,full_name,synthetic_nin,registered_phone,gender"""
        activated_pool = fetch_all(conn, f"""SELECT {citizen_columns} FROM citizens
            WHERE account_activated=TRUE AND record_status='ACTIVE'
              AND (locked_until IS NULL OR locked_until<=UTC_TIMESTAMP()) ORDER BY RAND()""")
        unactivated_pool = fetch_all(conn, f"""SELECT {citizen_columns} FROM citizens
            WHERE account_activated=FALSE AND record_status='ACTIVE' ORDER BY RAND()""")
    response = page(request, "demo_credentials.html", session=session, administrator=administrator,
                    organizations=organizations, activated=_balanced_demo_citizens(activated_pool),
                    unactivated=_balanced_demo_citizens(unactivated_pool),
                    demo_password=DEMO_PASSWORD, demo_pin="13579")
    response.headers["Cache-Control"] = "no-store, private"
    return response


@app.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    with connection() as conn:
        session = current_session(conn, request)
        if session:
            verify_csrf(session, csrf_token)
            execute(conn, "UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE id=%s", (session["id"],))
            conn.commit()
    response = redirect("/")
    clear_session_cookie(response)
    return response


def failed_login(conn, table: str, id_column: str, actor_id: int) -> None:
    allowed = {("admin_users", "id"), ("organisations", "id")}
    if (table, id_column) not in allowed:
        raise ValueError("Unsupported account table")
    execute(conn, f"UPDATE {table} SET failed_login_attempts=failed_login_attempts+1 WHERE {id_column}=%s", (actor_id,))
    row = fetch_one(conn, f"SELECT failed_login_attempts FROM {table} WHERE {id_column}=%s", (actor_id,))
    if row and row["failed_login_attempts"] >= settings.auth_max_attempts:
        locked_until = utcnow_naive() + timedelta(minutes=settings.auth_lock_minutes)
        execute(conn, f"UPDATE {table} SET locked_until=%s, failed_login_attempts=0 WHERE {id_column}=%s", (locked_until, actor_id))


def failed_citizen_login(conn, citizen_id: int) -> None:
    execute(conn, "UPDATE citizens SET failed_pin_attempts=failed_pin_attempts+1 WHERE citizen_id=%s", (citizen_id,))
    row = fetch_one(conn, "SELECT failed_pin_attempts FROM citizens WHERE citizen_id=%s", (citizen_id,))
    if row and row["failed_pin_attempts"] >= settings.auth_max_attempts:
        locked_until = utcnow_naive() + timedelta(minutes=settings.auth_lock_minutes)
        execute(conn, "UPDATE citizens SET locked_until=%s, failed_pin_attempts=0 WHERE citizen_id=%s", (locked_until, citizen_id))


@app.get("/admin/login", response_class=HTMLResponse)
def admin_login_form(request: Request, demo: int = 0):
    administrator = None
    if demo == 1:
        with connection() as conn:
            administrator = _demo_administrator(conn)
    return page(request, "login.html", title="Admin login", action="/admin/login",
                identifier_label="Username",
                identifier_value=administrator["username"] if administrator else "",
                password_value=DEMO_PASSWORD if administrator else "",
                demo_prefill=bool(administrator))


@app.post("/admin/login")
def admin_login(request: Request, identifier: str = Form(...), password: str = Form(...)):
    error = "The credentials provided are invalid or the account is temporarily unavailable."
    with connection() as conn:
        user = fetch_one(conn, "SELECT * FROM admin_users WHERE username=%s", (identifier.strip(),))
        if not user or not user["active"] or (user["locked_until"] and user["locked_until"] > utcnow_naive()) or not verify_password(password, user["password_hash"]):
            if user:
                failed_login(conn, "admin_users", "id", user["id"])
                conn.commit()
            return page(request, "login.html", title="Admin login", action="/admin/login", identifier_label="Username", error=error)
        execute(conn, "UPDATE admin_users SET failed_login_attempts=0, locked_until=NULL, last_login_at=UTC_TIMESTAMP() WHERE id=%s", (user["id"],))
        token, _ = create_session(conn, "ADMIN", user["id"])
        conn.commit()
    response = redirect("/admin/change-password" if user["must_change_password"] else "/admin")
    set_session_cookie(response, token)
    return response


@app.get("/admin/change-password", response_class=HTMLResponse)
def admin_change_password_form(request: Request):
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
    return page(request, "admin_change_password.html", session=session)


@app.post("/admin/change-password")
def admin_change_password(request: Request, csrf_token: str = Form(...), current_password: str = Form(...), new_password: str = Form(...), password_confirm: str = Form(...)):
    try:
        validate_password(new_password)
        if new_password != password_confirm:
            raise ValueError("Password confirmation does not match")
        if new_password == current_password:
            raise ValueError("The new password must be different from the current password")
    except ValueError as exc:
        with connection() as conn:
            session = require_actor(conn, request, "ADMIN")
        return page(request, "admin_change_password.html", session=session, error=str(exc))
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        verify_csrf(session, csrf_token)
        admin = fetch_one(conn, "SELECT password_hash FROM admin_users WHERE id=%s FOR UPDATE", (session["actor_id"],))
        if not admin or not verify_password(current_password, admin["password_hash"]):
            return page(request, "admin_change_password.html", session=session, error="The current password is incorrect.")
        execute(conn, """UPDATE admin_users SET password_hash=%s, must_change_password=FALSE,
            password_changed_at=UTC_TIMESTAMP(), failed_login_attempts=0, locked_until=NULL WHERE id=%s""",
            (hash_password(new_password), session["actor_id"]))
        execute(conn, "UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE actor_type='ADMIN' AND actor_id=%s AND id<>%s", (session["actor_id"], session["id"]))
        conn.commit()
    return redirect("/admin")


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, status_filter: str = "", category: int | None = None,
                    q: str = "", date_from: str = "", date_to: str = "",
                    sort: str = "newest", error: str = "", page_number: int = 1):
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        admin = fetch_one(conn, "SELECT must_change_password,role FROM admin_users WHERE id=%s", (session["actor_id"],))
        if admin["must_change_password"]:
            return redirect("/admin/change-password")
        valid_statuses = {"PENDING", "NEEDS_INFORMATION", "APPROVED", "REJECTED", "SUSPENDED"}
        clean_status = status_filter if status_filter in valid_statuses else ""
        clean_q = q.strip()[:100]
        clean_from = date_from if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_from) else ""
        clean_to = date_to if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_to) else ""
        sort_options = {
            "newest": "o.created_at DESC,o.id DESC", "oldest": "o.created_at,o.id",
            "name_asc": "o.business_name,o.id", "name_desc": "o.business_name DESC,o.id DESC",
        }
        clean_sort = sort if sort in sort_options else "newest"
        where, params = [], []
        if clean_status:
            where.append("o.status=%s"); params.append(clean_status)
        if category:
            where.append("o.category_id=%s"); params.append(category)
        if clean_q:
            term = f"%{clean_q}%"
            where.append("(o.business_name LIKE %s OR o.email LIKE %s OR o.phone LIKE %s OR o.public_reference LIKE %s OR o.registration_reference LIKE %s)")
            params.extend([term] * 5)
        if clean_from:
            where.append("DATE(o.created_at)>=%s"); params.append(clean_from)
        if clean_to:
            where.append("DATE(o.created_at)<=%s"); params.append(clean_to)
        base_sql = """ FROM organisations o JOIN organisation_categories c ON c.id=o.category_id"""
        where_sql = " WHERE " + " AND ".join(where) if where else ""
        total = fetch_one(conn, "SELECT COUNT(*) count" + base_sql + where_sql, tuple(params))["count"]
        per_page = 10
        total_pages = max(1, (total + per_page - 1) // per_page)
        clean_page = min(max(1, page_number), total_pages)
        sql = """SELECT o.*,c.code AS category_code,c.name AS category_name
            FROM organisations o JOIN organisation_categories c ON c.id=o.category_id"""
        sql += where_sql + " ORDER BY " + sort_options[clean_sort] + " LIMIT %s OFFSET %s"
        orgs = fetch_all(conn, sql, tuple(params + [per_page, (clean_page - 1) * per_page]))
        counts = {row["status"]: row["count"] for row in fetch_all(conn, "SELECT status, COUNT(*) count FROM organisations GROUP BY status")}
        platform_stats = {
            "organisations": fetch_one(conn, "SELECT COUNT(*) count FROM organisations")["count"],
            "verifications": fetch_one(conn, "SELECT COUNT(*) count FROM verifications")["count"],
            "pending_requests": fetch_one(conn, "SELECT COUNT(*) count FROM consent_requests WHERE status='PENDING' AND expires_at>UTC_TIMESTAMP()")["count"],
            "blocked_today": fetch_one(conn, "SELECT COUNT(*) count FROM request_history WHERE decision='BLOCKED' AND timestamp>=UTC_TIMESTAMP()-INTERVAL 24 HOUR")["count"],
        }
        categories = active_categories(conn)
    error_message = {
        "reason": "Provide a clear reason before completing this action.",
        "category": "Select an active organization category.",
    }.get(error)
    filters = {"status": clean_status, "category": category or "", "q": clean_q,
               "date_from": clean_from, "date_to": clean_to, "sort": clean_sort}
    query = urlencode({key: value for key, value in {"status_filter": clean_status, "category": category or "",
                      "q": clean_q, "date_from": clean_from, "date_to": clean_to, "sort": clean_sort}.items() if value})
    pagination = {"page": clean_page, "pages": total_pages, "total": total, "base": "/admin?" + query}
    return page(request, "admin.html", session=session, admin=admin, organisations=orgs,
                counts=counts, categories=categories, active_filter=clean_status,
                filters=filters, platform_stats=platform_stats, error=error_message,
                total=total, page_number=clean_page, total_pages=total_pages, pagination=pagination)


@app.get("/admin/security", response_class=HTMLResponse)
def admin_security(request: Request, organisation: str = "", decision: str = "",
                   date_from: str = "", date_to: str = "", citizen_reference: str = "",
                   error: str = ""):
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        admin = fetch_one(conn, "SELECT must_change_password,role FROM admin_users WHERE id=%s", (session["actor_id"],))
        if admin["must_change_password"]:
            return redirect("/admin/change-password")
        overview = security_overview(conn)
        service_rows = services(conn)
        incidents = security_incidents(conn, organisation=organisation, decision=decision,
                                       date_from=date_from, date_to=date_to,
                                       citizen_reference=citizen_reference)
        audit(conn, "ADMIN_SECURITY_VIEWED", "ADMIN", session["actor_id"], "SECURITY_CENTRE",
              {"record_count": len(incidents)})
        conn.commit()
    filters = {"organisation": organisation, "decision": decision, "date_from": date_from,
               "date_to": date_to, "citizen_reference": citizen_reference}
    return page(request, "admin_security.html", session=session, admin=admin,
                overview=overview, services=service_rows,
                incidents=incidents, filters=filters,
                error={"service-note": "Select a reason for making the service unavailable."}.get(error))


@app.get("/admin/security/services/history", response_class=HTMLResponse)
def admin_service_history(request: Request, service: str = "", status: str = "",
                          administrator: str = "", date_from: str = "", date_to: str = "",
                          sort: str = "newest"):
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        admin = fetch_one(conn, "SELECT must_change_password,role FROM admin_users WHERE id=%s", (session["actor_id"],))
        if admin["must_change_password"]:
            return redirect("/admin/change-password")
        clean_from = date_from if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_from) else ""
        clean_to = date_to if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_to) else ""
        clean_sort = sort if sort in {"newest", "oldest"} else "newest"
        history = service_change_history(conn, service=service, status=status,
                                         administrator=administrator, date_from=clean_from,
                                         date_to=clean_to, sort=clean_sort)
        audit(conn, "ADMIN_SECURITY_VIEWED", "ADMIN", session["actor_id"], "SERVICE_STATUS_HISTORY",
              {"record_count": len(history)})
        conn.commit()
    filters = {"service": service if service in SERVICE_CODES else "",
               "status": status if status in {"AVAILABLE", "UNAVAILABLE"} else "",
               "administrator": administrator.strip()[:64], "date_from": clean_from,
               "date_to": clean_to, "sort": clean_sort}
    return page(request, "admin_service_history.html", session=session, admin=admin,
                service_history=history, filters=filters)


@app.post("/admin/security/services/{service_code}")
def admin_service_status(request: Request, service_code: str, csrf_token: str = Form(...),
                         status: str = Form(...), reason_code: str = Form(""), message: str = Form("")):
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        verify_csrf(session, csrf_token)
        admin = fetch_one(conn, "SELECT must_change_password FROM admin_users WHERE id=%s", (session["actor_id"],))
        if admin["must_change_password"]:
            return redirect("/admin/change-password")
        if status == "UNAVAILABLE":
            reasons = {
                "MAINTENANCE": "Scheduled maintenance in progress.",
                "SERVICE_INTERRUPTION": "Service interruption under investigation.",
                "TECHNICAL_ISSUE": "Technical issue under investigation.",
            }
            service_note = message.strip() if reason_code == "OTHER" else reasons.get(reason_code, "")
            if len(service_note) < 3:
                return redirect("/admin/security?error=service-note")
        else:
            service_note = ""
        try:
            change_service_status(conn, service_code, status, session["actor_id"], service_note)
        except ValueError:
            return redirect("/admin/security")
        conn.commit()
    return redirect("/admin/security")


@app.get("/admin/security/incidents/{incident_id}", response_class=HTMLResponse)
def admin_security_incident(request: Request, incident_id: int):
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        admin = fetch_one(conn, "SELECT must_change_password,role FROM admin_users WHERE id=%s", (session["actor_id"],))
        if admin["must_change_password"]:
            return redirect("/admin/change-password")
        incident = security_incident(conn, incident_id)
        if not incident:
            return redirect("/admin/security")
        audit(conn, "ADMIN_SECURITY_VIEWED", "ADMIN", session["actor_id"], str(incident_id),
              {"view": "INCIDENT_DETAIL"})
        conn.commit()
    return page(request, "admin_security_incident.html", session=session, admin=admin, incident=incident)


@app.post("/admin/organisations/{organisation_id}/status")
def change_org_status(request: Request, organisation_id: int, csrf_token: str = Form(...), new_status: str = Form(...), category_id: int | None = Form(None), reason: str = Form("")):
    if new_status not in {"APPROVED", "REJECTED", "SUSPENDED"}:
        return redirect("/admin")
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        verify_csrf(session, csrf_token)
        admin = fetch_one(conn, "SELECT must_change_password FROM admin_users WHERE id=%s", (session["actor_id"],))
        if admin["must_change_password"]:
            return redirect("/admin/change-password")
        org = fetch_one(conn, "SELECT id, status FROM organisations WHERE id=%s FOR UPDATE", (organisation_id,))
        if not org:
            return redirect("/admin")
        if org["status"] in {"PENDING", "NEEDS_INFORMATION"}:
            return redirect(f"/admin/organisations/{organisation_id}/review")
        allowed = (
            org["status"] == "PENDING" and new_status in {"APPROVED", "REJECTED"}
            or org["status"] == "APPROVED" and new_status == "SUSPENDED"
            or org["status"] == "SUSPENDED" and new_status == "APPROVED"
        )
        if not allowed:
            return redirect("/admin")
        action_reason = reason.strip()
        if new_status in {"REJECTED", "SUSPENDED"} and len(action_reason) < 5:
            return redirect(f"/admin?status_filter={org['status']}&error=reason")
        if org["status"] == "PENDING" and new_status == "APPROVED":
            category = fetch_one(conn, "SELECT id,code FROM organisation_categories WHERE id=%s AND active=TRUE", (category_id,)) if category_id else None
            if not category:
                return redirect("/admin?status_filter=PENDING&error=category")
        else:
            category = fetch_one(conn, """SELECT c.id,c.code FROM organisations o
                JOIN organisation_categories c ON c.id=o.category_id WHERE o.id=%s""", (organisation_id,))
        event = "ORG_REINSTATED" if org["status"] == "SUSPENDED" and new_status == "APPROVED" else {
            "APPROVED": "ORG_APPROVED", "REJECTED": "ORG_REJECTED", "SUSPENDED": "ORG_SUSPENDED",
        }[new_status]
        execute(conn, """UPDATE organisations SET status=%s, category_id=%s, status_reason=%s,
                   reviewed_by_admin_id=%s, reviewed_at=UTC_TIMESTAMP() WHERE id=%s""",
                (new_status, category["id"], action_reason if new_status in {"REJECTED", "SUSPENDED"} else None,
                 session["actor_id"], organisation_id))
        if new_status == "SUSPENDED":
            execute(conn, "UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE actor_type='ORGANISATION' AND actor_id=%s AND revoked_at IS NULL", (organisation_id,))
        audit(conn, event, "ADMIN", session["actor_id"], str(organisation_id), {"new_status": new_status, "category": category["code"]})
        conn.commit()
    return redirect(f"/admin?status_filter={new_status}")


@app.get("/admin/organisations/{organisation_id}/review", response_class=HTMLResponse)
def admin_application_review(request: Request, organisation_id: int, error: str = "", message: str = ""):
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        admin = fetch_one(conn, "SELECT must_change_password FROM admin_users WHERE id=%s", (session["actor_id"],))
        if admin["must_change_password"]:
            return redirect("/admin/change-password")
        organisation = fetch_one(conn, """SELECT o.*,c.name category_name,c.code category_code
            FROM organisations o JOIN organisation_categories c ON c.id=o.category_id WHERE o.id=%s""", (organisation_id,))
        if not organisation:
            return redirect("/admin")
        requirements = fetch_all(conn, """SELECT r.*,s.id submission_id,s.original_filename,s.mime_type,s.byte_size,
            s.document_number,s.expires_on,s.uploaded_at,s.review_status,s.review_notes
            FROM category_evidence_requirements r LEFT JOIN organisation_evidence_submissions s ON s.id=(
                SELECT s2.id FROM organisation_evidence_submissions s2 WHERE s2.requirement_id=r.id
                AND s2.organisation_id=%s ORDER BY s2.uploaded_at DESC,s2.id DESC LIMIT 1)
            WHERE r.category_id=%s AND r.active=TRUE ORDER BY r.sort_order,r.id""",
            (organisation_id, organisation["category_id"]))
        permissions = fetch_all(conn, """SELECT d.display_name,d.privacy_mode FROM category_claim_permissions p
            JOIN claim_definitions d ON d.claim_code=p.claim_code WHERE p.category_id=%s ORDER BY d.display_name""",
            (organisation["category_id"],))
        history = fetch_all(conn, """SELECT r.*,a.username administrator FROM organisation_application_reviews r
            LEFT JOIN admin_users a ON a.id=r.administrator_id WHERE r.organisation_id=%s ORDER BY r.created_at DESC,r.id DESC""",
            (organisation_id,))
    errors = {"notes": "Provide a clear reason of at least five characters.",
              "evidence": "All required evidence must be accepted before approval.",
              "expired": "An expired document cannot be accepted. Request a current replacement."}
    messages = {"assessed": "Evidence assessment saved.", "decided": "Application decision saved."}
    return page(request, "admin_application_review.html", session=session, organisation=organisation,
                requirements=requirements, permissions=permissions, history=history,
                error=errors.get(error), message=messages.get(message), current_date=date.today())


@app.get("/admin/organisations/{organisation_id}/evidence/{submission_id}")
def admin_view_application_evidence(request: Request, organisation_id: int, submission_id: int):
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        admin = fetch_one(conn, "SELECT active,must_change_password FROM admin_users WHERE id=%s", (session["actor_id"],))
        if not admin or not admin["active"]:
            return redirect("/")
        if admin["must_change_password"]:
            return redirect("/admin/change-password")
        item = fetch_one(conn, """SELECT stored_filename,original_filename,mime_type FROM organisation_evidence_submissions
            WHERE id=%s AND organisation_id=%s""", (submission_id, organisation_id))
    if not item:
        return redirect(f"/admin/organisations/{organisation_id}/review")
    storage = Path(settings.evidence_storage_path).resolve()
    evidence_path = (storage / item["stored_filename"]).resolve()
    if evidence_path.parent != storage or not evidence_path.is_file():
        raise VerificationError("EVIDENCE_UNAVAILABLE", "This evidence file is unavailable.", 404)
    safe_name = Path(item["original_filename"]).name.replace('"', "")
    return FileResponse(evidence_path, media_type=item["mime_type"],
                        headers={"Content-Disposition": f'inline; filename="{safe_name}"', "X-Content-Type-Options": "nosniff"})


@app.post("/admin/organisations/{organisation_id}/evidence/{submission_id}/assessment")
def admin_assess_application_evidence(request: Request, organisation_id: int, submission_id: int,
                                      csrf_token: str = Form(...), review_status: str = Form(...), notes: str = Form("")):
    if review_status not in {"ACCEPTED", "REJECTED"} or (review_status == "REJECTED" and len(notes.strip()) < 5):
        return redirect(f"/admin/organisations/{organisation_id}/review?error=notes")
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        verify_csrf(session, csrf_token)
        item = fetch_one(conn, "SELECT id,expires_on FROM organisation_evidence_submissions WHERE id=%s AND organisation_id=%s FOR UPDATE",
                         (submission_id, organisation_id))
        if not item:
            return redirect(f"/admin/organisations/{organisation_id}/review")
        if review_status == "ACCEPTED" and item["expires_on"] and item["expires_on"] < date.today():
            return redirect(f"/admin/organisations/{organisation_id}/review?error=expired")
        execute(conn, """UPDATE organisation_evidence_submissions SET review_status=%s,review_notes=%s,
            reviewed_by_admin_id=%s,reviewed_at=UTC_TIMESTAMP() WHERE id=%s""",
            (review_status, notes.strip() or None, session["actor_id"], submission_id))
        execute(conn, """INSERT INTO organisation_application_reviews
            (organisation_id,administrator_id,action,notes) VALUES (%s,%s,%s,%s)""",
            (organisation_id, session["actor_id"], f"EVIDENCE_{review_status}", notes.strip() or None))
        conn.commit()
    return redirect(f"/admin/organisations/{organisation_id}/review?message=assessed")


@app.post("/admin/organisations/{organisation_id}/review/decision")
def admin_application_decision(request: Request, organisation_id: int, csrf_token: str = Form(...),
                               decision: str = Form(...), notes: str = Form("")):
    if decision not in {"APPROVED", "REJECTED", "NEEDS_INFORMATION"}:
        return redirect(f"/admin/organisations/{organisation_id}/review")
    clean_notes = notes.strip()
    if decision != "APPROVED" and len(clean_notes) < 5:
        return redirect(f"/admin/organisations/{organisation_id}/review?error=notes")
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        verify_csrf(session, csrf_token)
        organisation = fetch_one(conn, "SELECT id,status,category_id FROM organisations WHERE id=%s FOR UPDATE", (organisation_id,))
        if not organisation or organisation["status"] not in {"PENDING", "NEEDS_INFORMATION"}:
            return redirect(f"/admin/organisations/{organisation_id}/review")
        if decision == "APPROVED":
            rows = fetch_all(conn, """SELECT r.requirement_mode,s.review_status FROM category_evidence_requirements r
                LEFT JOIN organisation_evidence_submissions s ON s.id=(SELECT s2.id FROM organisation_evidence_submissions s2
                WHERE s2.requirement_id=r.id AND s2.organisation_id=%s ORDER BY s2.uploaded_at DESC,s2.id DESC LIMIT 1)
                WHERE r.category_id=%s AND r.active=TRUE""", (organisation_id, organisation["category_id"]))
            required_ok = all(row["review_status"] == "ACCEPTED" for row in rows if row["requirement_mode"] == "REQUIRED")
            alternatives = [row for row in rows if row["requirement_mode"] == "ALTERNATIVE"]
            if not required_ok or (alternatives and not any(row["review_status"] == "ACCEPTED" for row in alternatives)):
                return redirect(f"/admin/organisations/{organisation_id}/review?error=evidence")
        execute(conn, """UPDATE organisations SET status=%s,status_reason=%s,reviewed_by_admin_id=%s,
            reviewed_at=UTC_TIMESTAMP() WHERE id=%s""",
            (decision, clean_notes if decision != "APPROVED" else None, session["actor_id"], organisation_id))
        action = "MORE_INFORMATION_REQUESTED" if decision == "NEEDS_INFORMATION" else decision
        execute(conn, """INSERT INTO organisation_application_reviews
            (organisation_id,administrator_id,action,notes) VALUES (%s,%s,%s,%s)""",
            (organisation_id, session["actor_id"], action, clean_notes or None))
        audit_event = {"APPROVED": "ORG_APPROVED", "REJECTED": "ORG_REJECTED",
                       "NEEDS_INFORMATION": "ORG_MORE_INFORMATION_REQUESTED"}[decision]
        audit(conn, audit_event, "ADMIN", session["actor_id"], str(organisation_id), {"decision": decision})
        conn.commit()
    return redirect(f"/admin/organisations/{organisation_id}/review?message=decided")


@app.get("/admin/categories", response_class=HTMLResponse)
def category_management(request: Request, error: str = ""):
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        admin = fetch_one(conn, "SELECT must_change_password FROM admin_users WHERE id=%s", (session["actor_id"],))
        if admin["must_change_password"]:
            return redirect("/admin/change-password")
        claims = fetch_all(conn, "SELECT * FROM claim_definitions WHERE active=TRUE ORDER BY action_type DESC,display_name")
        categories = fetch_all(conn, """SELECT c.*,COUNT(DISTINCT o.id) AS organisation_count
            FROM organisation_categories c LEFT JOIN organisations o ON o.category_id=c.id
            GROUP BY c.id ORDER BY c.name""")
        permissions = fetch_all(conn, "SELECT category_id,claim_code FROM category_claim_permissions")
        evidence = fetch_all(conn, """SELECT id,category_id,name,instructions,requirement_mode,
            requires_document_number,requires_expiry_date,active FROM category_evidence_requirements
            ORDER BY category_id,sort_order,id""")
    selected = {}
    for permission in permissions:
        selected.setdefault(permission["category_id"], set()).add(permission["claim_code"])
    evidence_by_category = {}
    for requirement in evidence:
        evidence_by_category.setdefault(requirement["category_id"], []).append(requirement)
    error_message = {"invalid": "Enter valid category details.", "duplicate": "A category with that name or code already exists."}.get(error)
    return page(request, "admin_categories.html", session=session, categories=categories, claims=claims,
                selected=selected, evidence_by_category=evidence_by_category, error=error_message)


def category_values(name: str, code: str, description: str):
    clean_name = name.strip()
    clean_code = re.sub(r"[^A-Z0-9]+", "_", (code.strip() or clean_name).upper()).strip("_")
    clean_description = description.strip()
    if not 2 <= len(clean_name) <= 100 or not re.fullmatch(r"[A-Z][A-Z0-9_]{1,49}", clean_code) or len(clean_description) > 255:
        raise ValueError("Enter a valid category name, code and description")
    return clean_name, clean_code, clean_description or None


def valid_claim_codes(conn, submitted: list[str]) -> list[str]:
    allowed = {row["claim_code"] for row in fetch_all(conn, "SELECT claim_code FROM claim_definitions WHERE active=TRUE")}
    return sorted(set(submitted) & allowed)


@app.post("/admin/categories")
def create_category(request: Request, csrf_token: str = Form(...), name: str = Form(...), code: str = Form(""),
                    description: str = Form(""), registration_reference_required: str = Form("0"),
                    claim_codes: list[str] = Form(default=[])):
    try:
        clean_name, clean_code, clean_description = category_values(name, code, description)
    except ValueError:
        return redirect("/admin/categories?error=invalid")
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        verify_csrf(session, csrf_token)
        admin = fetch_one(conn, "SELECT must_change_password FROM admin_users WHERE id=%s", (session["actor_id"],))
        if admin["must_change_password"]:
            return redirect("/admin/change-password")
        if fetch_one(conn, "SELECT id FROM organisation_categories WHERE code=%s OR name=%s", (clean_code, clean_name)):
            return redirect("/admin/categories?error=duplicate")
        execute(conn, """INSERT INTO organisation_categories
            (code,name,description,registration_reference_required) VALUES (%s,%s,%s,%s)""",
                (clean_code, clean_name, clean_description, registration_reference_required == "1"))
        category_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
        selected = valid_claim_codes(conn, claim_codes)
        for claim_code in selected:
            execute(conn, "INSERT INTO category_claim_permissions (category_id,claim_code) VALUES (%s,%s)", (category_id, claim_code))
        audit(conn, "CATEGORY_CREATED", "ADMIN", session["actor_id"], str(category_id), {"category_code": clean_code})
        audit(conn, "CATEGORY_PERMISSIONS_UPDATED", "ADMIN", session["actor_id"], str(category_id), {"claim_codes": selected})
        conn.commit()
    return redirect("/admin/categories")


def require_super_admin(conn, request: Request):
    session = require_actor(conn, request, "ADMIN")
    admin = fetch_one(conn, "SELECT id,username,role,active,must_change_password FROM admin_users WHERE id=%s", (session["actor_id"],))
    if not admin or not admin["active"]:
        raise VerificationError("ADMIN_UNAVAILABLE", "This administrator account is unavailable.", 403)
    if admin["must_change_password"]:
        return session, admin, redirect("/admin/change-password")
    if admin["role"] != "SUPER_ADMIN":
        raise VerificationError("ADMIN_FORBIDDEN", "Only a primary administrator can manage administrator accounts.", 403)
    return session, admin, None


@app.get("/admin/administrators", response_class=HTMLResponse)
def administrator_management(request: Request, error: str = "", message: str = "", q: str = "",
                             status: str = "", role: str = "", page_number: int = 1):
    with connection() as conn:
        session, current_admin, response = require_super_admin(conn, request)
        if response:
            return response
        clean_q, clean_status, clean_role = q.strip()[:100], status if status in {"ACTIVE", "INACTIVE"} else "", role if role in {"ADMIN", "SUPER_ADMIN"} else ""
        where, params = [], []
        if clean_q:
            term = f"%{clean_q}%"; where.append("(username LIKE %s OR full_name LIKE %s OR email LIKE %s)"); params.extend([term] * 3)
        if clean_status:
            where.append("active=%s"); params.append(clean_status == "ACTIVE")
        if clean_role:
            where.append("role=%s"); params.append(clean_role)
        where_sql = " WHERE " + " AND ".join(where) if where else ""
        total = fetch_one(conn, "SELECT COUNT(*) count FROM admin_users" + where_sql, tuple(params))["count"]
        per_page, pages = 8, max(1, (total + 7) // 8)
        clean_page = min(max(1, page_number), pages)
        administrators = fetch_all(conn, """SELECT id,username,full_name,email,role,active,created_at,last_login_at,
            must_change_password,deactivated_at FROM admin_users""" + where_sql +
            " ORDER BY active DESC,created_at,username LIMIT %s OFFSET %s", tuple(params + [per_page, (clean_page - 1) * per_page]))
    errors = {
        "invalid": "Enter a valid username and a temporary password of at least 10 characters.",
        "duplicate": "That administrator username is already in use.",
        "final_super": "TrustID must always have at least one active primary administrator.",
        "self": "You cannot deactivate your own administrator account.",
        "missing": "The administrator account could not be found.",
    }
    messages = {
        "created": "Administrator created. They must change the temporary password at first sign-in.",
        "activated": "Administrator access restored.",
        "deactivated": "Administrator access removed and active sessions ended.",
        "reset": "Temporary password set and active sessions ended.",
        "role": "Administrator role updated.",
    }
    return page(request, "admin_administrators.html", session=session, current_admin=current_admin,
                administrators=administrators, error=errors.get(error), message=messages.get(message),
                filters={"q": clean_q, "status": clean_status, "role": clean_role},
                pagination={"page": clean_page, "pages": pages, "total": total})


@app.post("/admin/administrators")
def create_administrator(request: Request, csrf_token: str = Form(...), username: str = Form(...),
                         temporary_password: str = Form(...), password_confirm: str = Form(...),
                         role: str = Form("ADMIN"), full_name: str = Form(""), email: str = Form("")):
    clean_username = username.strip().lower()
    clean_name = full_name.strip()
    clean_email = email.strip().lower()
    try:
        validate_password(temporary_password)
        if temporary_password != password_confirm:
            raise ValueError
        if (not re.fullmatch(r"[a-z][a-z0-9._-]{2,63}", clean_username)
                or role not in {"ADMIN", "SUPER_ADMIN"}
                or (clean_name and len(clean_name) < 2)
                or (clean_email and "@" not in clean_email)):
            raise ValueError
    except ValueError:
        return redirect("/admin/administrators?error=invalid")
    with connection() as conn:
        session, _, response = require_super_admin(conn, request)
        if response:
            return response
        verify_csrf(session, csrf_token)
        if fetch_one(conn, "SELECT id FROM admin_users WHERE username=%s OR (%s<>'' AND email=%s)",
                     (clean_username, clean_email, clean_email)):
            return redirect("/admin/administrators?error=duplicate")
        execute(conn, """INSERT INTO admin_users
            (username,full_name,email,role,active,password_hash,must_change_password,created_by_admin_id)
            VALUES (%s,%s,%s,%s,TRUE,%s,TRUE,%s)""",
            (clean_username, clean_name or None, clean_email or None, role,
             hash_password(temporary_password), session["actor_id"]))
        admin_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
        audit(conn, "ADMIN_CREATED", "ADMIN", session["actor_id"], str(admin_id), {"role": role})
        conn.commit()
    return redirect("/admin/administrators?message=created")


@app.post("/admin/administrators/{administrator_id}/status")
def change_administrator_status(request: Request, administrator_id: int, csrf_token: str = Form(...),
                                active: str = Form(...)):
    make_active = active == "1"
    with connection() as conn:
        session, _, response = require_super_admin(conn, request)
        if response:
            return response
        verify_csrf(session, csrf_token)
        target = fetch_one(conn, "SELECT id,role,active FROM admin_users WHERE id=%s FOR UPDATE", (administrator_id,))
        if not target:
            return redirect("/admin/administrators?error=missing")
        if not make_active and administrator_id == session["actor_id"]:
            return redirect("/admin/administrators?error=self")
        if not make_active and target["role"] == "SUPER_ADMIN":
            count = fetch_one(conn, "SELECT COUNT(*) count FROM admin_users WHERE role='SUPER_ADMIN' AND active=TRUE FOR UPDATE")["count"]
            if count <= 1:
                return redirect("/admin/administrators?error=final_super")
        execute(conn, "UPDATE admin_users SET active=%s,deactivated_at=%s WHERE id=%s",
                (make_active, None if make_active else utcnow_naive(), administrator_id))
        if not make_active:
            execute(conn, "UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE actor_type='ADMIN' AND actor_id=%s AND revoked_at IS NULL", (administrator_id,))
        event = "ADMIN_ACTIVATED" if make_active else "ADMIN_DEACTIVATED"
        audit(conn, event, "ADMIN", session["actor_id"], str(administrator_id), None)
        conn.commit()
    return redirect(f"/admin/administrators?message={'activated' if make_active else 'deactivated'}")


@app.post("/admin/administrators/{administrator_id}/role")
def change_administrator_role(request: Request, administrator_id: int, csrf_token: str = Form(...), role: str = Form(...)):
    if role not in {"ADMIN", "SUPER_ADMIN"}:
        return redirect("/admin/administrators?error=invalid")
    with connection() as conn:
        session, _, response = require_super_admin(conn, request)
        if response:
            return response
        verify_csrf(session, csrf_token)
        target = fetch_one(conn, "SELECT id,role,active FROM admin_users WHERE id=%s FOR UPDATE", (administrator_id,))
        if not target:
            return redirect("/admin/administrators?error=missing")
        if target["role"] == "SUPER_ADMIN" and role == "ADMIN" and target["active"]:
            count = fetch_one(conn, "SELECT COUNT(*) count FROM admin_users WHERE role='SUPER_ADMIN' AND active=TRUE FOR UPDATE")["count"]
            if count <= 1:
                return redirect("/admin/administrators?error=final_super")
        execute(conn, "UPDATE admin_users SET role=%s WHERE id=%s", (role, administrator_id))
        audit(conn, "ADMIN_ROLE_CHANGED", "ADMIN", session["actor_id"], str(administrator_id), {"role_changed_to": role})
        conn.commit()
    return redirect("/admin/administrators?message=role")


@app.post("/admin/administrators/{administrator_id}/reset-password")
def reset_administrator_password(request: Request, administrator_id: int, csrf_token: str = Form(...),
                                 temporary_password: str = Form(...), password_confirm: str = Form(...)):
    try:
        validate_password(temporary_password)
        if temporary_password != password_confirm:
            raise ValueError
    except ValueError:
        return redirect("/admin/administrators?error=invalid")
    with connection() as conn:
        session, _, response = require_super_admin(conn, request)
        if response:
            return response
        verify_csrf(session, csrf_token)
        if not fetch_one(conn, "SELECT id FROM admin_users WHERE id=%s FOR UPDATE", (administrator_id,)):
            return redirect("/admin/administrators?error=missing")
        execute(conn, """UPDATE admin_users SET password_hash=%s,must_change_password=TRUE,
            password_changed_at=UTC_TIMESTAMP(),failed_login_attempts=0,locked_until=NULL WHERE id=%s""",
            (hash_password(temporary_password), administrator_id))
        execute(conn, "UPDATE auth_sessions SET revoked_at=UTC_TIMESTAMP() WHERE actor_type='ADMIN' AND actor_id=%s AND revoked_at IS NULL", (administrator_id,))
        audit(conn, "ADMIN_PASSWORD_RESET", "ADMIN", session["actor_id"], str(administrator_id), None)
        conn.commit()
    return redirect("/admin/administrators?message=reset")


@app.get("/admin/organisations/{organisation_id}/verifications", response_class=HTMLResponse)
def admin_organisation_verifications(request: Request, organisation_id: int):
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        admin = fetch_one(conn, "SELECT active,must_change_password FROM admin_users WHERE id=%s", (session["actor_id"],))
        if not admin or not admin["active"]:
            return redirect("/")
        if admin["must_change_password"]:
            return redirect("/admin/change-password")
        organisation = fetch_one(conn, """SELECT o.id,o.business_name,o.status,c.name category_name
            FROM organisations o JOIN organisation_categories c ON c.id=o.category_id WHERE o.id=%s""", (organisation_id,))
        if not organisation:
            return redirect("/admin")
        rows = fetch_all(conn, """SELECT v.public_reference,v.subject_reference,v.claim_code,
            v.condition_expression,v.purpose,v.result,v.policy_decision,v.internal_reason_code,v.issued_at,v.expires_at,v.created_at,
            cr.status consent_status,cr.resolved_channel,cr.resolved_at,sd.delivery_status sms_status,
            (cd.verification_id IS NOT NULL) disclosure_created,r.transaction_id,r.verification_token,
            r.algorithm,r.signing_key_id,sk.status signing_key_status
            FROM verifications v
            LEFT JOIN consent_requests cr ON cr.verification_id=v.id
            LEFT JOIN sms_deliveries sd ON sd.consent_request_id=cr.id
            LEFT JOIN controlled_disclosures cd ON cd.verification_id=v.id
            LEFT JOIN receipts r ON r.verification_id=v.id
            LEFT JOIN signing_keys sk ON sk.key_id=r.signing_key_id
            WHERE v.organisation_id=%s ORDER BY v.created_at DESC""", (organisation_id,))
        for row in rows:
            if row.get("verification_token"):
                receipt_state, _, _ = verify_receipt(conn, row["verification_token"])
                row["receipt_status"] = {
                    "CURRENT": "Authentic and current", "EXPIRED": "Authentic but expired",
                    "INVALID": "Integrity issue", "UNAVAILABLE": "Unavailable",
                }[receipt_state]
        audit(conn, "ADMIN_VERIFICATION_HISTORY_VIEWED", "ADMIN", session["actor_id"], str(organisation_id), {"record_count": len(rows)})
        conn.commit()
    return page(request, "admin_verification_history.html", session=session, organisation=organisation,
                verifications=[display_verification(row) for row in rows])


@app.post("/admin/categories/{category_id}")
def update_category(request: Request, category_id: int, csrf_token: str = Form(...), name: str = Form(...),
                    description: str = Form(""), active: str = Form("0"),
                    registration_reference_required: str = Form("0"), claim_codes: list[str] = Form(default=[])):
    clean_name = name.strip()
    clean_description = description.strip()
    if not 2 <= len(clean_name) <= 100 or len(clean_description) > 255:
        return redirect("/admin/categories?error=invalid")
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        verify_csrf(session, csrf_token)
        admin = fetch_one(conn, "SELECT must_change_password FROM admin_users WHERE id=%s", (session["actor_id"],))
        if admin["must_change_password"]:
            return redirect("/admin/change-password")
        category = fetch_one(conn, "SELECT id,code FROM organisation_categories WHERE id=%s FOR UPDATE", (category_id,))
        if not category:
            return redirect("/admin/categories")
        duplicate = fetch_one(conn, "SELECT id FROM organisation_categories WHERE name=%s AND id<>%s", (clean_name, category_id))
        if duplicate:
            return redirect("/admin/categories?error=duplicate")
        is_active = active == "1"
        execute(conn, """UPDATE organisation_categories SET name=%s,description=%s,active=%s,
            registration_reference_required=%s WHERE id=%s""",
                (clean_name, clean_description or None, is_active,
                 registration_reference_required == "1", category_id))
        selected = valid_claim_codes(conn, claim_codes)
        execute(conn, "DELETE FROM category_claim_permissions WHERE category_id=%s", (category_id,))
        for claim_code in selected:
            execute(conn, "INSERT INTO category_claim_permissions (category_id,claim_code) VALUES (%s,%s)", (category_id, claim_code))
        audit(conn, "CATEGORY_UPDATED", "ADMIN", session["actor_id"], str(category_id), {
            "category_code": category["code"], "active": is_active,
        })
        audit(conn, "CATEGORY_PERMISSIONS_UPDATED", "ADMIN", session["actor_id"], str(category_id), {"claim_codes": selected})
        conn.commit()
    return redirect("/admin/categories")


@app.post("/admin/categories/{category_id}/evidence")
def add_category_evidence(request: Request, category_id: int, csrf_token: str = Form(...),
                          name: str = Form(...), instructions: str = Form(""),
                          requirement_mode: str = Form("REQUIRED"),
                          requires_document_number: str = Form("0"), requires_expiry_date: str = Form("0")):
    clean_name, clean_instructions = name.strip(), instructions.strip()
    if not 2 <= len(clean_name) <= 120 or len(clean_instructions) > 255 or requirement_mode not in {"REQUIRED", "ALTERNATIVE", "OPTIONAL"}:
        return redirect("/admin/categories?error=invalid")
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        verify_csrf(session, csrf_token)
        if not fetch_one(conn, "SELECT id FROM organisation_categories WHERE id=%s", (category_id,)):
            return redirect("/admin/categories")
        execute(conn, """INSERT INTO category_evidence_requirements
            (category_id,name,instructions,requirement_mode,requires_document_number,requires_expiry_date,sort_order)
            VALUES (%s,%s,%s,%s,%s,%s,(SELECT next_order FROM (SELECT COALESCE(MAX(sort_order),0)+10 next_order
            FROM category_evidence_requirements WHERE category_id=%s) x))""",
            (category_id, clean_name, clean_instructions or None, requirement_mode,
             requires_document_number == "1", requires_expiry_date == "1", category_id))
        audit(conn, "CATEGORY_UPDATED", "ADMIN", session["actor_id"], str(category_id), {"evidence_added": clean_name})
        conn.commit()
    return redirect("/admin/categories")


@app.post("/admin/categories/{category_id}/evidence/{requirement_id}/status")
def change_category_evidence_status(request: Request, category_id: int, requirement_id: int,
                                    csrf_token: str = Form(...), active: str = Form("0")):
    with connection() as conn:
        session = require_actor(conn, request, "ADMIN")
        verify_csrf(session, csrf_token)
        execute(conn, "UPDATE category_evidence_requirements SET active=%s WHERE id=%s AND category_id=%s",
                (active == "1", requirement_id, category_id))
        audit(conn, "CATEGORY_UPDATED", "ADMIN", session["actor_id"], str(category_id), {"evidence_status_changed": requirement_id})
        conn.commit()
    return redirect("/admin/categories")


@app.get("/organisation/register", response_class=HTMLResponse)
def org_register_form(request: Request):
    with connection() as conn:
        categories = active_categories(conn)
    return page(request, "org_register.html", categories=categories)


@app.post("/organisation/register")
async def org_register(request: Request):
    form = await request.form()
    business_name, email, phone = str(form.get("business_name", "")), str(form.get("email", "")), str(form.get("phone", ""))
    registration_reference, intended_use = str(form.get("registration_reference", "")), str(form.get("intended_use", ""))
    password, password_confirm = str(form.get("password", "")), str(form.get("password_confirm", ""))
    try:
        category_id = int(str(form.get("category_id", "0")))
    except ValueError:
        category_id = 0
    try:
        validate_password(password)
        if password != password_confirm:
            raise ValueError("Password confirmation does not match")
        phone = normalize_phone(phone)
        if category_id < 1 or len(business_name.strip()) < 2 or "@" not in email or len(intended_use.strip()) < 10:
            raise ValueError("Complete all fields with valid information")
    except ValueError as exc:
        with connection() as conn:
            categories = active_categories(conn)
        return page(request, "org_register.html", categories=categories, error=str(exc))
    with connection() as conn:
        categories = active_categories(conn)
        category = fetch_one(conn, """SELECT id,code FROM organisation_categories
            WHERE id=%s AND active=TRUE""", (category_id,))
        if not category:
            return page(request, "org_register.html", categories=categories, error="Select an available organization category")
        if fetch_one(conn, "SELECT id FROM organisations WHERE email=%s", (email.strip().lower(),)):
            return page(request, "org_register.html", categories=categories, error="An application already exists for this email")
        requirements = fetch_all(conn, """SELECT id,name,requirement_mode,requires_document_number,requires_expiry_date
            FROM category_evidence_requirements WHERE category_id=%s AND active=TRUE ORDER BY sort_order,id""", (category_id,))
        uploads = []
        alternative_count = 0
        try:
            for requirement in requirements:
                upload = form.get(f'evidence_file_{requirement["id"]}')
                has_file = isinstance(upload, UploadFile) and bool(upload.filename)
                if requirement["requirement_mode"] == "REQUIRED" and not has_file:
                    raise ValueError(f'Upload {requirement["name"]}.')
                if requirement["requirement_mode"] == "ALTERNATIVE" and has_file:
                    alternative_count += 1
                if not has_file:
                    continue
                document_number = clean_document_number(str(form.get(f'evidence_number_{requirement["id"]}', "")))
                expiry_value = str(form.get(f'evidence_expiry_{requirement["id"]}', "")).strip()
                if requirement["requires_document_number"] and not document_number:
                    raise ValueError(f'Enter the document number for {requirement["name"]}.')
                if requirement["requires_expiry_date"] and not expiry_value:
                    raise ValueError(f'Enter the expiry date for {requirement["name"]}.')
                expiry = date.fromisoformat(expiry_value) if expiry_value else None
                uploads.append((requirement, validate_evidence(upload.filename, await upload.read()), document_number, expiry))
            if any(r["requirement_mode"] == "ALTERNATIVE" for r in requirements) and alternative_count == 0:
                raise ValueError("Upload at least one of the accepted evidence options.")
        except (ValueError, TypeError) as exc:
            return page(request, "org_register.html", categories=categories, error=str(exc))
        execute(conn, """INSERT INTO organisations
            (public_reference,business_name,email,phone,category_id,registration_reference,intended_use,password_hash)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (new_organisation_reference(), business_name.strip(), email.strip().lower(), phone, category_id,
             None, intended_use.strip(), hash_password(password)))
        org_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
        storage = Path(settings.evidence_storage_path).resolve()
        storage.mkdir(parents=True, exist_ok=True)
        written = []
        try:
            for requirement, evidence, document_number, expiry in uploads:
                destination = storage / evidence.stored_filename
                destination.write_bytes(evidence.content)
                written.append(destination)
                execute(conn, """INSERT INTO organisation_evidence_submissions
                    (organisation_id,requirement_id,original_filename,stored_filename,mime_type,byte_size,sha256,document_number,expires_on)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (org_id, requirement["id"], evidence.original_filename, evidence.stored_filename,
                     evidence.mime_type, len(evidence.content), evidence.digest, document_number, expiry))
        except Exception:
            for destination in written:
                destination.unlink(missing_ok=True)
            raise
        audit(conn, "ORG_APPLICATION_SUBMITTED", "ORGANISATION", org_id, str(org_id), {"category": category["code"]})
        conn.commit()
    return redirect("/organisation/login?registered=1")


@app.get("/organisation/login", response_class=HTMLResponse)
def org_login_form(request: Request, registered: int = 0, demo: str = ""):
    organization = None
    if demo:
        with connection() as conn:
            organization = _demo_organization(conn, demo.strip().upper())
    return page(request, "login.html", title="Organisation login", action="/organisation/login",
                identifier_label="Email",
                message="Application submitted. You can now sign in to view its status." if registered else None,
                identifier_value=organization["email"] if organization else "",
                password_value=DEMO_PASSWORD if organization else "",
                demo_prefill=bool(organization))


@app.post("/organisation/login")
def org_login(request: Request, identifier: str = Form(...), password: str = Form(...)):
    error = "The credentials provided are invalid or the account is temporarily unavailable."
    with connection() as conn:
        org = fetch_one(conn, "SELECT * FROM organisations WHERE email=%s", (identifier.strip().lower(),))
        if not org or (org["locked_until"] and org["locked_until"] > utcnow_naive()) or not verify_password(password, org["password_hash"]):
            if org:
                failed_login(conn, "organisations", "id", org["id"])
                audit(conn, "ORG_LOGIN_FAILED", "ORGANISATION", org["id"], str(org["id"]), {"reason": "INVALID_CREDENTIALS_OR_LOCKED"})
                conn.commit()
            return page(request, "login.html", title="Organisation login", action="/organisation/login", identifier_label="Email", error=error)
        execute(conn, "UPDATE organisations SET failed_login_attempts=0, locked_until=NULL, last_login_at=UTC_TIMESTAMP() WHERE id=%s", (org["id"],))
        token, _ = create_session(conn, "ORGANISATION", org["id"])
        audit(conn, "ORG_LOGIN", "ORGANISATION", org["id"], str(org["id"]), {"status": org["status"]})
        conn.commit()
    response = redirect("/organisation")
    set_session_cookie(response, token)
    return response


@app.get("/organisation", response_class=HTMLResponse)
def org_dashboard(request: Request, evidence_error: int = 0, evidence_updated: int = 0):
    with connection() as conn:
        session = require_actor(conn, request, "ORGANISATION")
        expire_requests(conn)
        org = fetch_one(conn, """SELECT o.*,c.code AS category_code,c.name AS category_name
            FROM organisations o JOIN organisation_categories c ON c.id=o.category_id WHERE o.id=%s""", (session["actor_id"],))
        recent = fetch_all(conn, """SELECT v.public_reference,v.subject_reference,v.claim_code,v.condition_expression,
            v.result,v.created_at,v.expires_at,r.transaction_id,cr.status consent_status
            FROM verifications v LEFT JOIN receipts r ON r.verification_id=v.id
            LEFT JOIN consent_requests cr ON cr.verification_id=v.id
            WHERE v.organisation_id=%s AND v.public_reference IS NOT NULL
            ORDER BY v.created_at DESC LIMIT 5""", (session["actor_id"],))
        pending_count = fetch_one(conn, """SELECT COUNT(*) count FROM consent_requests
            WHERE organisation_id=%s AND status='PENDING' AND expires_at>UTC_TIMESTAMP()""", (session["actor_id"],))["count"]
        signed_count = receipt_count(conn, session["actor_id"])
        application_evidence = fetch_all(conn, """SELECT r.*,s.id submission_id,s.original_filename,
            s.review_status,s.review_notes,s.document_number,s.expires_on FROM category_evidence_requirements r
            LEFT JOIN organisation_evidence_submissions s ON s.id=(SELECT s2.id FROM organisation_evidence_submissions s2
                WHERE s2.requirement_id=r.id AND s2.organisation_id=%s ORDER BY s2.uploaded_at DESC,s2.id DESC LIMIT 1)
            WHERE r.category_id=%s AND r.active=TRUE ORDER BY r.sort_order,r.id""",
            (session["actor_id"], org["category_id"]))
        conn.commit()
    claims = PolicyEngine().available_claims(session["actor_id"])
    return page(request, "org_dashboard.html", session=session, organisation=org,
                available_claims=claims, recent=[display_verification(row) for row in recent],
                pending_count=pending_count, signed_count=signed_count, application_evidence=application_evidence,
                evidence_error=evidence_error, evidence_updated=evidence_updated)


@app.post("/organisation/application/evidence")
async def organisation_supply_application_evidence(request: Request):
    form = await request.form()
    with connection() as conn:
        session = require_actor(conn, request, "ORGANISATION")
        verify_csrf(session, str(form.get("csrf_token", "")))
        organisation = fetch_one(conn, "SELECT id,status,category_id FROM organisations WHERE id=%s FOR UPDATE", (session["actor_id"],))
        if not organisation or organisation["status"] not in {"PENDING", "NEEDS_INFORMATION"}:
            return redirect("/organisation")
        requirements = fetch_all(conn, """SELECT id,requires_document_number,requires_expiry_date
            FROM category_evidence_requirements WHERE category_id=%s AND active=TRUE""", (organisation["category_id"],))
        uploads = []
        try:
            for requirement in requirements:
                upload = form.get(f'evidence_file_{requirement["id"]}')
                if not isinstance(upload, UploadFile) or not upload.filename:
                    continue
                number = clean_document_number(str(form.get(f'evidence_number_{requirement["id"]}', "")))
                expiry_value = str(form.get(f'evidence_expiry_{requirement["id"]}', "")).strip()
                if requirement["requires_document_number"] and not number:
                    raise ValueError("Enter the document number for every replacement document.")
                if requirement["requires_expiry_date"] and not expiry_value:
                    raise ValueError("Enter the expiry date for every replacement document.")
                uploads.append((requirement, validate_evidence(upload.filename, await upload.read()), number,
                                date.fromisoformat(expiry_value) if expiry_value else None))
            if not uploads:
                raise ValueError("Choose at least one document to submit.")
        except (ValueError, TypeError):
            return redirect("/organisation?evidence_error=1")
        storage = Path(settings.evidence_storage_path).resolve()
        storage.mkdir(parents=True, exist_ok=True)
        for requirement, evidence, number, expiry in uploads:
            (storage / evidence.stored_filename).write_bytes(evidence.content)
            execute(conn, """INSERT INTO organisation_evidence_submissions
                (organisation_id,requirement_id,original_filename,stored_filename,mime_type,byte_size,sha256,document_number,expires_on)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (organisation["id"], requirement["id"], evidence.original_filename, evidence.stored_filename,
                 evidence.mime_type, len(evidence.content), evidence.digest, number, expiry))
        execute(conn, """INSERT INTO organisation_application_reviews (organisation_id,action,notes)
            VALUES (%s,'EVIDENCE_RESUBMITTED',%s)""", (organisation["id"], f"{len(uploads)} document(s) submitted"))
        execute(conn, "UPDATE organisations SET status='PENDING' WHERE id=%s", (organisation["id"],))
        conn.commit()
    return redirect("/organisation?evidence_updated=1")


@app.get("/organisation/history", response_class=HTMLResponse)
def organisation_history(request: Request, tab: str = "all", q: str = "", status: str = "",
                         claim: str = "", date_from: str = "", date_to: str = "", page_number: int = 1):
    with connection() as conn:
        session = require_actor(conn, request, "ORGANISATION")
        expire_requests(conn)
        org = fetch_one(conn, """SELECT o.business_name,o.status,c.name category_name
            FROM organisations o JOIN organisation_categories c ON c.id=o.category_id WHERE o.id=%s""",
            (session["actor_id"],))
        history = verification_history(conn, session["actor_id"], tab=tab, query=q, status=status,
                                       claim=claim, date_from=date_from, date_to=date_to, page=page_number)
        claim_rows = fetch_all(conn, """SELECT DISTINCT claim_code FROM verifications
            WHERE organisation_id=%s ORDER BY claim_code""", (session["actor_id"],))
        conn.commit()
    claims = [{"code": row["claim_code"], "label": CLAIM_CATALOG[ClaimCode(row["claim_code"])].label}
              for row in claim_rows]
    return page(request, "verification_history.html", session=session, organisation=org,
                history=history, claims=claims)


@app.get("/organisation/receipts/{transaction_id}", response_class=HTMLResponse)
def organisation_receipt_detail(request: Request, transaction_id: str):
    with connection() as conn:
        session = require_actor(conn, request, "ORGANISATION")
        org = fetch_one(conn, "SELECT business_name,status FROM organisations WHERE id=%s", (session["actor_id"],))
        receipt = organisation_receipt(conn, session["actor_id"], transaction_id)
    if not receipt:
        return redirect("/organisation/history?tab=receipts")
    if receipt.get("safe"):
        receipt["qr"] = qr_data_url(receipt["verification_link"])
    return page(request, "receipt_detail.html", session=session, organisation=org, receipt=receipt)


def approved_org(conn, request: Request):
    session = require_actor(conn, request, "ORGANISATION")
    org = fetch_one(conn, """SELECT o.id,o.business_name,o.status,c.name category_name,c.active category_active
        FROM organisations o JOIN organisation_categories c ON c.id=o.category_id WHERE o.id=%s""",
        (session["actor_id"],))
    if not org or org["status"] != "APPROVED" or not org["category_active"]:
        return session, org, False
    return session, org, True


def claim_form_context(claim: ClaimCode) -> dict:
    return {
        "claim": claim,
        "definition": CLAIM_CATALOG[claim],
        "identity_claim": claim in {
            ClaimCode.AGE_COMPARE, ClaimCode.IDENTITY_STATUS, ClaimCode.FULL_LEGAL_NAME,
            ClaimCode.STATE_OF_ORIGIN, ClaimCode.RESIDENTIAL_ADDRESS,
            ClaimCode.REGISTERED_RESIDENCE,
        },
        "flexible_identity_claim": claim == ClaimCode.NAME_MATCH,
        "consent_claim": claim in CONSENT_CLAIMS,
        "states": NIGERIAN_STATES,
    }


def information_returned(claim: ClaimCode) -> str:
    result = {
        ClaimCode.AGE_COMPARE: "Whether the person meets the selected age requirement.",
        ClaimCode.IDENTITY_STATUS: "Whether the submitted NIN matches a valid identity record held by the national identity authority.",
        ClaimCode.LICENCE_STATUS: "Whether the driving licence matches the selected status.",
        ClaimCode.LICENCE_CLASS: "Whether the driving licence matches the selected class requirement.",
        ClaimCode.FULL_LEGAL_NAME: "The legal name, only after the citizen approves.",
        ClaimCode.STATE_OF_ORIGIN: "The state of origin, only after the citizen approves.",
        ClaimCode.RESIDENTIAL_ADDRESS: "The residential address, only after the citizen approves.",
        ClaimCode.NAME_MATCH: "Whether the supplied name matches the selected identity record. The registered name is not revealed.",
        ClaimCode.REGISTERED_RESIDENCE: "Whether the supplied location matches the registered residence. The registered address is not revealed.",
    }[claim]
    return result + " The identity photograph will also be displayed for comparison."


@app.get("/organisation/verifications/new", response_class=HTMLResponse)
def verification_choices(request: Request):
    with connection() as conn:
        session, org, allowed = approved_org(conn, request)
    if not allowed:
        return redirect("/organisation")
    claims = PolicyEngine().available_claims(session["actor_id"])
    for claim in claims:
        claim["description"] = CLAIM_CATALOG[ClaimCode(claim["claim_code"])].description
    return page(request, "verification_choices.html", session=session, organisation=org, claims=claims)


@app.get("/organisation/verifications/new/{claim_code}", response_class=HTMLResponse)
def verification_details(request: Request, claim_code: str):
    with connection() as conn:
        session, org, allowed = approved_org(conn, request)
    if not allowed:
        return redirect("/organisation")
    permitted = {row["claim_code"] for row in PolicyEngine().available_claims(session["actor_id"])}
    if claim_code not in permitted:
        return redirect("/organisation/verifications/new")
    claim = ClaimCode(claim_code)
    return page(request, "verification_details.html", session=session, organisation=org,
                **claim_form_context(claim))


@app.post("/organisation/verifications/review", response_class=HTMLResponse)
def verification_review(request: Request, csrf_token: str = Form(...), claim_code: str = Form(...),
                        identifier: str = Form(...), operator: str = Form(""),
                        threshold_low: str = Form(""), threshold_high: str = Form(""),
                        classes: list[str] = Form(default=[]), purpose: str = Form(...),
                        surname: str = Form(""), first_name: str = Form(""), middle_name: str = Form(""),
                        residence_state: str = Form(""), residence_lga: str = Form("")):
    with connection() as conn:
        session, org, allowed = approved_org(conn, request)
        verify_csrf(session, csrf_token)
    if not allowed:
        return redirect("/organisation")
    permitted = {row["claim_code"] for row in PolicyEngine().available_claims(session["actor_id"])}
    if claim_code not in permitted:
        return page(request, "verification_choices.html", session=session, organisation=org,
                    claims=PolicyEngine().available_claims(session["actor_id"]),
                    error="This verification is not available for your organization.")
    try:
        prepared = prepare_request(claim_code, identifier, operator, threshold_low,
                                   threshold_high, tuple(classes), purpose, surname=surname,
                                   first_name=first_name, middle_name=middle_name,
                                   residence_state=residence_state, residence_lga=residence_lga)
    except ValueError as exc:
        claim = ClaimCode(claim_code)
        return page(request, "verification_details.html", session=session, organisation=org,
                    error=str(exc), values={"identifier": identifier, "operator": operator,
                    "threshold_low": threshold_low, "threshold_high": threshold_high,
                    "classes": classes, "purpose": purpose, "surname": surname,
                    "first_name": first_name, "middle_name": middle_name,
                    "residence_state": residence_state, "residence_lga": residence_lga},
                    **claim_form_context(claim))
    with connection() as conn:
        token = create_submission(conn, session["actor_id"], prepared.claim)
    return page(request, "verification_review.html", session=session, organisation=org,
                prepared=prepared, submission_token=token,
                definition=CLAIM_CATALOG[prepared.claim], consent_claim=prepared.claim in CONSENT_CLAIMS,
                information_returned=information_returned(prepared.claim))


@app.post("/organisation/verifications/submit", response_class=HTMLResponse)
def verification_submit(request: Request, csrf_token: str = Form(...), submission_token: str = Form(...),
                        claim_code: str = Form(...), identifier: str = Form(...), operator: str = Form(""),
                        threshold_low: str = Form(""), threshold_high: str = Form(""),
                        classes: list[str] = Form(default=[]), purpose: str = Form(...),
                        surname: str = Form(""), first_name: str = Form(""), middle_name: str = Form(""),
                        residence_state: str = Form(""), residence_lga: str = Form("")):
    with connection() as conn:
        session, org, allowed = approved_org(conn, request)
        verify_csrf(session, csrf_token)
    if not allowed:
        return redirect("/organisation")
    try:
        prepared = prepare_request(claim_code, identifier, operator, threshold_low,
                                   threshold_high, tuple(classes), purpose, surname=surname,
                                   first_name=first_name, middle_name=middle_name,
                                   residence_state=residence_state, residence_lga=residence_lga)
        with connection() as conn:
            verification_id, denied_message = submit_request(conn, session["actor_id"], submission_token, prepared)
            if denied_message:
                return page(request, "verification_review.html", session=session, organisation=org,
                            prepared=prepared, submission_token=submission_token,
                            definition=CLAIM_CATALOG[prepared.claim], consent_claim=prepared.claim in CONSENT_CLAIMS,
                            information_returned=information_returned(prepared.claim),
                            error=denied_message)
            row = fetch_one(conn, "SELECT public_reference FROM verifications WHERE id=%s", (verification_id,))
        return redirect(f"/organisation/verifications/{row['public_reference']}")
    except (ValueError, VerificationError) as exc:
        safe = str(exc) if isinstance(exc, ValueError) else exc.safe_message
        return page(request, "verification_expired.html", session=session, organisation=org, error=safe)


@app.get("/organisation/verifications/{reference}", response_class=HTMLResponse)
def verification_detail(request: Request, reference: str):
    with connection() as conn:
        session = require_actor(conn, request, "ORGANISATION")
        expire_requests(conn)
        org = fetch_one(conn, """SELECT o.business_name,o.status,c.name category_name
            FROM organisations o JOIN organisation_categories c ON c.id=o.category_id WHERE o.id=%s""", (session["actor_id"],))
        row = fetch_one(conn, """SELECT v.id,v.public_reference,v.subject_reference,v.claim_code,v.condition_expression,
            v.purpose,v.result,v.subject_authority,v.source_record_id,v.issued_at,v.expires_at,v.created_at,cr.status consent_status
            FROM verifications v LEFT JOIN consent_requests cr ON cr.verification_id=v.id
            WHERE v.public_reference=%s AND v.organisation_id=%s""", (reference, session["actor_id"]))
        receipt = fetch_one(conn, "SELECT verification_token FROM receipts WHERE verification_id=%s", (row["id"],)) if row else None
        disclosure = organisation_disclosure(conn, session["actor_id"], row["id"]) if row and row["result"] == "CONDITION_SATISFIED" and row["claim_code"] in {claim.value for claim in DISCLOSURE_CLAIMS} else None
        conn.commit()
    if not row:
        return redirect("/organisation")
    receipt_reference = reference if receipt else None
    verification = display_verification(row)
    verification["issued_display"] = wat_time(row.get("issued_at"))
    verification["expires_display"] = wat_time(row.get("expires_at"))
    return page(request, "verification_result.html", session=session, organisation=org,
                verification=verification, receipt_reference=receipt_reference,
                photograph_url=(f"/organisation/verifications/{reference}/identity-photograph"
                                if row["result"] in {"CONDITION_SATISFIED", "CONDITION_NOT_SATISFIED"}
                                and row.get("source_record_id") else None),
                disclosure=disclosure)


@app.get("/organisation/verifications/{reference}/identity-photograph")
def verification_identity_photograph(request: Request, reference: str):
    with connection() as conn:
        session = require_actor(conn, request, "ORGANISATION")
        verification_source = fetch_one(conn, """SELECT subject_authority,source_record_id FROM verifications
            WHERE public_reference=%s AND organisation_id=%s
              AND result IN ('CONDITION_SATISFIED','CONDITION_NOT_SATISFIED')""", (reference, session["actor_id"]))
        if not verification_source or not verification_source["source_record_id"]:
            return Response(status_code=404)
        service_code = verification_source["subject_authority"]
        if not is_available(conn, service_code):
            record_unavailable(conn, service_code, "ORGANISATION", session["actor_id"], reference)
            conn.commit()
            return Response(status_code=503)
        if not allow_identity_photo(conn, session["actor_id"]):
            conn.commit()
            return Response(status_code=429)
        photo_reference = photograph_reference_for_verification(conn, session["actor_id"], reference)
        if not photo_reference:
            conn.commit()
            return Response(status_code=404)
        try:
            content = portrait_png(photo_reference)
        except ValueError:
            return Response(status_code=404)
        record_photo_view(conn, session["actor_id"], reference)
        conn.commit()
    return Response(content=content, media_type="image/jpeg", headers={
        "Content-Disposition": "inline", "Cache-Control": "no-store, private",
    })


@app.get("/verify-result/{token}", response_class=HTMLResponse)
def public_verification_result(request: Request, token: str):
    with connection() as conn:
        if allow_public_authenticity_check(conn):
            state, payload, receipt = verify_receipt(conn, token)
            audit(conn, "RESULT_AUTHENTICITY_CHECKED", "SYSTEM", None,
                  receipt["transaction_id"] if receipt else None, {"state": state})
        else:
            state, payload, receipt = "UNAVAILABLE", None, None
        conn.commit()
    definition = None
    requirement = None
    if payload:
        try:
            claim = ClaimCode(payload["claim"])
            definition = CLAIM_CATALOG[claim]
            requirement = (definition.label.removeprefix("Request ").capitalize()
                           if payload["condition"] == "DISCLOSED_WITH_CONSENT"
                           else condition_label(claim, payload["condition"]))
            payload["issued_display"] = wat_time(datetime.fromisoformat(payload["issued_at"].replace("Z", "+00:00")))
            payload["expires_display"] = wat_time(datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00")))
        except (ValueError, KeyError):
            state, payload = "INVALID", None
    requested_return = request.query_params.get("return_to", "")
    back_url = (requested_return if requested_return.startswith("/organisation/receipts/")
                and "?" not in requested_return and "#" not in requested_return else None)
    response = page(request, "public_verification_result.html", state=state, payload=payload,
                    definition=definition, requirement=requirement, back_url=back_url)
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


@app.get("/citizen/activate", response_class=HTMLResponse)
def activation_form(request: Request):
    return page(request, "citizen_activate.html", step="phone")


@app.post("/citizen/activate/request")
def activation_request(request: Request, phone: str = Form(...)):
    try:
        phone = normalize_phone(phone)
    except ValueError as exc:
        return page(request, "citizen_activate.html", step="phone", error=str(exc))
    challenge_id = None
    with connection() as conn:
        if not is_available(conn, "SMS"):
            record_unavailable(conn, "SMS", "SYSTEM", None, "ACCOUNT_ACTIVATION")
            conn.commit()
            return page(request, "citizen_activate.html", step="phone", error="The activation code could not be sent at this time. Please try again later.")
        phone_context = current_phone_session(conn, request)
        citizen = fetch_one(conn, "SELECT citizen_id, account_activated FROM citizens WHERE registered_phone=%s AND record_status='ACTIVE'", (phone,))
        if citizen and citizen["account_activated"]:
            return page(request, "citizen_activate.html", step="phone", message="This TrustID account is already active. Please sign in using your registered mobile number and TrustID PIN.")
        if citizen:
            execute(conn, "UPDATE otp_challenges SET consumed_at=UTC_TIMESTAMP() WHERE citizen_id=%s AND purpose='ACCOUNT_ACTIVATION' AND consumed_at IS NULL", (citizen["citizen_id"],))
            nonce = new_token()
            code = derive_delivery_otp(nonce)
            execute(conn, """INSERT INTO otp_challenges (citizen_id,purpose,code_hash,expires_at)
                VALUES (%s,'ACCOUNT_ACTIVATION',%s,%s)""",
                (citizen["citizen_id"], digest_token(code), utcnow_naive() + timedelta(minutes=settings.otp_ttl_minutes)))
            challenge_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            access_token = new_token()
            execute(conn, """INSERT INTO sms_deliveries
                (challenge_id,phone_session_id,citizen_id,access_token_hash,code_nonce,recipient_mask,message_type,delivery_status,delivery_attempted_at,delivered_at,expires_at)
                VALUES (%s,%s,%s,%s,%s,%s,'ACCOUNT_ACTIVATION','SENT',UTC_TIMESTAMP(),UTC_TIMESTAMP(),%s)""",
                (challenge_id, phone_context["id"] if phone_context and phone_context["citizen_id"] == citizen["citizen_id"] else None, citizen["citizen_id"],
                 digest_token(access_token), nonce, mask_phone(phone), utcnow_naive() + timedelta(minutes=settings.otp_ttl_minutes)))
            conn.commit()
        else:
            return page(request, "citizen_activate.html", step="verify", challenge_id=0,
                        error="Phone number not found. Check the number and try again.")
    return page(request, "citizen_activate.html", step="verify", challenge_id=challenge_id or 0, message="An activation code has been sent. Kindly check your SMS inbox.")


@app.get("/phone/inbox/{access_token}", response_class=HTMLResponse)
def sms_inbox(request: Request, access_token: str):
    with connection() as conn:
        delivery = fetch_one(conn, """SELECT d.id, c.citizen_id, z.registered_phone
            FROM sms_deliveries d JOIN otp_challenges c ON c.id=d.challenge_id
            JOIN citizens z ON z.citizen_id=c.citizen_id
            WHERE d.access_token_hash=%s AND d.expires_at > UTC_TIMESTAMP()""", (digest_token(access_token),))
        if not delivery:
            return page(request, "phone_connect.html", error="This message link is invalid or has expired.")
        token = create_phone_session(conn, delivery["registered_phone"], delivery["citizen_id"])
        phone_session_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
        execute(conn, "UPDATE sms_deliveries SET phone_session_id=%s WHERE id=%s", (phone_session_id, delivery["id"]))
        conn.commit()
    response = redirect("/phone/messages")
    set_phone_cookie(response, token)
    return response


@app.post("/citizen/activate/complete")
def activation_complete(request: Request, challenge_id: int = Form(...), otp: str = Form(...), pin: str = Form(...), pin_confirm: str = Form(...)):
    try:
        validate_pin(pin)
        if pin != pin_confirm:
            raise ValueError("PIN confirmation does not match")
    except ValueError as exc:
        return page(request, "citizen_activate.html", step="verify", challenge_id=challenge_id, error=str(exc))
    with connection() as conn:
        challenge = fetch_one(conn, """SELECT * FROM otp_challenges WHERE id=%s AND purpose='ACCOUNT_ACTIVATION' FOR UPDATE""", (challenge_id,))
        invalid = not challenge or challenge["consumed_at"] or challenge["expires_at"] <= utcnow_naive() or challenge["failed_attempts"] >= settings.auth_max_attempts or not constant_time_equal(digest_token(otp.strip()), challenge["code_hash"])
        if invalid:
            if challenge and not challenge["consumed_at"]:
                execute(conn, "UPDATE otp_challenges SET failed_attempts=failed_attempts+1 WHERE id=%s", (challenge_id,))
                conn.commit()
            return page(request, "citizen_activate.html", step="verify", challenge_id=challenge_id, error="The activation code is invalid or has expired.")
        execute(conn, """UPDATE citizens SET pin_hash=%s, account_activated=TRUE, activated_at=UTC_TIMESTAMP(),
            failed_pin_attempts=0, locked_until=NULL WHERE citizen_id=%s AND account_activated=FALSE""", (hash_password(pin), challenge["citizen_id"]))
        execute(conn, "UPDATE otp_challenges SET consumed_at=UTC_TIMESTAMP() WHERE id=%s", (challenge_id,))
        audit(conn, "ACCOUNT_ACTIVATED", "CITIZEN", challenge["citizen_id"], None, {"channel": "WEB"})
        conn.commit()
    return redirect("/citizen/login?activated=1")


@app.get("/citizen/login", response_class=HTMLResponse)
def citizen_login_form(request: Request, activated: int = 0):
    return page(request, "login.html", title="Citizen login", action="/citizen/login", identifier_label="Registered phone", password_label="TrustID PIN (numbers only)", message="Your account has been activated successfully. You can now sign in." if activated else None)


@app.post("/citizen/login")
def citizen_login(request: Request, identifier: str = Form(...), password: str = Form(...)):
    error = "The credentials provided are invalid or the account is temporarily unavailable."
    try:
        phone = normalize_phone(identifier)
    except ValueError:
        phone = ""
    with connection() as conn:
        citizen = fetch_one(conn, "SELECT * FROM citizens WHERE registered_phone=%s", (phone,)) if phone else None
        valid = citizen and citizen["account_activated"] and citizen["pin_hash"] and not (citizen["locked_until"] and citizen["locked_until"] > utcnow_naive()) and verify_password(password, citizen["pin_hash"])
        if not valid:
            if citizen and citizen["account_activated"]:
                failed_citizen_login(conn, citizen["citizen_id"])
                conn.commit()
            return page(request, "login.html", title="Citizen login", action="/citizen/login", identifier_label="Registered phone", password_label="TrustID PIN (numbers only)", error=error)
        execute(conn, "UPDATE citizens SET failed_pin_attempts=0, locked_until=NULL, last_login_at=UTC_TIMESTAMP() WHERE citizen_id=%s", (citizen["citizen_id"],))
        token, _ = create_session(conn, "CITIZEN", citizen["citizen_id"])
        conn.commit()
    response = redirect("/citizen")
    set_session_cookie(response, token)
    return response


@app.get("/citizen", response_class=HTMLResponse)
def citizen_dashboard(request: Request, history_page: int = 1, q: str = "", status: str = "",
                      claim: str = "", date_from: str = "", date_to: str = ""):
    with connection() as conn:
        session = require_actor(conn, request, "CITIZEN")
        citizen = fetch_one(conn, "SELECT citizen_id, full_name, registered_phone, account_activated, last_login_at FROM citizens WHERE citizen_id=%s", (session["actor_id"],))
        clean_from = date_from if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_from) else ""
        clean_to = date_to if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_to) else ""
        requests = citizen_requests(conn, session["actor_id"], history_page=history_page,
                                    query=q, status=status, claim=claim,
                                    date_from=clean_from, date_to=clean_to)
        conn.commit()
    return page(request, "citizen_dashboard.html", session=session, citizen=citizen, requests=requests)


@app.get("/citizen/requests/{request_id}", response_class=HTMLResponse)
def citizen_request(request: Request, request_id: int):
    with connection() as conn:
        session = require_actor(conn, request, "CITIZEN")
        item = record_consent_view(conn, session["actor_id"], request_id)
        conn.commit()
    if not item:
        return redirect("/citizen")
    return page(request, "citizen_request_detail.html", session=session, item=item)


@app.get("/citizen/requests/{request_id}/approve", response_class=HTMLResponse)
def citizen_approve_form(request: Request, request_id: int):
    with connection() as conn:
        session = require_actor(conn, request, "CITIZEN")
        item = consent_request_detail(conn, session["actor_id"], request_id)
        conn.commit()
    if not item or item["status"] != "PENDING":
        return redirect(f"/citizen/requests/{request_id}")
    return page(request, "citizen_request_approve.html", session=session, item=item)


@app.post("/citizen/requests/{request_id}/approve", response_class=HTMLResponse)
def citizen_approve_start(request: Request, request_id: int, csrf_token: str = Form(...), pin: str = Form(...)):
    with connection() as conn:
        session = require_actor(conn, request, "CITIZEN")
        verify_csrf(session, csrf_token)
        item = consent_request_detail(conn, session["actor_id"], request_id)
        try:
            challenge_id = start_web_approval(conn, session["actor_id"], request_id, pin)
            conn.commit()
        except ConsentError as exc:
            conn.commit()
            return page(request, "citizen_request_approve.html", session=session, item=item, error=str(exc))
    return page(request, "citizen_request_code.html", session=session, item=item, challenge_id=challenge_id)


@app.post("/citizen/requests/{request_id}/confirm", response_class=HTMLResponse)
def citizen_approve_confirm(request: Request, request_id: int, csrf_token: str = Form(...),
                            challenge_id: int = Form(...), code: str = Form(...)):
    with connection() as conn:
        session = require_actor(conn, request, "CITIZEN")
        verify_csrf(session, csrf_token)
        item = consent_request_detail(conn, session["actor_id"], request_id)
        try:
            approve_consent(conn, session["actor_id"], request_id, channel="WEB", challenge_id=challenge_id, code=code)
            conn.commit()
        except ConsentError as exc:
            conn.commit()
            return page(request, "citizen_request_code.html", session=session, item=item,
                        challenge_id=challenge_id, error=str(exc))
    return page(request, "citizen_request_complete.html", session=session, action="approved")


@app.get("/citizen/requests/{request_id}/decline", response_class=HTMLResponse)
def citizen_decline_form(request: Request, request_id: int):
    with connection() as conn:
        session = require_actor(conn, request, "CITIZEN")
        item = consent_request_detail(conn, session["actor_id"], request_id)
        conn.commit()
    if not item or item["status"] != "PENDING":
        return redirect(f"/citizen/requests/{request_id}")
    return page(request, "citizen_request_decline.html", session=session, item=item)


@app.post("/citizen/requests/{request_id}/decline", response_class=HTMLResponse)
def citizen_decline(request: Request, request_id: int, csrf_token: str = Form(...), pin: str = Form(...)):
    with connection() as conn:
        session = require_actor(conn, request, "CITIZEN")
        verify_csrf(session, csrf_token)
        item = consent_request_detail(conn, session["actor_id"], request_id)
        try:
            reject_consent(conn, session["actor_id"], request_id, pin)
            conn.commit()
        except ConsentError as exc:
            conn.commit()
            return page(request, "citizen_request_decline.html", session=session, item=item, error=str(exc))
    return page(request, "citizen_request_complete.html", session=session, action="declined")


@app.get("/phone", response_class=HTMLResponse)
def phone_home(request: Request):
    with connection() as conn:
        phone = current_phone_session(conn, request)
        unread_count = phone_unread_count(conn, phone)
    if not phone:
        return page(request, "phone_connect.html")
    return page(request, "phone_home.html", phone=phone, unread_count=unread_count)


@app.post("/phone/connect")
def phone_connect(request: Request, phone_number: str = Form(...)):
    try:
        phone_number = normalize_phone(phone_number)
    except ValueError as exc:
        return page(request, "phone_connect.html", error=str(exc))
    with connection() as conn:
        citizen = fetch_one(conn, "SELECT citizen_id FROM citizens WHERE registered_phone=%s AND record_status='ACTIVE'", (phone_number,))
        token = create_phone_session(conn, phone_number, citizen["citizen_id"] if citizen else None)
        conn.commit()
    response = redirect("/phone")
    set_phone_cookie(response, token)
    return response


@app.post("/phone/disconnect")
def phone_disconnect(request: Request):
    with connection() as conn:
        phone = current_phone_session(conn, request)
        if phone:
            execute(conn, "UPDATE phone_sessions SET revoked_at=UTC_TIMESTAMP() WHERE id=%s", (phone["id"],))
            conn.commit()
    response = redirect("/phone")
    clear_phone_cookie(response)
    return response


@app.get("/phone/messages", response_class=HTMLResponse)
def phone_messages(request: Request):
    with connection() as conn:
        phone = current_phone_session(conn, request)
        if not phone:
            return redirect("/phone")
        deliveries = []
        if phone["citizen_id"]:
            rows = fetch_all(conn, """SELECT d.id,d.message_type,d.delivery_status,d.created_at,d.expires_at,d.opened_at,
                o.business_name FROM sms_deliveries d
                LEFT JOIN consent_requests cr ON cr.id=d.consent_request_id
                LEFT JOIN organisations o ON o.id=cr.organisation_id
                WHERE d.citizen_id=%s AND d.delivery_status='SENT'
                ORDER BY d.created_at DESC LIMIT 50""", (phone["citizen_id"],))
            for row in rows:
                deliveries.append(row)
        unread_count = phone_unread_count(conn, phone)
    return page(request, "phone_messages.html", phone=phone, deliveries=deliveries,
                unread_count=unread_count, now=utcnow_naive())


@app.get("/phone/messages/{message_id}", response_class=HTMLResponse)
def phone_message_detail(request: Request, message_id: int):
    with connection() as conn:
        phone = current_phone_session(conn, request)
        if not phone:
            return redirect("/phone")
        delivery = fetch_one(conn, """SELECT d.id,d.code_nonce,d.message_type,d.delivery_status,d.created_at,
            d.expires_at,d.opened_at,c.consumed_at,o.business_name,cd.display_name
            FROM sms_deliveries d LEFT JOIN otp_challenges c ON c.id=d.challenge_id
            LEFT JOIN consent_requests cr ON cr.id=COALESCE(d.consent_request_id,c.consent_request_id)
            LEFT JOIN organisations o ON o.id=cr.organisation_id
            LEFT JOIN claim_definitions cd ON cd.claim_code=cr.claim_code
            WHERE d.id=%s AND d.citizen_id=%s AND d.delivery_status='SENT'""", (message_id, phone["citizen_id"]))
        if not delivery:
            return redirect("/phone/messages")
        if not delivery["opened_at"]:
            execute(conn, "UPDATE sms_deliveries SET opened_at=UTC_TIMESTAMP() WHERE id=%s", (message_id,))
            conn.commit()
        activation_code = derive_delivery_otp(delivery["code_nonce"]) if delivery["code_nonce"] else None
        unread_count = phone_unread_count(conn, phone)
    return page(request, "phone_message_detail.html", phone=phone, delivery=delivery,
                activation_code=activation_code, unread_count=unread_count, now=utcnow_naive())


@app.get("/phone/dialer", response_class=HTMLResponse)
def phone_dialer(request: Request):
    with connection() as conn:
        phone = current_phone_session(conn, request)
    if not phone:
        return redirect("/phone")
    return page(request, "phone_dialer.html", phone=phone)


@app.post("/phone/dial")
def phone_dial(request: Request, service_code: str = Form(...)):
    with connection() as conn:
        phone = current_phone_session(conn, request)
        if not phone:
            return redirect("/phone")
        if service_code.strip() != "*7305#":
            return page(request, "phone_ussd.html", phone=phone, step="message", ussd_message="Invalid service code. Please check the code and try again.")
        if not is_available(conn, "USSD"):
            record_unavailable(conn, "USSD", "SYSTEM", None, "USSD_DIAL")
            message = unavailable_message(conn, "USSD")
            conn.commit()
            return page(request, "phone_ussd.html", phone=phone, step="message", ussd_message=message)
        if not phone["citizen_id"]:
            return page(request, "phone_ussd.html", phone=phone, step="message", ussd_message="This mobile number is not recognized. Please dial using the mobile number registered with your NIN.")
        citizen = fetch_one(conn, "SELECT citizen_id, account_activated FROM citizens WHERE citizen_id=%s AND record_status='ACTIVE'", (phone["citizen_id"],))
        if not citizen:
            return page(request, "phone_ussd.html", phone=phone, step="message", ussd_message="TrustID service is currently unavailable for this identity record. Please try again later.")
        token = new_token()
        execute(conn, "UPDATE ussd_sessions SET state='ENDED', ended_at=UTC_TIMESTAMP() WHERE phone_session_id=%s AND ended_at IS NULL", (phone["id"],))
        initial_state = "AWAITING_LOGIN_PIN" if citizen["account_activated"] else "MENU"
        execute(conn, """INSERT INTO ussd_sessions
            (token_hash,phone_session_id,citizen_id,state,expires_at)
            VALUES (%s,%s,%s,%s,%s)""",
            (digest_token(token), phone["id"], citizen["citizen_id"], initial_state,
             utcnow_naive() + timedelta(minutes=settings.ussd_session_ttl_minutes)))
        conn.commit()
    if citizen["account_activated"]:
        return page(request, "phone_ussd.html", phone=phone, step="prompt",
                    prompt="Welcome back to TrustID. Enter your TrustID PIN using numbers only", input_label="TrustID PIN",
                    navigation_label="Exit", ussd_token=token)
    return page(request, "phone_ussd.html", phone=phone, step="menu", account_active=False, ussd_token=token)


def ussd_prompt(request: Request, phone: dict, session: dict, token: str, error: str | None = None):
    state = session["state"]
    if state == "MENU":
        return page(request, "phone_ussd.html", phone=phone, step="menu",
                    account_active=bool(session["account_activated"]), ussd_token=token, error=error)
    if state.startswith("CONSENT_") or state == "RECENT_DECISIONS":
        with connection() as conn:
            if state == "CONSENT_MENU":
                count = fetch_one(conn, """SELECT COUNT(*) count FROM consent_requests
                    WHERE citizen_id=%s AND status='PENDING' AND expires_at>UTC_TIMESTAMP()""", (session["citizen_id"],))["count"]
                prompt = f"{count} {'request is' if count == 1 else 'requests are'} awaiting your attention."
                options = ["1. Review requests", "2. Recent decisions", "0. Exit"]
            elif state == "CONSENT_LIST":
                rows = fetch_all(conn, """SELECT cr.id,cr.claim_code,o.business_name FROM consent_requests cr
                    JOIN organisations o ON o.id=cr.organisation_id WHERE cr.citizen_id=%s
                    AND cr.status='PENDING' AND cr.expires_at>UTC_TIMESTAMP()
                    ORDER BY cr.expires_at LIMIT 5""", (session["citizen_id"],))
                prompt = "Choose a request" if rows else "You have no requests awaiting your attention."
                options = [f"{index}. {row['business_name'][:24]} — {('registered residence' if row['claim_code'] == 'REGISTERED_RESIDENCE' else CLAIM_CATALOG[ClaimCode(row['claim_code'])].label.removeprefix('Request '))}" for index, row in enumerate(rows, 1)] + ["0. Back"]
            elif state in {"CONSENT_DETAIL", "CONSENT_APPROVE_CONFIRM", "CONSENT_REJECT_CONFIRM"}:
                row = fetch_one(conn, """SELECT cr.id,cr.claim_code,cr.purpose,cr.expires_at,o.business_name FROM consent_requests cr
                    JOIN organisations o ON o.id=cr.organisation_id WHERE cr.id=%s AND cr.citizen_id=%s
                    AND cr.status='PENDING' AND cr.expires_at>UTC_TIMESTAMP()""", (session["selected_consent_id"], session["citizen_id"]))
                if not row:
                    prompt, options = "This request is no longer awaiting your decision.", ["0. Back"]
                else:
                    residence_check = row["claim_code"] == "REGISTERED_RESIDENCE"
                    info = ("registered residence" if residence_check else
                            CLAIM_CATALOG[ClaimCode(row["claim_code"])].label.removeprefix("Request "))
                    if state == "CONSENT_DETAIL":
                        expiry = (row["expires_at"] + timedelta(hours=1)).strftime("%d %b, %I:%M %p")
                        action = "wants to verify your" if residence_check else "requests your"
                        prompt = f"{row['business_name'][:30]} {action} {info}. Purpose: {row['purpose'][:70]}. Expires: {expiry}"
                        options = ["1. Approve", "2. Decline", "0. Back"]
                    elif state == "CONSENT_APPROVE_CONFIRM":
                        prompt = (f"Approve this request? The match result will be provided to {row['business_name'][:30]}."
                                  if residence_check else
                                  f"Approve this request? Your {info} will be provided to {row['business_name'][:30]}.")
                        options = ["1. Confirm approval", "0. Go back"]
                    else:
                        prompt = (f"Decline this request? {row['business_name'][:30]} will not receive the match result."
                                  if residence_check else
                                  f"Decline this request? {row['business_name'][:30]} will not receive your {info}.")
                        options = ["1. Confirm decline", "0. Go back"]
            else:
                rows = fetch_all(conn, """SELECT cr.status,cr.claim_code,o.business_name FROM consent_requests cr
                    JOIN organisations o ON o.id=cr.organisation_id WHERE cr.citizen_id=%s AND cr.status<>'PENDING'
                    ORDER BY COALESCE(cr.resolved_at,cr.expires_at) DESC LIMIT 5""", (session["citizen_id"],))
                prompt = "Recent decisions" if rows else "You have no recent decisions."
                options = [f"{row['business_name'][:22]} — {('Declined' if row['status']=='REJECTED' else row['status'].title())}" for row in rows] + ["0. Back"]
        return page(request, "phone_ussd.html", phone=phone, step="consent", prompt=prompt,
                    options=options, ussd_token=token, error=error)
    prompts = {
        "AWAITING_NEW_PIN": ("Create a 4–6 digit TrustID PIN using numbers only", "New PIN"),
        "AWAITING_PIN_CONFIRMATION": ("Confirm your TrustID PIN using numbers only", "Confirm PIN"),
        "AWAITING_LOGIN_PIN": ("Enter your TrustID PIN using numbers only", "TrustID PIN"),
    }
    prompt, label = prompts[state]
    return page(request, "phone_ussd.html", phone=phone, step="prompt", prompt=prompt,
                input_label=label, navigation_label="Exit" if state == "AWAITING_LOGIN_PIN" else "Back",
                ussd_token=token, error=error)


@app.post("/phone/ussd/respond")
def phone_ussd_respond(request: Request, ussd_token: str = Form(...), response: str = Form(...)):
    with connection() as conn:
        phone = current_phone_session(conn, request)
        if not phone:
            return redirect("/phone")
        session = fetch_one(conn, """SELECT u.*, c.account_activated, c.pin_hash, c.locked_until
            FROM ussd_sessions u JOIN citizens c ON c.citizen_id=u.citizen_id
            WHERE u.token_hash=%s AND u.phone_session_id=%s FOR UPDATE""",
            (digest_token(ussd_token), phone["id"]))
        if not session or session["ended_at"] or session["expires_at"] <= utcnow_naive():
            return page(request, "phone_ussd.html", phone=phone, step="message", ussd_message="Your session has ended for your security. Please dial *7305# to start again.")
        answer = response.strip()
        execute(conn, "UPDATE ussd_sessions SET last_active_at=UTC_TIMESTAMP(), expires_at=%s WHERE id=%s",
                (utcnow_naive() + timedelta(minutes=settings.ussd_session_ttl_minutes), session["id"]))

        if session["state"] == "CONSENT_MENU":
            if answer == "0":
                execute(conn, "UPDATE ussd_sessions SET state='ENDED',ended_at=UTC_TIMESTAMP() WHERE id=%s", (session["id"],))
                conn.commit()
                return page(request, "phone_ussd.html", phone=phone, step="message", ussd_message="Thank you for using TrustID.")
            next_state = {"1": "CONSENT_LIST", "2": "RECENT_DECISIONS"}.get(answer)
            if not next_state:
                conn.commit()
                return ussd_prompt(request, phone, session, ussd_token, "Please enter an available option.")
            execute(conn, "UPDATE ussd_sessions SET state=%s WHERE id=%s", (next_state, session["id"]))
            conn.commit(); session["state"] = next_state
            return ussd_prompt(request, phone, session, ussd_token)

        if session["state"] == "CONSENT_LIST":
            if answer == "0":
                execute(conn, "UPDATE ussd_sessions SET state='CONSENT_LIST',selected_consent_id=NULL WHERE id=%s", (session["id"],))
                conn.commit(); session["state"] = "CONSENT_MENU"
                return ussd_prompt(request, phone, session, ussd_token)
            rows = fetch_all(conn, """SELECT id FROM consent_requests WHERE citizen_id=%s AND status='PENDING'
                AND expires_at>UTC_TIMESTAMP() ORDER BY expires_at LIMIT 5""", (session["citizen_id"],))
            try:
                selected = rows[int(answer)-1] if int(answer) > 0 else None
            except (ValueError, IndexError):
                selected = None
            if not selected:
                conn.commit()
                return ussd_prompt(request, phone, session, ussd_token, "Please choose an available request.")
            execute(conn, "UPDATE ussd_sessions SET state='CONSENT_DETAIL',selected_consent_id=%s WHERE id=%s", (selected["id"], session["id"]))
            conn.commit(); session.update({"state": "CONSENT_DETAIL", "selected_consent_id": selected["id"]})
            return ussd_prompt(request, phone, session, ussd_token)

        if session["state"] in {"CONSENT_DETAIL", "CONSENT_APPROVE_CONFIRM", "CONSENT_REJECT_CONFIRM"}:
            if answer == "0":
                previous = "CONSENT_LIST" if session["state"] == "CONSENT_DETAIL" else "CONSENT_DETAIL"
                execute(conn, "UPDATE ussd_sessions SET state=%s WHERE id=%s", (previous, session["id"]))
                conn.commit(); session["state"] = previous
                return ussd_prompt(request, phone, session, ussd_token)
            if session["state"] == "CONSENT_DETAIL":
                next_state = {"1": "CONSENT_APPROVE_CONFIRM", "2": "CONSENT_REJECT_CONFIRM"}.get(answer)
                if not next_state:
                    conn.commit(); return ussd_prompt(request, phone, session, ussd_token, "Please enter 1, 2 or 0.")
                execute(conn, "UPDATE ussd_sessions SET state=%s WHERE id=%s", (next_state, session["id"]))
                conn.commit(); session["state"] = next_state
                return ussd_prompt(request, phone, session, ussd_token)
            if answer != "1":
                conn.commit(); return ussd_prompt(request, phone, session, ussd_token, "Please enter 1 to confirm or 0 to go back.")
            try:
                approved = session["state"] == "CONSENT_APPROVE_CONFIRM"
                ussd_decide(conn, session["citizen_id"], session["selected_consent_id"], approved)
                execute(conn, "UPDATE ussd_sessions SET state='CONSENT_MENU',selected_consent_id=NULL WHERE id=%s", (session["id"],))
                conn.commit()
            except ConsentError as exc:
                conn.rollback()
                return page(request, "phone_ussd.html", phone=phone, step="message", ussd_message=str(exc))
            return page(request, "phone_ussd.html", phone=phone, step="message",
                        ussd_message="Your approval has been recorded successfully." if approved else "The request has been declined.",
                        continue_ussd=True, ussd_token=ussd_token)

        if session["state"] == "RECENT_DECISIONS":
            if answer == "0":
                execute(conn, "UPDATE ussd_sessions SET state='CONSENT_MENU' WHERE id=%s", (session["id"],))
                conn.commit(); session["state"] = "CONSENT_MENU"
                return ussd_prompt(request, phone, session, ussd_token)
            conn.commit(); return ussd_prompt(request, phone, session, ussd_token, "Enter 0 to go back.")

        if session["state"] == "MENU":
            if answer == "2":
                execute(conn, "UPDATE ussd_sessions SET state='ENDED', ended_at=UTC_TIMESTAMP() WHERE id=%s", (session["id"],))
                conn.commit()
                return page(request, "phone_ussd.html", phone=phone, step="message", ussd_message="Thank you for using TrustID.")
            if answer != "1":
                conn.commit()
                return ussd_prompt(request, phone, session, ussd_token, "Invalid option. Please enter 1 or 2.")
            next_state = "AWAITING_LOGIN_PIN" if session["account_activated"] else "AWAITING_NEW_PIN"
            execute(conn, "UPDATE ussd_sessions SET state=%s WHERE id=%s", (next_state, session["id"]))
            conn.commit()
            session["state"] = next_state
            return ussd_prompt(request, phone, session, ussd_token)

        if answer == "0":
            if session["state"] == "AWAITING_LOGIN_PIN":
                execute(conn, "UPDATE ussd_sessions SET state='ENDED', ended_at=UTC_TIMESTAMP() WHERE id=%s", (session["id"],))
                conn.commit()
                return page(request, "phone_ussd.html", phone=phone, step="message", ussd_message="Session ended.")
            execute(conn, "UPDATE ussd_sessions SET state='MENU', pending_pin_hash=NULL WHERE id=%s", (session["id"],))
            conn.commit()
            session["state"] = "MENU"
            return ussd_prompt(request, phone, session, ussd_token)

        if session["state"] == "AWAITING_NEW_PIN":
            try:
                validate_pin(answer)
            except ValueError:
                conn.commit()
                return ussd_prompt(request, phone, session, ussd_token, "Enter a 4–6 digit TrustID PIN using numbers only. Avoid repeated or consecutive numbers.")
            execute(conn, "UPDATE ussd_sessions SET state='AWAITING_PIN_CONFIRMATION', pending_pin_hash=%s WHERE id=%s",
                    (hash_password(answer), session["id"]))
            conn.commit()
            session["state"] = "AWAITING_PIN_CONFIRMATION"
            return ussd_prompt(request, phone, session, ussd_token)

        if session["state"] == "AWAITING_PIN_CONFIRMATION":
            if not session["pending_pin_hash"] or not verify_password(answer, session["pending_pin_hash"]):
                execute(conn, "UPDATE ussd_sessions SET state='AWAITING_NEW_PIN', pending_pin_hash=NULL WHERE id=%s", (session["id"],))
                conn.commit()
                session["state"] = "AWAITING_NEW_PIN"
                return ussd_prompt(request, phone, session, ussd_token, "The PINs do not match. Please create your PIN again.")
            changed = execute(conn, """UPDATE citizens SET pin_hash=%s, account_activated=TRUE,
                activated_at=UTC_TIMESTAMP(), failed_pin_attempts=0, locked_until=NULL
                WHERE citizen_id=%s AND account_activated=FALSE""", (session["pending_pin_hash"], session["citizen_id"]))
            execute(conn, "UPDATE ussd_sessions SET state='ENDED', ended_at=UTC_TIMESTAMP(), pending_pin_hash=NULL WHERE id=%s", (session["id"],))
            if changed != 1:
                conn.commit()
                return page(request, "phone_ussd.html", phone=phone, step="message", ussd_message="This account is already active. Please sign in instead.")
            audit(conn, "ACCOUNT_ACTIVATED", "CITIZEN", session["citizen_id"], None, {"channel": "USSD"})
            conn.commit()
            return page(request, "phone_ussd.html", phone=phone, step="message", ussd_message="Your TrustID account has been activated successfully.")

        locked = session["locked_until"] and session["locked_until"] > utcnow_naive()
        valid = session["account_activated"] and session["pin_hash"] and not locked and verify_password(answer, session["pin_hash"])
        if not valid:
            if session["account_activated"] and not locked:
                failed_citizen_login(conn, session["citizen_id"])
                refreshed = fetch_one(conn, "SELECT locked_until FROM citizens WHERE citizen_id=%s", (session["citizen_id"],))
                locked = bool(refreshed and refreshed["locked_until"] and refreshed["locked_until"] > utcnow_naive())
            conn.commit()
            message = "Access has been temporarily restricted after multiple unsuccessful attempts. Please try again later." if locked else "The PIN entered is incorrect. Please try again."
            return ussd_prompt(request, phone, session, ussd_token, message)
        execute(conn, "UPDATE citizens SET failed_pin_attempts=0, locked_until=NULL, last_login_at=UTC_TIMESTAMP() WHERE citizen_id=%s", (session["citizen_id"],))
        execute(conn, "UPDATE ussd_sessions SET state='CONSENT_MENU' WHERE id=%s", (session["id"],))
        auth_token, _ = create_session(conn, "CITIZEN", session["citizen_id"])
        conn.commit()
        session["state"] = "CONSENT_MENU"
    result = ussd_prompt(request, phone, session, ussd_token)
    set_session_cookie(result, auth_token)
    return result


@app.post("/phone/ussd/cancel")
def phone_ussd_cancel(request: Request, ussd_token: str = Form(...)):
    with connection() as conn:
        phone = current_phone_session(conn, request)
        if not phone:
            return redirect("/phone")
        execute(conn, """UPDATE ussd_sessions SET state='ENDED', ended_at=UTC_TIMESTAMP(), pending_pin_hash=NULL
            WHERE token_hash=%s AND phone_session_id=%s AND ended_at IS NULL""",
            (digest_token(ussd_token), phone["id"]))
        conn.commit()
    return page(request, "phone_ussd.html", phone=phone, step="message", ussd_message="Session ended.")


@app.get("/ussd")
def ussd_home():
    return redirect("/phone/dialer")
