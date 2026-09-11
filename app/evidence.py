from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re
import secrets


MAX_EVIDENCE_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}


@dataclass(frozen=True)
class ValidatedEvidence:
    original_filename: str
    stored_filename: str
    mime_type: str
    content: bytes
    digest: str


def validate_evidence(filename: str, content: bytes) -> ValidatedEvidence:
    safe_name = Path(filename or "").name
    extension = Path(safe_name).suffix.lower()
    if not safe_name or extension not in ALLOWED_EXTENSIONS:
        raise ValueError("Upload a PDF, JPG or PNG document.")
    if not content or len(content) > MAX_EVIDENCE_BYTES:
        raise ValueError("Each evidence file must be no larger than 5 MB.")
    detected = None
    if content.startswith(b"%PDF-"):
        detected = "application/pdf"
    elif content.startswith(b"\x89PNG\r\n\x1a\n"):
        detected = "image/png"
    elif content.startswith(b"\xff\xd8\xff"):
        detected = "image/jpeg"
    if not detected:
        raise ValueError("The selected file is not a valid PDF, JPG or PNG document.")
    expected = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}[extension]
    if detected != expected:
        raise ValueError("The file contents do not match its extension.")
    stored = f"{secrets.token_hex(24)}{extension if extension != '.jpeg' else '.jpg'}"
    return ValidatedEvidence(safe_name[:255], stored, detected, content, sha256(content).hexdigest())


def clean_document_number(value: str) -> str | None:
    value = value.strip()
    if value and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 ./_-]{1,118}[A-Za-z0-9]", value):
        raise ValueError("Enter a valid document or registration number.")
    return value or None
