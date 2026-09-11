import hashlib
import hmac

from ..config import settings


def subject_reference(organisation_id: int, record_id: int, secret: str | None = None,
                      *, authority: str = "NATIONAL_ID") -> str:
    key = secret if secret is not None else settings.pseudonym_hmac_secret
    if len(key) < 32 or key.startswith("change-me"):
        raise RuntimeError("PSEUDONYM_HMAC_SECRET must be a random value of at least 32 characters")
    if authority not in {"NATIONAL_ID", "DRIVING_LICENCE"}:
        raise ValueError("Unsupported subject authority")
    # Preserve the established national-identity pseudonym contract while
    # domain-separating independent licence authority subjects.
    raw = f"{organisation_id}:{record_id}" if authority == "NATIONAL_ID" else f"{organisation_id}:{authority}:{record_id}"
    message = raw.encode("utf-8")
    digest = hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"SUB-{digest[:10].upper()}"


def unconfirmed_subject_reference(organisation_id: int, submitted_identifier: str,
                                  secret: str | None = None) -> str:
    """Create an organization-scoped reference without retaining an unmatched NIN."""
    key = secret if secret is not None else settings.pseudonym_hmac_secret
    if len(key) < 32 or key.startswith("change-me"):
        raise RuntimeError("PSEUDONYM_HMAC_SECRET must be a random value of at least 32 characters")
    message = f"{organisation_id}:NATIONAL_ID:UNCONFIRMED:{submitted_identifier}".encode("utf-8")
    digest = hmac.new(key.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"SUB-{digest[:10].upper()}"
