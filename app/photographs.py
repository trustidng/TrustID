from datetime import datetime
from io import BytesIO
from pathlib import Path
import re

from PIL import Image

from .auth import audit, utcnow_naive
from .db import execute, fetch_one


PHOTO_REFERENCE = re.compile(r"^PHOTO-(\d{4})$")
PHOTO_LIMIT_PER_MINUTE = 120
PORTRAIT_SHEET = (Path(__file__).resolve().parents[1] / "trusted_source_assets" /
                  "identity_photographs" / "synthetic_portraits_4x4.png")


def allow_identity_photo(conn, organisation_id: int, *, limit: int = PHOTO_LIMIT_PER_MINUTE) -> bool:
    bucket = utcnow_naive().replace(second=0, microsecond=0)
    execute(conn, """INSERT INTO identity_photo_rate_limits
        (organisation_id,bucket_start,request_count) VALUES (%s,%s,1)
        ON DUPLICATE KEY UPDATE request_count=LEAST(request_count+1,%s)""",
        (organisation_id, bucket, limit + 1))
    row = fetch_one(conn, """SELECT request_count,event_recorded FROM identity_photo_rate_limits
        WHERE organisation_id=%s AND bucket_start=%s FOR UPDATE""", (organisation_id, bucket))
    if row["request_count"] <= limit:
        return True
    if not row["event_recorded"]:
        execute(conn, """UPDATE identity_photo_rate_limits SET event_recorded=TRUE
            WHERE organisation_id=%s AND bucket_start=%s""", (organisation_id, bucket))
        audit(conn, "RATE_LIMIT_TRIGGERED", "ORGANISATION", organisation_id,
              "IDENTITY_PHOTOGRAPH", {"scope": "IDENTITY_PHOTO", "window_minutes": 1})
    return False


def photograph_reference_for_verification(conn, organisation_id: int, reference: str) -> str | None:
    row = fetch_one(conn, """SELECT v.id,v.public_reference,v.result,v.subject_authority,v.source_record_id
        FROM verifications v JOIN organisations o ON o.id=v.organisation_id
        WHERE v.public_reference=%s AND v.organisation_id=%s AND o.status='APPROVED'""",
        (reference, organisation_id))
    if (not row or row["result"] not in {"CONDITION_SATISFIED", "CONDITION_NOT_SATISFIED"}
            or not row["source_record_id"]):
        return None
    if row["subject_authority"] == "NATIONAL_ID":
        source = fetch_one(conn, """SELECT identity_photograph_reference photograph_reference
            FROM citizens WHERE citizen_id=%s""", (row["source_record_id"],))
    elif row["subject_authority"] == "DRIVING_LICENCE":
        source = fetch_one(conn, """SELECT holder_photograph_reference photograph_reference
            FROM licences WHERE licence_record_id=%s""", (row["source_record_id"],))
    else:
        return None
    return source["photograph_reference"] if source else None


def portrait_png(photo_reference: str) -> bytes:
    match = PHOTO_REFERENCE.fullmatch(photo_reference or "")
    if not match or not PORTRAIT_SHEET.is_file():
        raise ValueError("Photograph unavailable")
    index = int(match.group(1)) - 1
    if not 0 <= index < 16:
        raise ValueError("Photograph unavailable")
    with Image.open(PORTRAIT_SHEET) as sheet:
        width, height = sheet.size
        column, row = index % 4, index // 4
        left, top = column * width // 4, row * height // 4
        right, bottom = (column + 1) * width // 4, (row + 1) * height // 4
        portrait = sheet.crop((left, top, right, bottom)).convert("RGB")
        output = BytesIO()
        portrait.save(output, format="JPEG", quality=88, optimize=True)
        return output.getvalue()


def record_photo_view(conn, organisation_id: int, verification_reference: str) -> None:
    audit(conn, "IDENTITY_PHOTO_VIEWED", "ORGANISATION", organisation_id,
          verification_reference, {"delivery": "PROTECTED_INLINE"})
