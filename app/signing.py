import base64
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import secrets

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
import qrcode

from .auth import audit, utcnow_naive
from .config import settings
from .db import execute, fetch_one


SIGNED_FIELDS = (
    "verification_id", "issuer", "claim", "condition", "result",
    "organisation_id", "subject_reference", "issued_at", "expires_at",
)


class SigningUnavailable(RuntimeError):
    pass


PUBLIC_AUTHENTICITY_LIMIT_PER_MINUTE = 300


def utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonicalize(payload: dict) -> str:
    if tuple(payload.keys()) != SIGNED_FIELDS or any(not isinstance(value, str) for value in payload.values()):
        raise ValueError("Signed payload does not match the frozen contract")
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def parse_canonical(value: str) -> dict:
    payload = json.loads(value)
    if not isinstance(payload, dict) or set(payload) != set(SIGNED_FIELDS):
        raise ValueError("Signed payload has an invalid structure")
    if any(not isinstance(payload[field], str) for field in SIGNED_FIELDS):
        raise ValueError("Signed payload has an invalid value type")
    if canonicalize({field: payload[field] for field in SIGNED_FIELDS}) != value:
        raise ValueError("Signed payload is not canonical")
    return payload


def private_key() -> Ed25519PrivateKey:
    if not settings.signing_key_id or not settings.signing_private_key_b64:
        raise SigningUnavailable("TrustID signing is not configured")
    try:
        raw = base64.b64decode(settings.signing_private_key_b64, validate=True)
        return Ed25519PrivateKey.from_private_bytes(raw)
    except (ValueError, TypeError) as exc:
        raise SigningUnavailable("TrustID signing key is invalid") from exc


def public_key_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def validate_signing_configuration(conn) -> None:
    """Fail startup when the configured private key cannot sign valid receipts."""
    key = private_key()
    key_row = fetch_one(conn, "SELECT * FROM signing_keys WHERE key_id=%s", (settings.signing_key_id,))
    active = fetch_one(conn, "SELECT COUNT(*) count FROM signing_keys WHERE status='ACTIVE'")
    if (not key_row or key_row["status"] != "ACTIVE" or key_row["algorithm"] != "Ed25519"
            or key_row["public_key_b64"] != public_key_b64(key) or not active or active["count"] != 1):
        raise SigningUnavailable("TrustID signing configuration does not match the active public key")


def allow_public_authenticity_check(conn, *, limit: int = PUBLIC_AUTHENTICITY_LIMIT_PER_MINUTE) -> bool:
    """Apply a global, privacy-safe MySQL limit without storing visitor identifiers."""
    now = utcnow_naive().replace(second=0, microsecond=0)
    execute(conn, """INSERT INTO authenticity_rate_limits (bucket_start,request_count)
        VALUES (%s,1) ON DUPLICATE KEY UPDATE request_count=LEAST(request_count+1,%s)""",
        (now, limit + 1))
    row = fetch_one(conn, "SELECT request_count,event_recorded FROM authenticity_rate_limits WHERE bucket_start=%s FOR UPDATE", (now,))
    if row["request_count"] <= limit:
        return True
    if not row["event_recorded"]:
        execute(conn, "UPDATE authenticity_rate_limits SET event_recorded=TRUE WHERE bucket_start=%s", (now,))
        audit(conn, "RATE_LIMIT_TRIGGERED", "SYSTEM", None, "PUBLIC_VERIFICATION",
              {"scope": "PUBLIC_RESULT", "window_minutes": 1, "count": limit + 1})
    return False


