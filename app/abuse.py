"""Privacy-safe repeated verification controls and administrative summaries."""
from dataclasses import dataclass
from datetime import timedelta
import hashlib

from .auth import audit, utcnow_naive
from .db import execute, fetch_all, fetch_one

AGE_WINDOW = timedelta(minutes=30)
AGE_ATTEMPT_LIMIT = 3
BLOCK_MESSAGE = "This verification cannot continue because too many similar requests were made recently. Please try again later."


@dataclass(frozen=True)
class AttemptDecision:
    allowed: bool
    attempt_number: int
    recent_allowed: int
    reason_code: str | None = None


def acquire_age_guard(conn, organisation_id: int, identifier: str) -> None:
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:24]
    lock_name = f"trustid:age:{organisation_id}:{digest}"
    acquired = fetch_one(conn, "SELECT GET_LOCK(%s,5) acquired", (lock_name,))
    if not acquired or acquired["acquired"] != 1:
        raise RuntimeError("Unable to acquire age-verification guard")


def reserve_age_attempt(conn, organisation_id: int, citizen_reference: str, *, now=None,
                        limit: int = AGE_ATTEMPT_LIMIT, window: timedelta = AGE_WINDOW) -> AttemptDecision:
    moment = now or utcnow_naive()
    execute(conn, """INSERT IGNORE INTO inference_guards
        (organisation_id,subject_reference,claim_family,last_activity_at)
        VALUES (%s,%s,'AGE',%s)""", (organisation_id, citizen_reference, moment))
    fetch_one(conn, """SELECT organisation_id FROM inference_guards
        WHERE organisation_id=%s AND subject_reference=%s AND claim_family='AGE' FOR UPDATE""",
        (organisation_id, citizen_reference))
    recent = fetch_one(conn, """SELECT COUNT(*) count FROM request_history
        WHERE organisation_id=%s AND subject_reference=%s AND claim_family='AGE'
        AND decision='ALLOWED' AND timestamp>%s""",
        (organisation_id, citizen_reference, moment - window))["count"]
    total = fetch_one(conn, """SELECT COUNT(*) count FROM request_history
        WHERE organisation_id=%s AND subject_reference=%s AND claim_family='AGE'
        AND timestamp>%s""",
        (organisation_id, citizen_reference, moment - window))["count"]
    allowed, attempt = recent < limit, total + 1
    reason = None if allowed else "REPEATED_AGE_VERIFICATION"
    execute(conn, """INSERT INTO request_history
        (organisation_id,subject_reference,claim_family,operator,threshold_low,threshold_high,
         decision,attempt_number,reason_code,timestamp)
        VALUES (%s,%s,'AGE','PENDING',NULL,NULL,%s,%s,%s,%s)""",
        (organisation_id, citizen_reference, "ALLOWED" if allowed else "BLOCKED", attempt, reason, moment))
    history_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
    execute(conn, """UPDATE inference_guards SET last_activity_at=%s
        WHERE organisation_id=%s AND subject_reference=%s AND claim_family='AGE'""",
        (moment, organisation_id, citizen_reference))
    if not allowed:
        audit(conn, "INFERENCE_RISK_FLAGGED", "ORGANISATION", organisation_id,
              citizen_reference, {"incident_id": history_id, "claim_family": "AGE",
                                  "attempt_number": attempt, "reason_code": reason})
    return AttemptDecision(allowed, attempt, recent, reason)


def finalize_age_attempt(conn, organisation_id: int, citizen_reference: str,
                         operator: str, threshold_low, threshold_high) -> None:
    execute(conn, """UPDATE request_history SET operator=%s,threshold_low=%s,threshold_high=%s
        WHERE organisation_id=%s AND subject_reference=%s AND claim_family='AGE'
        AND decision='ALLOWED' AND operator='PENDING' ORDER BY id DESC LIMIT 1""",
        (operator, str(threshold_low) if threshold_low is not None else None,
         str(threshold_high) if threshold_high is not None else None,
         organisation_id, citizen_reference))


def security_overview(conn) -> dict:
    return {
        "blocked": fetch_one(conn, "SELECT COUNT(*) count FROM request_history WHERE decision='BLOCKED'")["count"],
        "flagged_organisations": fetch_one(conn, "SELECT COUNT(DISTINCT organisation_id) count FROM request_history WHERE decision='BLOCKED'")["count"],
        "recent_incidents": fetch_one(conn, "SELECT COUNT(*) count FROM request_history WHERE decision='BLOCKED' AND timestamp>=UTC_TIMESTAMP()-INTERVAL 24 HOUR")["count"],
        "rate_limits": fetch_one(conn, "SELECT COUNT(*) count FROM audit_log WHERE event_type='RATE_LIMIT_TRIGGERED'")["count"],
        "locked_accounts": fetch_one(conn, """SELECT
            (SELECT COUNT(*) FROM organisations WHERE locked_until>UTC_TIMESTAMP())+
            (SELECT COUNT(*) FROM admin_users WHERE locked_until>UTC_TIMESTAMP())+
            (SELECT COUNT(*) FROM citizens WHERE locked_until>UTC_TIMESTAMP()) count""")["count"],
    }


def security_incidents(conn, *, organisation="", decision="", date_from="", date_to="", citizen_reference=""):
    clauses, params = ["1=1"], []
    if organisation.strip():
        clauses.append("(o.business_name LIKE %s OR o.public_reference LIKE %s)")
        term = f"%{organisation.strip()}%"; params.extend((term, term))
    if decision in {"ALLOWED", "BLOCKED"}:
        clauses.append("h.decision=%s"); params.append(decision)
    if date_from:
        clauses.append("h.timestamp>=%s"); params.append(date_from)
    if date_to:
        clauses.append("h.timestamp<DATE_ADD(%s,INTERVAL 1 DAY)"); params.append(date_to)
    if citizen_reference.strip():
        clauses.append("h.subject_reference=%s"); params.append(citizen_reference.strip().upper())
    return fetch_all(conn, f"""SELECT h.id,h.subject_reference,h.claim_family,h.operator,h.threshold_low,
        h.threshold_high,h.decision,h.attempt_number,h.reason_code,h.timestamp,
        o.id organisation_id,o.public_reference organisation_reference,o.business_name,
        c.name category_name,o.status organisation_status
        FROM request_history h JOIN organisations o ON o.id=h.organisation_id
        JOIN organisation_categories c ON c.id=o.category_id
        WHERE {' AND '.join(clauses)} ORDER BY h.timestamp DESC,h.id DESC LIMIT 500""", tuple(params))


def security_incident(conn, incident_id: int):
    return fetch_one(conn, """SELECT h.*,o.public_reference organisation_reference,o.business_name,
        o.status organisation_status,c.name category_name,
        (SELECT COUNT(*) FROM request_history previous WHERE previous.organisation_id=h.organisation_id
         AND previous.decision='BLOCKED' AND previous.id<>h.id) previous_incidents
        FROM request_history h JOIN organisations o ON o.id=h.organisation_id
        JOIN organisation_categories c ON c.id=o.category_id WHERE h.id=%s""", (incident_id,))
