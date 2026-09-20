from dataclasses import dataclass
from datetime import datetime, timedelta
import math
import re

from .auth import utcnow_naive
from .db import fetch_all, fetch_one
from .signing import verification_url, verify_receipt
from .verification import ClaimCode
from .verification.catalog import CLAIM_CATALOG, condition_label
from .verifier import display_verification


PAGE_SIZE = 20
REFERENCE_PATTERN = re.compile(r"^(VR|SUB)-[A-Z0-9-]+$", re.IGNORECASE)
RESULT_FILTERS = {
    "completed": ("CONDITION_SATISFIED", "CONDITION_NOT_SATISFIED"),
    "pending": ("PENDING",),
    "met": ("CONDITION_SATISFIED",),
    "not_met": ("CONDITION_NOT_SATISFIED",),
    "declined": ("DENIED",),
}
RECEIPT_FILTERS = {"current", "expired", "integrity"}


def wat_time(value: datetime | None, *, stored_as_utc: bool = True) -> str:
    if not value:
        return "—"
    # Signed-result times are stored as UTC. Legacy DEFAULT CURRENT_TIMESTAMP
    # request times use the database server's configured Lagos time.
    local = value + timedelta(hours=1) if stored_as_utc else value
    return f"{local.day} {local.strftime('%b %Y')}, {local.strftime('%I:%M %p').lstrip('0')} WAT"


def _safe_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _safe_page(value: int) -> int:
    return max(1, min(int(value or 1), 10000))


def _base_filters(query: str, claim: str, date_from: str, date_to: str):
    clauses: list[str] = []
    params: list[object] = []
    clean_query = query.strip().upper()[:30]
    if clean_query and REFERENCE_PATTERN.fullmatch(clean_query):
        column = "v.public_reference" if clean_query.startswith("VR-") else "v.subject_reference"
        clauses.append(f"{column}=%s")
        params.append(clean_query)
    else:
        clean_query = ""
    if claim in {item.value for item in ClaimCode}:
        clauses.append("v.claim_code=%s")
        params.append(claim)
    else:
        claim = ""
    start = _safe_date(date_from)
    end = _safe_date(date_to)
    if start:
        clauses.append("v.created_at >= %s")
        params.append(start)
    else:
        date_from = ""
    if end:
        clauses.append("v.created_at < %s")
        params.append(end + timedelta(days=1))
    else:
        date_to = ""
    return clauses, params, {
        "q": clean_query, "claim": claim, "date_from": date_from, "date_to": date_to,
    }


def verification_history(conn, organisation_id: int, *, tab: str = "all", query: str = "",
                         status: str = "", claim: str = "", date_from: str = "",
                         date_to: str = "", page: int = 1) -> dict:
    tab = "receipts" if tab == "receipts" else "all"
    page = _safe_page(page)
    clauses, params, filters = _base_filters(query, claim, date_from, date_to)
    clauses.insert(0, "v.organisation_id=%s")
    params.insert(0, organisation_id)

    if tab == "receipts":
        joins = "JOIN receipts r ON r.verification_id=v.id LEFT JOIN consent_requests cr ON cr.verification_id=v.id"
        if status not in RECEIPT_FILTERS:
            status = ""
    else:
        joins = "LEFT JOIN receipts r ON r.verification_id=v.id LEFT JOIN consent_requests cr ON cr.verification_id=v.id"
        if status in RESULT_FILTERS:
            values = RESULT_FILTERS[status]
            marks = ",".join(["%s"] * len(values))
            clauses.append(f"v.result IN ({marks})")
            params.extend(values)
        else:
            status = ""

    where = " AND ".join(clauses)
    select_sql = f"""SELECT v.id,v.public_reference,v.subject_reference,v.claim_code,
        v.condition_expression,v.purpose,v.result,v.issued_at,v.expires_at,v.created_at,
        r.transaction_id,r.verification_token,cr.status consent_status
        FROM verifications v {joins} WHERE {where}
        ORDER BY v.created_at DESC"""
    if tab == "receipts":
        rows = fetch_all(conn, select_sql, tuple(params))
    else:
        rows = fetch_all(conn, select_sql + " LIMIT %s OFFSET %s", tuple(params + [PAGE_SIZE, (page - 1) * PAGE_SIZE]))

    items = []
    for raw in rows:
        item = display_verification(raw)
        item["created_display"] = wat_time(raw["created_at"], stored_as_utc=False)
        item["expires_display"] = wat_time(raw.get("expires_at"))
        item["receipt_state"] = None
        if raw.get("verification_token"):
            state, _, _ = verify_receipt(conn, raw["verification_token"])
            item["receipt_state"] = state
            item["receipt_status"] = {
                "CURRENT": "Authentic and current", "EXPIRED": "Authentic but expired",
                "INVALID": "Integrity issue", "UNAVAILABLE": "Unavailable",
            }[state]
        items.append(item)

    if tab == "receipts" and status:
        expected = {"current": "CURRENT", "expired": "EXPIRED", "integrity": "INVALID"}[status]
        items = [item for item in items if item["receipt_state"] == expected]
    if tab == "receipts":
        count = len(items)
        items = items[(page - 1) * PAGE_SIZE:page * PAGE_SIZE]
    else:
        count = fetch_one(conn, f"SELECT COUNT(*) count FROM verifications v {joins} WHERE {where}", tuple(params))["count"]
    filters.update({"status": status, "tab": tab})
    return {
        "items": items, "filters": filters, "page": page,
        "pages": max(1, math.ceil(count / PAGE_SIZE)), "total": count,
        "start": (page - 1) * PAGE_SIZE + 1 if count else 0,
        "end": min(page * PAGE_SIZE, count),
    }


