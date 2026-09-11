"""Operational service status and privacy-safe failure recording."""
import json
from .auth import audit
from .db import execute, fetch_all, fetch_one

SERVICE_CODES = {"NATIONAL_ID", "DRIVING_LICENCE", "SMS", "USSD"}
SERVICE_MESSAGES = {
    "NATIONAL_ID": "The identity verification service is temporarily unavailable. Please try again later.",
    "DRIVING_LICENCE": "The driving licence verification service is temporarily unavailable. Please try again later.",
    "SMS": "The confirmation code could not be sent at this time. Please try again later.",
    "USSD": "TrustID USSD is temporarily unavailable. Please try again later.",
}


def is_available(conn, service_code: str) -> bool:
    if service_code not in SERVICE_CODES:
        raise ValueError("Unknown service")
    row = fetch_one(conn, "SELECT status FROM service_status WHERE service_code=%s", (service_code,))
    return bool(row and row["status"] == "AVAILABLE")


def services(conn) -> list[dict]:
    return fetch_all(conn, """SELECT service_code,display_name,status,status_message,changed_at
        FROM service_status ORDER BY FIELD(service_code,'NATIONAL_ID','DRIVING_LICENCE','SMS','USSD')""")


def unavailable_message(conn, service_code: str) -> str:
    row = fetch_one(conn, "SELECT status_message FROM service_status WHERE service_code=%s", (service_code,))
    note = (row or {}).get("status_message") or ""
    if service_code == "USSD" and "maintenance" in note.lower():
        return "TrustID USSD is currently unavailable due to maintenance. Please try again later."
    return SERVICE_MESSAGES[service_code]


def service_change_history(conn, limit: int = 100, *, service: str = "", status: str = "",
                           administrator: str = "", date_from: str = "", date_to: str = "",
                           sort: str = "newest") -> list[dict]:
    where = ["a.event_type='SERVICE_STATUS_CHANGED'", "a.actor_type='ADMIN'"]
    params = []
    if service in SERVICE_CODES:
        where.append("a.target_reference=%s"); params.append(service)
    if status in {"AVAILABLE", "UNAVAILABLE"}:
        where.append("JSON_UNQUOTE(JSON_EXTRACT(a.detail,'$.status'))=%s"); params.append(status)
    if administrator.strip():
        where.append("u.username LIKE %s"); params.append(f"%{administrator.strip()[:64]}%")
    if date_from:
        where.append("DATE(a.timestamp)>=%s"); params.append(date_from)
    if date_to:
        where.append("DATE(a.timestamp)<=%s"); params.append(date_to)
    order = "a.timestamp,a.id" if sort == "oldest" else "a.timestamp DESC,a.id DESC"
    params.append(limit)
    rows = fetch_all(conn, f"""SELECT a.id,a.target_reference,a.detail,a.timestamp,u.username
        FROM audit_log a LEFT JOIN admin_users u ON u.id=a.actor_id
        WHERE {' AND '.join(where)} ORDER BY {order} LIMIT %s""", tuple(params))
    for row in rows:
        detail = row.get("detail")
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except ValueError:
                detail = {}
        row["change"] = detail or {}
    return rows


def record_unavailable(conn, service_code: str, actor_type: str, actor_id: int | None,
                       target: str | None = None) -> None:
    audit(conn, "SERVICE_UNAVAILABLE", actor_type, actor_id, target or service_code,
          {"service_code": service_code})


def change_status(conn, service_code: str, status: str, admin_id: int, message: str = "") -> None:
    if service_code not in SERVICE_CODES or status not in {"AVAILABLE", "UNAVAILABLE"}:
        raise ValueError("Invalid service status")
    current = fetch_one(conn, "SELECT status,status_message FROM service_status WHERE service_code=%s FOR UPDATE", (service_code,))
    if not current:
        raise ValueError("Service status unavailable")
    changed = execute(conn, """UPDATE service_status SET status=%s,status_message=%s,
        changed_at=UTC_TIMESTAMP(),changed_by_admin_id=%s WHERE service_code=%s""",
        (status, message.strip()[:255] or None, admin_id, service_code))
    if changed != 1:
        raise ValueError("Service status unavailable")
    audit(conn, "SERVICE_STATUS_CHANGED", "ADMIN", admin_id, service_code,
          {"service_code": service_code, "previous_status": current["status"],
           "status": status, "reason": message.strip()[:255] or None})
