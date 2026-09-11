from datetime import timedelta
import json
import os
import unicodedata

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .auth import audit, utcnow_naive
from .config import settings
from .db import execute, fetch_all, fetch_one
from .security import constant_time_equal, derive_delivery_otp, digest_token, mask_phone, new_token, verify_password
from .resilience import SERVICE_MESSAGES, is_available, record_unavailable
from .signing import sign_completed_result
from .verification import ClaimCode
from .verification.catalog import CLAIM_CATALOG


APPROVAL_WORDING_VERSION = "2026-09-v1"
REQUEST_PAGE_SIZE = 10
DISCLOSURE_TTL = timedelta(days=30)
OTP_MAX_ATTEMPTS = 5
OTP_MAX_SENDS_PER_REQUEST = 3
OTP_RESEND_COOLDOWN = timedelta(seconds=60)

DISCLOSURE_FIELDS = {
    ClaimCode.FULL_LEGAL_NAME.value: "full_name",
    ClaimCode.STATE_OF_ORIGIN.value: "state_of_origin",
    ClaimCode.RESIDENTIAL_ADDRESS.value: "residential_address",
}
REGISTERED_RESIDENCE = ClaimCode.REGISTERED_RESIDENCE.value


class ConsentError(ValueError):
    pass


def _key() -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=b"TrustID Phase 8 disclosure",
        info=b"controlled-disclosure/v1",
    ).derive(settings.pseudonym_hmac_secret.encode("utf-8"))


def _aad(verification_id: int, organisation_id: int, citizen_id: int, claim_code: str) -> bytes:
    return f"{verification_id}:{organisation_id}:{citizen_id}:{claim_code}:v1".encode()


def encrypt_value(value: str, verification_id: int, organisation_id: int,
                  citizen_id: int, claim_code: str) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_key()).encrypt(
        nonce, value.encode("utf-8"),
        _aad(verification_id, organisation_id, citizen_id, claim_code),
    )
    return ciphertext, nonce


def decrypt_value(row: dict) -> str:
    return AESGCM(_key()).decrypt(
        bytes(row["nonce"]), bytes(row["ciphertext"]),
        _aad(row["verification_id"], row["organisation_id"], row["citizen_id"], row["claim_code"]),
    ).decode("utf-8")


def _request_aad(consent_id: int, verification_id: int, organisation_id: int, citizen_id: int) -> bytes:
    return f"request-context:{consent_id}:{verification_id}:{organisation_id}:{citizen_id}:v1".encode()


def encrypt_request_context(context: dict, consent_id: int, verification_id: int,
                            organisation_id: int, citizen_id: int) -> tuple[bytes, bytes]:
    nonce = os.urandom(12)
    payload = json.dumps(context, sort_keys=True, separators=(",", ":")).encode()
    return AESGCM(_key()).encrypt(
        nonce, payload, _request_aad(consent_id, verification_id, organisation_id, citizen_id)), nonce


def decrypt_request_context(conn, row: dict) -> dict:
    protected = fetch_one(conn, "SELECT * FROM consent_request_contexts WHERE consent_request_id=%s", (row["id"],))
    if not protected:
        raise ConsentError("TrustID cannot complete this request at the moment. Please try again later.")
    payload = AESGCM(_key()).decrypt(
        bytes(protected["nonce"]), bytes(protected["ciphertext"]),
        _request_aad(row["id"], row["verification_id"], row["organisation_id"], row["citizen_id"]))
    return json.loads(payload.decode())


def _match_text(left: str | None, right: str | None) -> bool:
    def normalized(value):
        text = unicodedata.normalize("NFKD", value or "")
        return "".join(char.casefold() for char in text
                       if not unicodedata.combining(char) and char.isalnum())
    return normalized(left) == normalized(right)


