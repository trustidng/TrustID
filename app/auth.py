from datetime import datetime, timedelta, timezone
import json

from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse

from .config import settings
from .db import execute, fetch_one
from .security import digest_token, new_token

SESSION_COOKIE = "trustid_session"
PHONE_COOKIE = "trustid_phone"


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def create_session(conn, actor_type: str, actor_id: int) -> tuple[str, str]:
    token, csrf = new_token(), new_token()
    execute(
        conn,
        """INSERT INTO auth_sessions
           (token_hash, actor_type, actor_id, csrf_token, expires_at)
           VALUES (%s,%s,%s,%s,%s)""",
        (digest_token(token), actor_type, actor_id, csrf, utcnow_naive() + timedelta(hours=settings.session_ttl_hours)),
    )
    return token, csrf


def set_session_cookie(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=settings.session_ttl_hours * 3600,
        httponly=True, secure=settings.cookie_secure, samesite="strict", path="/",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def create_phone_session(conn, phone_number: str, citizen_id: int | None) -> str:
    token = new_token()
    execute(
        conn,
        """INSERT INTO phone_sessions (token_hash, phone_number, citizen_id, expires_at)
           VALUES (%s,%s,%s,%s)""",
        (digest_token(token), phone_number, citizen_id, utcnow_naive() + timedelta(hours=4)),
    )
    return token


def set_phone_cookie(response, token: str) -> None:
    response.set_cookie(
        PHONE_COOKIE, token, max_age=4 * 3600, httponly=True,
        secure=settings.cookie_secure, samesite="strict", path="/",
    )


def clear_phone_cookie(response) -> None:
    response.delete_cookie(PHONE_COOKIE, path="/")


def current_phone_session(conn, request: Request):
    token = request.cookies.get(PHONE_COOKIE)
    if not token:
        return None
    phone = fetch_one(
        conn,
        """SELECT id, phone_number, citizen_id, expires_at FROM phone_sessions
           WHERE token_hash=%s AND revoked_at IS NULL AND expires_at > UTC_TIMESTAMP()""",
        (digest_token(token),),
    )
    if phone:
        execute(conn, "UPDATE phone_sessions SET last_active_at=UTC_TIMESTAMP() WHERE id=%s", (phone["id"],))
        conn.commit()
    return phone


def current_session(conn, request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    return fetch_one(
        conn,
        """SELECT id, actor_type, actor_id, csrf_token, expires_at
           FROM auth_sessions
           WHERE token_hash=%s AND revoked_at IS NULL AND expires_at > UTC_TIMESTAMP()""",
        (digest_token(token),),
    )


def require_actor(conn, request: Request, actor_type: str):
    session = current_session(conn, request)
    if not session or session["actor_type"] != actor_type:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/"})
    return session


def verify_csrf(session, submitted: str) -> None:
    if not submitted or submitted != session["csrf_token"]:
        raise HTTPException(status_code=403, detail="Invalid form token")


def audit(conn, event_type: str, actor_type: str, actor_id: int | None, target: str | None, detail: dict | None = None) -> None:
    execute(
        conn,
        """INSERT INTO audit_log (event_type, actor_type, actor_id, target_reference, detail)
           VALUES (%s,%s,%s,%s,%s)""",
        (event_type, actor_type, actor_id, target, json.dumps(detail) if detail else None),
    )


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)
