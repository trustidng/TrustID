"""Acceptance checks for independent authorities and protected identity photographs."""
from pathlib import Path
import secrets
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import SESSION_COOKIE, create_session
from app.db import connection, execute, fetch_all, fetch_one
from app.main import app
from app.photographs import allow_identity_photo
from app.security import hash_password
from app.verifier import create_submission, prepare_request, submit_request


def main() -> None:
    suffix = secrets.token_hex(5).upper()
    org_ids: list[int] = []
    references: list[str] = []
    with connection() as conn:
        try:
            citizen = fetch_one(conn, """SELECT citizen_id,synthetic_nin,full_name,date_of_birth,
                identity_photograph_reference FROM citizens WHERE record_status='ACTIVE' ORDER BY citizen_id LIMIT 1""")
            licence = fetch_one(conn, """SELECT licence_record_id,licence_number,holder_full_name,
                holder_date_of_birth,holder_photograph_reference FROM licences
                WHERE record_status='ACTIVE' AND licence_status='VALID'
                AND issue_date<=UTC_DATE() AND expiry_date>=UTC_DATE() LIMIT 1""")
            if not citizen or not licence:
                raise AssertionError("Independent authority acceptance records are unavailable")
            columns = {row["COLUMN_NAME"] for row in fetch_all(conn, """SELECT COLUMN_NAME
                FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='licences'""")}
            assert "citizen_reference" not in columns
            for required in ("holder_full_name", "holder_date_of_birth", "holder_photograph_reference"):
                assert required in columns

            categories = {
                row["code"]: row["id"] for row in fetch_all(conn, """SELECT id,code FROM organisation_categories
                    WHERE code IN ('RETAIL','TRANSPORT_LOGISTICS')""")
            }
            for number, category in enumerate(("RETAIL", "TRANSPORT_LOGISTICS"), 1):
                execute(conn, """INSERT INTO organisations
                    (public_reference,business_name,email,phone,category_id,status,password_hash,intended_use)
                    VALUES (%s,%s,%s,%s,%s,'APPROVED',%s,'Protected photograph acceptance testing')""",
                    (f"ORG-P{number}{suffix}", f"Photo Test Organization {number}",
                     f"photo-{number}-{suffix}@trustid.test", f"+23480318{number}9999", categories[category],
                     hash_password("PhotoAcceptance123!")))
                org_ids.append(fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"])
            conn.commit()

            def submit(org_id: int, claim: str, identifier: str, operator: str, low: str = ""):
                prepared = prepare_request(claim, identifier, operator, low, "", (),
                                           "Confirm applicant eligibility")
                token = create_submission(conn, org_id, prepared.claim)
                verification_id, denied = submit_request(conn, org_id, token, prepared)
                assert not denied
                row = fetch_one(conn, """SELECT public_reference,citizen_id,subject_authority,source_record_id
                    FROM verifications WHERE id=%s""", (verification_id,))
                references.append(row["public_reference"])
                return row

            national_result = submit(org_ids[0], "AGE_COMPARE", citizen["synthetic_nin"], "MINIMUM", "18")
            licence_result = submit(org_ids[1], "LICENCE_STATUS", licence["licence_number"], "IS_VALID")
            assert national_result["subject_authority"] == "NATIONAL_ID" and national_result["citizen_id"]
            assert licence_result["subject_authority"] == "DRIVING_LICENCE" and licence_result["citizen_id"] is None
            assert licence_result["source_record_id"] == licence["licence_record_id"]

            retail_token, _ = create_session(conn, "ORGANISATION", org_ids[0])
            transport_token, _ = create_session(conn, "ORGANISATION", org_ids[1])
            conn.commit()
            with TestClient(app) as client:
                client.cookies.set(SESSION_COOKIE, retail_token)
                result_page = client.get(f"/organisation/verifications/{national_result['public_reference']}")
                photograph = client.get(
                    f"/organisation/verifications/{national_result['public_reference']}/identity-photograph")
                assert result_page.status_code == 200 and "Compare the photograph" in result_page.text
                assert photograph.status_code == 200 and photograph.headers["content-type"] == "image/jpeg"
                assert photograph.content.startswith(b"\xff\xd8") and "no-store" in photograph.headers["cache-control"]
                client.cookies.set(SESSION_COOKIE, transport_token)
                isolated = client.get(
                    f"/organisation/verifications/{national_result['public_reference']}/identity-photograph")
                assert isolated.status_code == 404
                public_asset = client.get("/static/identity_photographs/synthetic_portraits_4x4.png")
                assert public_asset.status_code == 404

            assert fetch_one(conn, """SELECT COUNT(*) count FROM audit_log
                WHERE event_type='IDENTITY_PHOTO_VIEWED' AND target_reference=%s""",
                (national_result["public_reference"],))["count"] == 1
            execute(conn, "DELETE FROM identity_photo_rate_limits WHERE organisation_id=%s", (org_ids[0],))
            assert allow_identity_photo(conn, org_ids[0], limit=2)
            assert allow_identity_photo(conn, org_ids[0], limit=2)
            assert not allow_identity_photo(conn, org_ids[0], limit=2)
            conn.commit()
            print("Authority and photograph acceptance passed: standalone sources, protected images, isolation, audit and rate limits.")
        finally:
            if org_ids:
                marks = ",".join(["%s"] * len(org_ids))
                execute(conn, f"DELETE FROM identity_photo_rate_limits WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM auth_sessions WHERE actor_type='ORGANISATION' AND actor_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM audit_log WHERE (actor_type='ORGANISATION' AND actor_id IN ({marks})) OR target_reference IN ({','.join(['%s'] * len(references)) if references else "''"})", tuple(org_ids + references))
                execute(conn, f"DELETE FROM receipts WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM verification_submissions WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM request_history WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM verifications WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM organisations WHERE id IN ({marks})", tuple(org_ids))
                conn.commit()


if __name__ == "__main__":
    main()