def expire_requests(conn, citizen_id: int | None = None) -> int:
    where = " AND citizen_id=%s" if citizen_id is not None else ""
    params = (citizen_id,) if citizen_id is not None else ()
    rows = fetch_all(conn, f"""SELECT id,verification_id FROM consent_requests
        WHERE status='PENDING' AND expires_at<=UTC_TIMESTAMP(){where} FOR UPDATE""", params)
    for row in rows:
        execute(conn, "UPDATE consent_requests SET status='EXPIRED',resolved_at=UTC_TIMESTAMP() WHERE id=%s AND status='PENDING'", (row["id"],))
        execute(conn, "UPDATE verifications SET result='DENIED' WHERE id=%s AND result='PENDING'", (row["verification_id"],))
        execute(conn, "DELETE FROM consent_request_contexts WHERE consent_request_id=%s", (row["id"],))
        audit(conn, "CONSENT_EXPIRED", "SYSTEM", None, str(row["verification_id"]), None)
    return len(rows)


def citizen_requests(conn, citizen_id: int, *, history_page: int = 1, query: str = "",
                     status: str = "", claim: str = "", date_from: str = "",
                     date_to: str = "") -> dict:
    expire_requests(conn, citizen_id)
    pending = fetch_all(conn, """SELECT cr.id,cr.status,cr.created_at,cr.expires_at,cr.purpose,
        cr.claim_code,o.business_name,v.public_reference
        FROM consent_requests cr JOIN organisations o ON o.id=cr.organisation_id
        JOIN verifications v ON v.id=cr.verification_id
        WHERE cr.citizen_id=%s AND cr.status='PENDING'
        ORDER BY cr.expires_at,cr.created_at DESC""", (citizen_id,))
    page = max(1, history_page)
    where, params = ["cr.citizen_id=%s", "cr.status<>'PENDING'"], [citizen_id]
    if query.strip():
        where.append("(o.business_name LIKE %s OR v.public_reference LIKE %s)")
        params.extend([f"%{query.strip()[:100]}%"] * 2)
    if status in {"APPROVED", "REJECTED", "EXPIRED"}:
        where.append("cr.status=%s"); params.append(status)
    if claim in {item.value for item in ClaimCode}:
        where.append("cr.claim_code=%s"); params.append(claim)
    if date_from:
        where.append("DATE(COALESCE(cr.resolved_at,cr.expires_at))>=%s"); params.append(date_from)
    if date_to:
        where.append("DATE(COALESCE(cr.resolved_at,cr.expires_at))<=%s"); params.append(date_to)
    joins = " FROM consent_requests cr JOIN organisations o ON o.id=cr.organisation_id JOIN verifications v ON v.id=cr.verification_id "
    total = fetch_one(conn, "SELECT COUNT(*) count" + joins + "WHERE " + " AND ".join(where), tuple(params))["count"]
    history = fetch_all(conn, """SELECT cr.id,cr.status,cr.created_at,cr.resolved_at,cr.expires_at,
        cr.claim_code,o.business_name FROM consent_requests cr
        JOIN organisations o ON o.id=cr.organisation_id
        JOIN verifications v ON v.id=cr.verification_id WHERE """ + " AND ".join(where) +
        " ORDER BY COALESCE(cr.resolved_at,cr.expires_at) DESC LIMIT %s OFFSET %s",
        tuple(params + [REQUEST_PAGE_SIZE, (page - 1) * REQUEST_PAGE_SIZE]))
    for item in pending + history:
        item["display_name"] = ("Registered residence" if item["claim_code"] == REGISTERED_RESIDENCE else
                                CLAIM_CATALOG[ClaimCode(item["claim_code"])].label.removeprefix("Request ").capitalize())
        item["binary_verification"] = item["claim_code"] == REGISTERED_RESIDENCE
        item["expires_display"] = (item["expires_at"] + timedelta(hours=1)).strftime("%d %b %Y, %I:%M %p WAT") if item.get("expires_at") else "—"
        decision_time = item.get("resolved_at") or item.get("expires_at")
        item["decision_display"] = (decision_time + timedelta(hours=1)).strftime("%d %b %Y, %I:%M %p WAT") if decision_time else "—"
    return {"pending": pending, "history": history, "history_total": total, "page": page,
            "pages": max(1, (total + REQUEST_PAGE_SIZE - 1) // REQUEST_PAGE_SIZE),
            "filters": {"q": query.strip()[:100], "status": status, "claim": claim,
                        "date_from": date_from, "date_to": date_to}}


def request_detail(conn, citizen_id: int, request_id: int, *, lock: bool = False) -> dict | None:
    expire_requests(conn, citizen_id)
    row = fetch_one(conn, f"""SELECT cr.*,o.business_name,o.status organisation_status,
        v.public_reference,v.result FROM consent_requests cr
        JOIN organisations o ON o.id=cr.organisation_id
        JOIN verifications v ON v.id=cr.verification_id
        WHERE cr.id=%s AND cr.citizen_id=%s{' FOR UPDATE' if lock else ''}""", (request_id, citizen_id))
    if row:
        row["display_name"] = ("Registered residence" if row["claim_code"] == REGISTERED_RESIDENCE else
                               CLAIM_CATALOG[ClaimCode(row["claim_code"])].label.removeprefix("Request ").capitalize())
        row["binary_verification"] = row["claim_code"] == REGISTERED_RESIDENCE
        if row["binary_verification"] and row["status"] == "PENDING":
            context = decrypt_request_context(conn, row)
            row["requested_location"] = context["state"] + (f", {context['lga']} LGA" if context.get("lga") else " State")
        row["expires_display"] = (row["expires_at"] + timedelta(hours=1)).strftime("%d %b %Y, %I:%M %p WAT") if row.get("expires_at") else "—"
        row["resolved_display"] = (row["resolved_at"] + timedelta(hours=1)).strftime("%d %b %Y, %I:%M %p WAT") if row.get("resolved_at") else "—"
    return row


def record_view(conn, citizen_id: int, request_id: int) -> dict | None:
    row = request_detail(conn, citizen_id, request_id, lock=True)
    if row and row["viewed_at"] is None:
        execute(conn, "UPDATE consent_requests SET viewed_at=UTC_TIMESTAMP() WHERE id=%s", (request_id,))
        audit(conn, "CONSENT_VIEWED", "CITIZEN", citizen_id, row["public_reference"], {"claim_code": row["claim_code"]})
    return row


def verify_citizen_pin(conn, citizen_id: int, pin: str) -> bool:
    citizen = fetch_one(conn, "SELECT pin_hash,account_activated,record_status,locked_until FROM citizens WHERE citizen_id=%s FOR UPDATE", (citizen_id,))
    now = utcnow_naive()
    valid = bool(citizen and citizen["account_activated"] and citizen["record_status"] == "ACTIVE"
                 and citizen["pin_hash"] and not (citizen["locked_until"] and citizen["locked_until"] > now)
                 and verify_password(pin, citizen["pin_hash"]))
    if valid:
        execute(conn, "UPDATE citizens SET failed_pin_attempts=0,locked_until=NULL WHERE citizen_id=%s", (citizen_id,))
    elif citizen and not (citizen["locked_until"] and citizen["locked_until"] > now):
        attempts = fetch_one(conn, "SELECT failed_pin_attempts FROM citizens WHERE citizen_id=%s", (citizen_id,))["failed_pin_attempts"] + 1
        locked_until = now + timedelta(minutes=settings.auth_lock_minutes) if attempts >= settings.auth_max_attempts else None
        execute(conn, "UPDATE citizens SET failed_pin_attempts=%s,locked_until=%s WHERE citizen_id=%s", (attempts, locked_until, citizen_id))
    return valid


def start_web_approval(conn, citizen_id: int, request_id: int, pin: str) -> int:
    row = request_detail(conn, citizen_id, request_id, lock=True)
    if not row or row["status"] != "PENDING":
        raise ConsentError("This request is no longer awaiting your approval.")
    if not verify_citizen_pin(conn, citizen_id, pin):
        raise ConsentError("The PIN entered is incorrect or your account is temporarily unavailable.")
    if not is_available(conn, "SMS"):
        record_unavailable(conn, "SMS", "CITIZEN", citizen_id, row["public_reference"])
        raise ConsentError(SERVICE_MESSAGES["SMS"])
    latest = fetch_one(conn, """SELECT created_at FROM otp_challenges WHERE consent_request_id=%s
        AND purpose='CONSENT_APPROVAL' ORDER BY created_at DESC LIMIT 1""", (request_id,))
    if latest and latest["created_at"] + OTP_RESEND_COOLDOWN > utcnow_naive():
        raise ConsentError("Please wait before requesting another confirmation code.")
    sends = fetch_one(conn, "SELECT COUNT(*) count FROM otp_challenges WHERE consent_request_id=%s AND purpose='CONSENT_APPROVAL'", (request_id,))["count"]
    if sends >= OTP_MAX_SENDS_PER_REQUEST:
        raise ConsentError("No more confirmation codes can be sent for this request.")
    execute(conn, "UPDATE otp_challenges SET invalidated_at=UTC_TIMESTAMP() WHERE consent_request_id=%s AND purpose='CONSENT_APPROVAL' AND consumed_at IS NULL AND invalidated_at IS NULL", (request_id,))
    nonce = new_token()
    code = derive_delivery_otp(nonce)
    expires = utcnow_naive() + timedelta(minutes=settings.otp_ttl_minutes)
    execute(conn, """INSERT INTO otp_challenges (citizen_id,consent_request_id,purpose,code_hash,expires_at)
        VALUES (%s,%s,'CONSENT_APPROVAL',%s,%s)""", (citizen_id, request_id, digest_token(code), expires))
    challenge_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
    phone = fetch_one(conn, "SELECT registered_phone FROM citizens WHERE citizen_id=%s", (citizen_id,))["registered_phone"]
    execute(conn, """INSERT INTO sms_deliveries
        (challenge_id,citizen_id,code_nonce,recipient_mask,message_type,delivery_status,
         delivery_attempted_at,delivered_at,expires_at)
        VALUES (%s,%s,%s,%s,'CONSENT_APPROVAL_CODE','SENT',UTC_TIMESTAMP(),UTC_TIMESTAMP(),%s)""",
        (challenge_id, citizen_id, nonce, mask_phone(phone), expires))
    audit(conn, "CONSENT_APPROVAL_STARTED", "CITIZEN", citizen_id, row["public_reference"], {"claim_code": row["claim_code"], "channel": "WEB"})
    audit(conn, "CONSENT_CODE_SENT", "SYSTEM", None, row["public_reference"], {"channel": "WEB"})
    return challenge_id


def _ensure_authorized(conn, row: dict) -> None:
    permission = fetch_one(conn, """SELECT d.privacy_mode FROM organisations o
        JOIN organisation_categories c ON c.id=o.category_id
        JOIN category_claim_permissions p ON p.category_id=c.id
        JOIN claim_definitions d ON d.claim_code=p.claim_code
        WHERE o.id=%s AND o.status='APPROVED' AND c.active=TRUE
          AND p.claim_code=%s AND d.active=TRUE AND d.privacy_mode IN ('CONSENT','STRONG_CONSENT')""",
        (row["organisation_id"], row["claim_code"]))
    if not permission:
        raise ConsentError("This request can no longer be completed.")
    if not is_available(conn, "NATIONAL_ID"):
        record_unavailable(conn, "NATIONAL_ID", "CITIZEN", row["citizen_id"], row["public_reference"])
        raise ConsentError(SERVICE_MESSAGES["NATIONAL_ID"])


def _authorization_and_value(conn, row: dict) -> str:
    _ensure_authorized(conn, row)
    field = DISCLOSURE_FIELDS.get(row["claim_code"])
    source = fetch_one(conn, f"SELECT {field} value FROM citizens WHERE citizen_id=%s AND record_status='ACTIVE'", (row["citizen_id"],)) if field else None
    if not source or not source["value"]:
        raise ConsentError("TrustID cannot complete this request at the moment. Please try again later.")
    return source["value"]


def _complete_registered_residence(conn, row: dict, now) -> str:
    _ensure_authorized(conn, row)
    context = decrypt_request_context(conn, row)
    source = fetch_one(conn, """SELECT state_of_residence,lga_of_residence FROM citizens
        WHERE citizen_id=%s AND record_status='ACTIVE'""", (row["citizen_id"],))
    if not source:
        raise ConsentError("TrustID cannot complete this request at the moment. Please try again later.")
    matched = _match_text(context.get("state"), source["state_of_residence"])
    if context.get("lga"):
        matched = matched and _match_text(context["lga"], source["lga_of_residence"])
    result = "CONDITION_SATISFIED" if matched else "CONDITION_NOT_SATISFIED"
    expires = now + timedelta(hours=24)
    execute(conn, """UPDATE verifications SET result=%s,condition_expression='REGISTERED_RESIDENCE_MATCH',
        issued_at=%s,expires_at=%s WHERE id=%s AND result='PENDING'""",
        (result, now, expires, row["verification_id"]))
    execute(conn, "DELETE FROM consent_request_contexts WHERE consent_request_id=%s", (row["id"],))
    audit(conn, "RESULT_GENERATED", "SYSTEM", None, row["public_reference"],
          {"claim_code": row["claim_code"], "result": result})
    sign_completed_result(conn, row["verification_id"])
    return result


def approve(conn, citizen_id: int, request_id: int, *, channel: str,
            challenge_id: int | None = None, code: str | None = None) -> str:
    row = request_detail(conn, citizen_id, request_id, lock=True)
    if not row or row["status"] != "PENDING":
        raise ConsentError("This request is no longer awaiting your approval.")
    if channel == "WEB":
        challenge = fetch_one(conn, """SELECT * FROM otp_challenges WHERE id=%s AND consent_request_id=%s
            AND citizen_id=%s AND purpose='CONSENT_APPROVAL' FOR UPDATE""", (challenge_id, request_id, citizen_id))
        if not challenge or challenge["consumed_at"] or challenge["invalidated_at"] or challenge["expires_at"] <= utcnow_naive():
            raise ConsentError("This confirmation code is invalid or has expired.")
        if challenge["failed_attempts"] >= OTP_MAX_ATTEMPTS or not code or not constant_time_equal(digest_token(code.strip()), challenge["code_hash"]):
            execute(conn, "UPDATE otp_challenges SET failed_attempts=failed_attempts+1 WHERE id=%s", (challenge_id,))
            raise ConsentError("This confirmation code is invalid or has expired.")
    now = utcnow_naive()
    value = None if row["claim_code"] == REGISTERED_RESIDENCE else _authorization_and_value(conn, row)
    changed = execute(conn, """UPDATE consent_requests SET status='APPROVED',resolved_channel=%s,
        resolved_at=%s,wording_version=%s WHERE id=%s AND status='PENDING' AND expires_at>UTC_TIMESTAMP()""",
        (channel, now, APPROVAL_WORDING_VERSION, request_id))
    if changed != 1:
        raise ConsentError("This request is no longer awaiting your approval.")
    if row["claim_code"] == REGISTERED_RESIDENCE:
        result = _complete_registered_residence(conn, row, now)
    else:
        expires = now + DISCLOSURE_TTL
        ciphertext, nonce = encrypt_value(value, row["verification_id"], row["organisation_id"], citizen_id, row["claim_code"])
        execute(conn, """INSERT INTO controlled_disclosures
            (verification_id,organisation_id,citizen_id,claim_code,ciphertext,nonce,issued_at,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
            (row["verification_id"], row["organisation_id"], citizen_id, row["claim_code"], ciphertext, nonce, now, expires))
        execute(conn, """UPDATE verifications SET result='CONDITION_SATISFIED',condition_expression='DISCLOSED_WITH_CONSENT',
            issued_at=%s,expires_at=%s WHERE id=%s AND result='PENDING'""", (now, expires, row["verification_id"]))
        audit(conn, "DISCLOSURE_CREATED", "SYSTEM", None, row["public_reference"], {"claim_code": row["claim_code"]})
        audit(conn, "RESULT_GENERATED", "SYSTEM", None, row["public_reference"], {"claim_code": row["claim_code"], "result": "INFORMATION_PROVIDED"})
        sign_completed_result(conn, row["verification_id"])
    if challenge_id:
        execute(conn, "UPDATE otp_challenges SET consumed_at=UTC_TIMESTAMP() WHERE id=%s", (challenge_id,))
    audit(conn, "CONSENT_APPROVED", "CITIZEN", citizen_id, row["public_reference"], {"claim_code": row["claim_code"], "channel": channel, "wording_version": APPROVAL_WORDING_VERSION})
    return row["public_reference"]


def reject(conn, citizen_id: int, request_id: int, pin: str) -> str:
    row = request_detail(conn, citizen_id, request_id, lock=True)
    if not row or row["status"] != "PENDING":
        raise ConsentError("This request is no longer awaiting your decision.")
    if not verify_citizen_pin(conn, citizen_id, pin):
        raise ConsentError("The PIN entered is incorrect or your account is temporarily unavailable.")
    changed = execute(conn, """UPDATE consent_requests SET status='REJECTED',resolved_channel='WEB',
        resolved_at=UTC_TIMESTAMP(),wording_version=%s WHERE id=%s AND status='PENDING' AND expires_at>UTC_TIMESTAMP()""",
        (APPROVAL_WORDING_VERSION, request_id))
    if changed != 1:
        raise ConsentError("This request is no longer awaiting your decision.")
    execute(conn, "UPDATE verifications SET result='DENIED' WHERE id=%s AND result='PENDING'", (row["verification_id"],))
    execute(conn, "DELETE FROM consent_request_contexts WHERE consent_request_id=%s", (request_id,))
    audit(conn, "CONSENT_REJECTED", "CITIZEN", citizen_id, row["public_reference"], {"claim_code": row["claim_code"], "channel": "WEB", "wording_version": APPROVAL_WORDING_VERSION})
    return row["public_reference"]


def ussd_decide(conn, citizen_id: int, request_id: int, approve_request: bool) -> str:
    if approve_request:
        return approve(conn, citizen_id, request_id, channel="USSD")
    row = request_detail(conn, citizen_id, request_id, lock=True)
    if not row or row["status"] != "PENDING":
        raise ConsentError("This request is no longer awaiting your decision.")
    changed = execute(conn, """UPDATE consent_requests SET status='REJECTED',resolved_channel='USSD',
        resolved_at=UTC_TIMESTAMP(),wording_version=%s WHERE id=%s AND status='PENDING' AND expires_at>UTC_TIMESTAMP()""",
        (APPROVAL_WORDING_VERSION, request_id))
    if changed != 1:
        raise ConsentError("This request is no longer awaiting your decision.")
    execute(conn, "UPDATE verifications SET result='DENIED' WHERE id=%s AND result='PENDING'", (row["verification_id"],))
    execute(conn, "DELETE FROM consent_request_contexts WHERE consent_request_id=%s", (request_id,))
    audit(conn, "CONSENT_REJECTED", "CITIZEN", citizen_id, row["public_reference"], {"claim_code": row["claim_code"], "channel": "USSD", "wording_version": APPROVAL_WORDING_VERSION})
    return row["public_reference"]


def organisation_disclosure(conn, organisation_id: int, verification_id: int) -> dict | None:
    execute(conn, "DELETE FROM controlled_disclosures WHERE expires_at<=UTC_TIMESTAMP()")
    row = fetch_one(conn, """SELECT * FROM controlled_disclosures
        WHERE verification_id=%s AND organisation_id=%s AND expires_at>UTC_TIMESTAMP()""",
        (verification_id, organisation_id))
    if not row:
        return None
    row["value"] = decrypt_value(row)
    execute(conn, "UPDATE controlled_disclosures SET last_viewed_at=UTC_TIMESTAMP() WHERE verification_id=%s", (verification_id,))
    audit(conn, "DISCLOSURE_VIEWED", "ORGANISATION", organisation_id, str(verification_id), {"claim_code": row["claim_code"]})
    return row