def sign_completed_result(conn, verification_id: int) -> dict:
    existing = fetch_one(conn, "SELECT * FROM receipts WHERE verification_id=%s", (verification_id,))
    if existing:
        return existing
    row = fetch_one(conn, """SELECT v.id,v.public_reference,v.claim_code,v.condition_expression,v.result,
        v.subject_reference,v.issued_at,v.expires_at,o.id organisation_id,o.public_reference organisation_reference
        FROM verifications v JOIN organisations o ON o.id=v.organisation_id
        WHERE v.id=%s FOR UPDATE""", (verification_id,))
    if not row or row["result"] not in {"CONDITION_SATISFIED", "CONDITION_NOT_SATISFIED"}:
        raise SigningUnavailable("Only completed verification results can be signed")
    if not row["organisation_reference"]:
        organisation_reference = "ORG-" + secrets.token_hex(6).upper()
        execute(conn, "UPDATE organisations SET public_reference=%s WHERE id=%s AND public_reference IS NULL",
                (organisation_reference, row["organisation_id"]))
        row["organisation_reference"] = fetch_one(
            conn, "SELECT public_reference FROM organisations WHERE id=%s", (row["organisation_id"],)
        )["public_reference"]
    key = private_key()
    key_row = fetch_one(conn, "SELECT * FROM signing_keys WHERE key_id=%s FOR UPDATE", (settings.signing_key_id,))
    if not key_row or key_row["status"] != "ACTIVE" or key_row["public_key_b64"] != public_key_b64(key):
        raise SigningUnavailable("The active signing key does not match configuration")
    payload = {
        "verification_id": row["public_reference"], "issuer": "TrustID",
        "claim": row["claim_code"], "condition": row["condition_expression"],
        "result": row["result"], "organisation_id": row["organisation_reference"],
        "subject_reference": row["subject_reference"], "issued_at": utc_text(row["issued_at"]),
        "expires_at": utc_text(row["expires_at"]),
    }
    canonical = canonicalize(payload)
    signature = base64.b64encode(key.sign(canonical.encode("utf-8"))).decode("ascii")
    token = secrets.token_urlsafe(32)
    execute(conn, """INSERT INTO receipts
        (transaction_id,verification_token,verification_id,claim_code,condition_expression,result,
         issued_at,expires_at,organisation_id,subject_reference,canonical_payload,signature,
         signing_key_id,algorithm,integrity_status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'Ed25519','VALID')""",
        (row["public_reference"], token, row["id"], row["claim_code"], row["condition_expression"],
         row["result"], row["issued_at"], row["expires_at"], row["organisation_id"],
         row["subject_reference"], canonical, signature, settings.signing_key_id))
    audit(conn, "RESULT_SIGNED", "SYSTEM", None, row["public_reference"],
          {"claim_code": row["claim_code"], "key_id": settings.signing_key_id})
    return fetch_one(conn, "SELECT * FROM receipts WHERE verification_id=%s", (verification_id,))


def verify_receipt(conn, token: str) -> tuple[str, dict | None, dict | None]:
    if len(token) != 43 or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in token):
        return "UNAVAILABLE", None, None
    row = fetch_one(conn, """SELECT r.*,o.public_reference organisation_reference
        FROM receipts r JOIN organisations o ON o.id=r.organisation_id WHERE r.verification_token=%s""", (token,))
    if not row:
        return "UNAVAILABLE", None, None
    try:
        payload = parse_canonical(row["canonical_payload"])
        key = fetch_one(conn, "SELECT * FROM signing_keys WHERE key_id=%s", (row["signing_key_id"],))
        if not key or key["status"] == "REVOKED" or key["algorithm"] != "Ed25519":
            raise ValueError("Signing key is unavailable")
        Ed25519PublicKey.from_public_bytes(base64.b64decode(key["public_key_b64"], validate=True)).verify(
            base64.b64decode(row["signature"], validate=True), row["canonical_payload"].encode("utf-8"))
        expected = {
            "verification_id": row["transaction_id"], "claim": row["claim_code"],
            "condition": row["condition_expression"], "result": row["result"],
            "organisation_id": row["organisation_reference"], "subject_reference": row["subject_reference"],
            "issued_at": utc_text(row["issued_at"]), "expires_at": utc_text(row["expires_at"]),
        }
        if payload["issuer"] != "TrustID" or any(payload[field] != value for field, value in expected.items()):
            raise ValueError("Receipt columns do not match the signed payload")
        expires = datetime.fromisoformat(payload["expires_at"].replace("Z", "+00:00"))
        state = "EXPIRED" if expires <= datetime.now(timezone.utc) else "CURRENT"
    except (ValueError, TypeError, json.JSONDecodeError, InvalidSignature):
        return "INVALID", None, row
    return state, payload, row


def verification_url(token: str) -> str:
    return f"{settings.public_base_url}/verify-result/{token}"


def qr_data_url(url: str) -> str:
    image = qrcode.make(url)
    output = BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