def organisation_receipt(conn, organisation_id: int, transaction_id: str) -> dict | None:
    row = fetch_one(conn, """SELECT r.verification_token,r.transaction_id,v.purpose
        FROM receipts r JOIN verifications v ON v.id=r.verification_id
        WHERE r.transaction_id=%s AND r.organisation_id=%s""", (transaction_id, organisation_id))
    if not row:
        return None
    state, payload, receipt = verify_receipt(conn, row["verification_token"])
    if state in {"INVALID", "UNAVAILABLE"} or not payload or not receipt:
        return {"transaction_id": row["transaction_id"], "state": state, "safe": False}
    claim = ClaimCode(payload["claim"])
    direct = claim in {ClaimCode.FULL_LEGAL_NAME, ClaimCode.STATE_OF_ORIGIN, ClaimCode.RESIDENTIAL_ADDRESS}
    return {
        "transaction_id": row["transaction_id"], "state": state, "safe": True,
        "result": payload["result"],
        "status_label": "Authentic and current" if state == "CURRENT" else "Authentic but expired",
        "definition": CLAIM_CATALOG[claim],
        "requirement": (CLAIM_CATALOG[claim].label.removeprefix("Request ").capitalize() if direct else condition_label(claim, payload["condition"])),
        "outcome": (
            "Information provided" if direct and payload["result"] == "CONDITION_SATISFIED" else
            "Name match confirmed" if claim == ClaimCode.NAME_MATCH and payload["result"] == "CONDITION_SATISFIED" else
            "Name match not confirmed" if claim == ClaimCode.NAME_MATCH else
            "Residence confirmed" if claim == ClaimCode.REGISTERED_RESIDENCE and payload["result"] == "CONDITION_SATISFIED" else
            "Residence not confirmed" if claim == ClaimCode.REGISTERED_RESIDENCE else
            "Requirement met" if payload["result"] == "CONDITION_SATISFIED" else "Requirement not met"
        ),
        "verification_reference": payload["verification_id"], "organisation_reference": payload["organisation_id"],
        "subject_reference": payload["subject_reference"], "issued": wat_time(receipt["issued_at"]),
        "expires": wat_time(receipt["expires_at"]), "purpose": row["purpose"],
        "verification_link": verification_url(row["verification_token"]),
        "offline_verification_link": verification_url(row["verification_token"]) + "/offline",
    }


def receipt_count(conn, organisation_id: int) -> int:
    return fetch_one(conn, "SELECT COUNT(*) count FROM receipts WHERE organisation_id=%s", (organisation_id,))["count"]
