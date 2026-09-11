import hashlib
import hmac
import re
import secrets

import bcrypt

from .config import settings

PHONE_RE = re.compile(r"^\+234\d{10}$")
COMMON_PASSWORDS = {
    "1234567890", "administrator", "changeme123", "letmein1234",
    "password", "password1", "password123", "qwerty12345", "trustid123",
}


def hash_password(value: str) -> str:
    return bcrypt.hashpw(value.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(value: str, encoded_hash: str) -> bool:
    try:
        return bcrypt.checkpw(value.encode("utf-8"), encoded_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def validate_password(value: str) -> None:
    if len(value) < 10:
        raise ValueError("Password must contain at least 10 characters")
    if len(value) > 64 or len(value.encode("utf-8")) > 72:
        raise ValueError("Password must not exceed 64 characters")
    normalized = re.sub(r"\s+", "", value).casefold()
    if normalized in COMMON_PASSWORDS:
        raise ValueError("This password is too common. Choose a different password")


def validate_pin(value: str) -> None:
    if not re.fullmatch(r"\d{4,6}", value) or len(set(value)) == 1 or value in {"1234", "12345", "123456"}:
        raise ValueError("Enter a 4–6 digit TrustID PIN using numbers only. Avoid repeated or consecutive numbers.")


def normalize_phone(value: str) -> str:
    compact = re.sub(r"[\s()-]", "", value)
    if compact.startswith("0") and len(compact) == 11:
        compact = "+234" + compact[1:]
    elif compact.startswith("234"):
        compact = "+" + compact
    if not PHONE_RE.fullmatch(compact):
        raise ValueError("Enter a valid Nigerian phone number")
    return compact


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_organisation_reference() -> str:
    """Return a stable, non-sequential public organization reference."""
    return "ORG-" + secrets.token_hex(6).upper()


def digest_token(token: str) -> str:
    return hmac.new(settings.session_secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def derive_delivery_otp(nonce: str) -> str:
    digest = hmac.new(settings.session_secret.encode(), f"sms:{nonce}".encode(), hashlib.sha256).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 1_000_000:06d}"


def mask_phone(phone: str) -> str:
    return f"{phone[:7]}***{phone[-3:]}"


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
