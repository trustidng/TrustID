"""Database-backed Phase 6 signing, tamper, expiry, privacy, and cleanup acceptance."""
from datetime import timedelta
import base64
from io import BytesIO
from pathlib import Path
import json
import secrets
import sys

from fastapi.testclient import TestClient
from PIL import Image
import zxingcpp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import utcnow_naive
from app.db import connection, execute, fetch_all, fetch_one
from app.security import hash_password
from app.signing import (
    allow_public_authenticity_check, qr_data_url, sign_completed_result, validate_signing_configuration,
    verification_url, verify_receipt,
)
from app.main import app


def main() -> None:
    suffix = secrets.token_hex(5).upper()
    org_id = None
    verification_ids = []
    with connection() as conn:
        try:
            validate_signing_configuration(conn)
            category = fetch_one(conn, "SELECT id FROM organisation_categories WHERE code='FINANCIAL'")["id"]
            citizen = fetch_one(conn, "SELECT citizen_id FROM citizens WHERE record_status='ACTIVE' ORDER BY citizen_id LIMIT 1")
            execute(conn, """INSERT INTO organisations
                (public_reference,business_name,email,phone,category_id,status,password_hash,intended_use)
                VALUES (%s,%s,%s,%s,%s,'APPROVED',%s,'Phase 6 acceptance testing')""",
                (f"ORG-T{suffix}", f"Phase 6 Organization {suffix}", f"phase6-{suffix}@trustid.test",
                 "+2348031999999", category, hash_password("Phase6Acceptance!")))
            org_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]

            def create_result(reference: str, issued, expires):
                execute(conn, """INSERT INTO verifications
                    (public_reference,organisation_id,citizen_id,subject_authority,source_record_id,subject_reference,claim_code,
                     condition_expression,purpose,policy_decision,policy_reason,result,issued_at,expires_at)
                    VALUES (%s,%s,%s,'NATIONAL_ID',%s,%s,'AGE_COMPARE','>= 18','Acceptance signing check',
                    'ALLOW_INSTANT','ALLOWED','CONDITION_SATISFIED',%s,%s)""",
                    (reference, org_id, citizen["citizen_id"], citizen["citizen_id"], f"SUB-{suffix}", issued, expires))
                verification_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
                verification_ids.append(verification_id)
                return sign_completed_result(conn, verification_id)

            now = utcnow_naive()
            current = create_result(f"VR-C{suffix}", now, now + timedelta(hours=24))
            expired = create_result(f"VR-E{suffix}", now - timedelta(days=2), now - timedelta(days=1))
            conn.commit()

            state, payload, _ = verify_receipt(conn, current["verification_token"])
            assert state == "CURRENT" and payload["issuer"] == "TrustID"
            assert len(current["verification_token"]) == 43
            url = verification_url(current["verification_token"])
            assert url.endswith(current["verification_token"])
            qr = qr_data_url(url)
            assert qr.startswith("data:image/png;base64,")
            qr_image = Image.open(BytesIO(base64.b64decode(qr.split(",", 1)[1])))
            decoded = zxingcpp.read_barcode(qr_image)
            assert decoded and decoded.text == url
            with TestClient(app) as client:  # Exercises lifespan signing-key validation.
                public = client.get(f"/verify-result/{current['verification_token']}")
                assert public.status_code == 200 and "Authentic and current" in public.text
                assert public.headers["x-robots-tag"].startswith("noindex")
                unavailable = client.get("/verify-result/invalid")
                assert unavailable.status_code == 200 and "Result unavailable" in unavailable.text

            state, _, _ = verify_receipt(conn, expired["verification_token"])
            assert state == "EXPIRED"

            original = current["canonical_payload"]
            altered = json.loads(original)
            altered["condition"] = ">= 21"
            altered_text = json.dumps(altered, sort_keys=True, separators=(",", ":"))
            execute(conn, "UPDATE receipts SET canonical_payload=%s WHERE verification_id=%s", (altered_text, verification_ids[0]))
            conn.commit()
            assert verify_receipt(conn, current["verification_token"])[0] == "INVALID"
            execute(conn, "UPDATE receipts SET canonical_payload=%s WHERE verification_id=%s", (original, verification_ids[0]))
            conn.commit()
            assert verify_receipt(conn, current["verification_token"])[0] == "CURRENT"

            serialized = " ".join(row["canonical_payload"] for row in fetch_all(
                conn, "SELECT canonical_payload FROM receipts WHERE organisation_id=%s", (org_id,)))
            for forbidden in ("synthetic_nin", "licence_number", "phone_number", "date_of_birth", "full_name", "residential_address"):
                assert forbidden not in serialized
            execute(conn, "DELETE FROM authenticity_rate_limits WHERE bucket_start=DATE_FORMAT(UTC_TIMESTAMP(),'%Y-%m-%d %H:%i:00')")
            assert allow_public_authenticity_check(conn, limit=2)
            assert allow_public_authenticity_check(conn, limit=2)
            assert not allow_public_authenticity_check(conn, limit=2)
            execute(conn, "DELETE FROM authenticity_rate_limits WHERE bucket_start=DATE_FORMAT(UTC_TIMESTAMP(),'%Y-%m-%d %H:%i:00')")
            execute(conn, "DELETE FROM audit_log WHERE event_type='RATE_LIMIT_TRIGGERED' AND target_reference='PUBLIC_VERIFICATION'")
            conn.commit()
            print("Phase 6 acceptance passed: signed receipt, QR link, expiry, tamper detection, privacy and cleanup.")
        finally:
            if org_id:
                execute(conn, "DELETE FROM audit_log WHERE actor_id=%s OR target_reference LIKE %s", (org_id, f"VR-%{suffix}"))
                execute(conn, "DELETE FROM receipts WHERE organisation_id=%s", (org_id,))
                execute(conn, "DELETE FROM verifications WHERE organisation_id=%s", (org_id,))
                execute(conn, "DELETE FROM organisations WHERE id=%s", (org_id,))
                conn.commit()


if __name__ == "__main__":
    main()
