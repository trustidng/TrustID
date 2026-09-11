"""Database-backed Phase 7 history, receipts, isolation, privacy, and load acceptance."""
from datetime import timedelta
import json
from pathlib import Path
import secrets
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import SESSION_COOKIE, create_session, utcnow_naive
from app.db import connection, execute, fetch_one
from app.history import organisation_receipt, verification_history
from app.main import app
from app.security import hash_password
from app.signing import sign_completed_result


def main() -> None:
    suffix = secrets.token_hex(5).upper()
    org_ids: list[int] = []
    verification_ids: list[int] = []
    session_ids: list[int] = []
    with connection() as conn:
        try:
            category = fetch_one(conn, "SELECT id FROM organisation_categories WHERE code='FINANCIAL'")["id"]
            citizen = fetch_one(conn, "SELECT citizen_id FROM citizens WHERE record_status='ACTIVE' ORDER BY citizen_id LIMIT 1")["citizen_id"]
            for number in (1, 2):
                execute(conn, """INSERT INTO organisations
                    (public_reference,business_name,email,phone,category_id,status,password_hash,intended_use)
                    VALUES (%s,%s,%s,%s,%s,'APPROVED',%s,'Phase 7 acceptance testing')""",
                    (f"ORG-7{number}{suffix}", f"Phase 7 Organization {number}",
                     f"phase7-{number}-{suffix}@trustid.test", f"+23480317{number}9999", category,
                     hash_password("Phase7Acceptance!")))
                org_ids.append(fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"])

            now = utcnow_naive()
            subject = f"SUB-7{suffix}"

            def create_result(org_id: int, reference: str, expires, *, sign=True, result="CONDITION_SATISFIED"):
                issued = now if expires > now else now - timedelta(days=2)
                execute(conn, """INSERT INTO verifications
                    (public_reference,organisation_id,citizen_id,subject_authority,source_record_id,subject_reference,claim_code,
                     condition_expression,purpose,policy_decision,policy_reason,result,issued_at,expires_at)
                    VALUES (%s,%s,%s,'NATIONAL_ID',%s,%s,'AGE_COMPARE','>= 18','Confirm programme eligibility',
                    'ALLOW_INSTANT','ALLOWED',%s,%s,%s)""",
                    (reference, org_id, citizen, citizen, subject, result, issued, expires))
                verification_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
                verification_ids.append(verification_id)
                return sign_completed_result(conn, verification_id) if sign else None

            current = create_result(org_ids[0], f"VR-7C{suffix}", now + timedelta(hours=24))
            expired = create_result(org_ids[0], f"VR-7E{suffix}", now - timedelta(days=1))
            other = create_result(org_ids[1], f"VR-7O{suffix}", now + timedelta(days=30))
            create_result(org_ids[0], f"VR-7P{suffix}", now + timedelta(minutes=10), sign=False, result="PENDING")

            # Load test the all-request history with 500 privacy-safe records.
            for index in range(500):
                create_result(org_ids[0], f"VR-7L{index:03d}{suffix}", now + timedelta(hours=24), sign=False)
            token, _ = create_session(conn, "ORGANISATION", org_ids[0])
            session_ids.append(fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"])
            conn.commit()

            first_page = verification_history(conn, org_ids[0], page=1)
            last_page = verification_history(conn, org_ids[0], page=26)
            assert first_page["total"] == 503 and len(first_page["items"]) == 20
            assert last_page["items"] and len(last_page["items"]) <= 20
            assert verification_history(conn, org_ids[0], query=subject)["total"] == 503
            receipts = verification_history(conn, org_ids[0], tab="receipts")
            assert receipts["total"] == 2 and {item["receipt_state"] for item in receipts["items"]} == {"CURRENT", "EXPIRED"}
            assert verification_history(conn, org_ids[0], tab="receipts", status="current")["total"] == 1
            assert organisation_receipt(conn, org_ids[0], current["transaction_id"])["purpose"] == "Confirm programme eligibility"
            assert organisation_receipt(conn, org_ids[1], current["transaction_id"]) is None
            assert organisation_receipt(conn, org_ids[0], other["transaction_id"]) is None
            assert fetch_one(conn, "SELECT COUNT(*) count FROM receipts WHERE verification_id=%s", (verification_ids[3],))["count"] == 0

            original = current["canonical_payload"]
            changed = json.loads(original)
            changed["condition"] = ">= 25"
            execute(conn, "UPDATE receipts SET canonical_payload=%s WHERE verification_id=%s",
                    (json.dumps(changed, sort_keys=True, separators=(",", ":")), verification_ids[0]))
            conn.commit()
            invalid = organisation_receipt(conn, org_ids[0], current["transaction_id"])
            assert invalid == {"transaction_id": current["transaction_id"], "state": "INVALID", "safe": False}
            execute(conn, "UPDATE receipts SET canonical_payload=%s WHERE verification_id=%s", (original, verification_ids[0]))
            conn.commit()

            with TestClient(app) as client:
                client.cookies.set(SESSION_COOKIE, token)
                history_page = client.get("/organisation/history?q=" + subject)
                receipt_page = client.get(f"/organisation/receipts/{current['transaction_id']}")
                cross_org = client.get(f"/organisation/receipts/{other['transaction_id']}", follow_redirects=False)
                assert history_page.status_code == 200 and "Verification history" in history_page.text
                assert receipt_page.status_code == 200 and "Print or save receipt" in receipt_page.text
                assert "Confirm programme eligibility" in receipt_page.text
                assert "canonical_payload" not in receipt_page.text and "synthetic_nin" not in receipt_page.text
                assert cross_org.status_code == 303 and cross_org.headers["location"].startswith("/organisation/history")
            print("Phase 7 acceptance passed: 500-record history, filters, receipts, isolation, tamper safety, privacy and UI routes.")
        finally:
            if org_ids:
                marks = ",".join(["%s"] * len(org_ids))
                execute(conn, f"DELETE FROM auth_sessions WHERE actor_type='ORGANISATION' AND actor_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM audit_log WHERE actor_type='ORGANISATION' AND actor_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM receipts WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM verifications WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM organisations WHERE id IN ({marks})", tuple(org_ids))
                conn.commit()


if __name__ == "__main__":
    main()
