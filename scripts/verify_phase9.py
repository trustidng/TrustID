"""Database-backed Phase 9 probing protection, isolation and admin acceptance."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.auth import SESSION_COOKIE, create_session, utcnow_naive
from app.db import connection, execute, fetch_all, fetch_one
from app.main import app
from app.security import digest_token, hash_password
from app.verifier import create_submission, prepare_request, submit_request


def age_request(org_id, nin, age, token=None):
    prepared = prepare_request("AGE_COMPARE", nin, "MINIMUM", str(age), "", (), "Confirm customer eligibility")
    with connection() as conn:
        submission = token or create_submission(conn, org_id, prepared.claim)
        return submission, submit_request(conn, org_id, submission, prepared)


def main():
    suffix = secrets.token_hex(4).upper()
    org_ids, citizen_ids, verification_ids, submission_tokens = [], [], [], []
    admin_id = admin_session_id = None
    try:
        with connection() as conn:
            category = fetch_one(conn, """SELECT p.category_id id FROM category_claim_permissions p
                JOIN organisation_categories c ON c.id=p.category_id
                WHERE p.claim_code IN ('AGE_COMPARE','IDENTITY_STATUS') AND c.active=TRUE
                GROUP BY p.category_id HAVING COUNT(DISTINCT p.claim_code)=2 LIMIT 1""")["id"]
            for index in range(3):
                execute(conn, """INSERT INTO organisations
                    (public_reference,business_name,email,phone,category_id,status,password_hash,intended_use)
                    VALUES (%s,%s,%s,%s,%s,'APPROVED',%s,'Phase 9 acceptance testing')""",
                    (f"ORG-9{index}{suffix}", f"Phase 9 Organization {index+1}",
                     f"phase9-{index}-{suffix}@trustid.test", f"+2348089{index}{suffix[:5]}",
                     category, hash_password("Phase9Acceptance!")))
                org_ids.append(fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"])
            for index in range(3):
                nin = "9" + str(secrets.randbelow(10**10)).zfill(10)
                execute(conn, """INSERT INTO citizens
                    (synthetic_nin,full_name,surname,first_name,middle_name,date_of_birth,gender,registered_phone,
                     identity_status,record_status,state_of_origin,state_of_residence,lga_of_residence,
                     residential_address,identity_photograph_reference)
                    VALUES (%s,%s,%s,%s,%s,'1990-04-12',%s,%s,'VERIFIED','ACTIVE','Kano','Kano',
                    'Kano Municipal','9 Test Road, Kano',%s)""",
                    (nin, f"Citizen Test {index+1}", f"Test {index+1}", "Citizen", None,
                     "MALE" if index % 2 == 0 else "FEMALE", f"+2348079{index}{suffix[:5]}",
                     "PHOTO-0001" if index % 2 == 0 else "PHOTO-0002"))
                citizen_ids.append(fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"])
            nins = [row["synthetic_nin"] for row in fetch_all(conn,
                "SELECT synthetic_nin FROM citizens WHERE citizen_id IN (%s,%s,%s) ORDER BY citizen_id", tuple(citizen_ids))]
            execute(conn, """INSERT INTO admin_users
                (username,role,active,password_hash,must_change_password)
                VALUES (%s,'ADMIN',TRUE,%s,FALSE)""",
                (f"phase9.{suffix.lower()}", hash_password("Phase9AdminAcceptance!")))
            admin_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            admin_token, _ = create_session(conn, "ADMIN", admin_id)
            admin_session_id = fetch_one(conn, "SELECT id FROM auth_sessions WHERE token_hash=%s", (digest_token(admin_token),))["id"]
            conn.commit()

        blocked_token = None
        for age in (18, 21, 25, 27):
            token, (verification_id, message) = age_request(org_ids[0], nins[0], age)
            submission_tokens.append(token)
            if verification_id:
                verification_ids.append(verification_id)
            else:
                blocked_token = token
                assert "too many similar requests" in message
        assert len(verification_ids) == 3

        _, duplicate = age_request(org_ids[0], nins[0], 27, blocked_token)
        assert duplicate[0] is None and "too many similar requests" in duplicate[1]
        with connection() as conn:
            reference = fetch_one(conn, "SELECT subject_reference FROM request_history WHERE organisation_id=%s LIMIT 1", (org_ids[0],))["subject_reference"]
            rows = fetch_all(conn, "SELECT * FROM request_history WHERE organisation_id=%s AND subject_reference=%s", (org_ids[0], reference))
            assert len(rows) == 4 and sum(row["decision"] == "BLOCKED" for row in rows) == 1
            assert all("result" not in row for row in rows)
            assert fetch_one(conn, "SELECT COUNT(*) count FROM verifications WHERE organisation_id=%s", (org_ids[0],))["count"] == 3
            assert fetch_one(conn, "SELECT COUNT(*) count FROM receipts r JOIN verifications v ON v.id=r.verification_id WHERE v.organisation_id=%s", (org_ids[0],))["count"] == 3

        for org_id, nin in ((org_ids[1], nins[0]), (org_ids[0], nins[1])):
            token, (verification_id, message) = age_request(org_id, nin, 18)
            submission_tokens.append(token); verification_ids.append(verification_id)
            assert verification_id and message is None

        with connection() as conn:
            execute(conn, "UPDATE request_history SET timestamp=%s WHERE organisation_id=%s AND subject_reference=%s",
                    (utcnow_naive()-timedelta(minutes=30, seconds=1), org_ids[0], reference))
            conn.commit()
        token, (verification_id, message) = age_request(org_ids[0], nins[0], 30)
        submission_tokens.append(token); verification_ids.append(verification_id)
        assert verification_id and message is None

        identity_prepared = prepare_request("IDENTITY_STATUS", nins[0], "IS_VERIFIED", "", "", (),
                                            "Confirm customer identity status")
        for _ in range(5):
            with connection() as conn:
                identity_token = create_submission(conn, org_ids[0], identity_prepared.claim)
                identity_id, identity_message = submit_request(conn, org_ids[0], identity_token, identity_prepared)
            submission_tokens.append(identity_token); verification_ids.append(identity_id)
            assert identity_id and identity_message is None

        prepared_tokens = []
        prepared = prepare_request("AGE_COMPARE", nins[2], "MINIMUM", "18", "", (), "Confirm customer eligibility")
        with connection() as conn:
            for _ in range(6):
                prepared_tokens.append(create_submission(conn, org_ids[2], prepared.claim))
        def concurrent_submit(token):
            with connection() as thread_conn:
                return submit_request(thread_conn, org_ids[2], token, prepared)
        with ThreadPoolExecutor(max_workers=6) as pool:
            concurrent_results = list(pool.map(concurrent_submit, prepared_tokens))
        submission_tokens.extend(prepared_tokens)
        concurrency_ids = [item[0] for item in concurrent_results if item[0]]
        verification_ids.extend(concurrency_ids)
        assert len(concurrency_ids) == 3 and sum(item[0] is None for item in concurrent_results) == 3, concurrent_results

        admin_client = TestClient(app, follow_redirects=False)
        anonymous = TestClient(app, follow_redirects=False)
        assert anonymous.get("/admin/security").status_code == 303
        assert anonymous.get("/admin/security/incidents/1").status_code == 303
        admin_client.cookies.set(SESSION_COOKIE, admin_token)
        page = admin_client.get("/admin/security?decision=BLOCKED")
        assert page.status_code == 200 and "Requests blocked" in page.text and "Phase 9 Organization" in page.text
        with connection() as conn:
            incident = fetch_one(conn, "SELECT id FROM request_history WHERE decision='BLOCKED' AND organisation_id=%s ORDER BY id DESC LIMIT 1", (org_ids[2],))
        detail = admin_client.get(f"/admin/security/incidents/{incident['id']}")
        assert detail.status_code == 200 and "Privacy-safe record" not in detail.text
        private_values = (nins[0], "Phase Nine Citizen", "1990-04-12", "CONDITION_SATISFIED")
        assert all(value not in page.text + detail.text for value in private_values)
        print("Phase 9 acceptance passed: rolling limit, duplicate safety, concurrency, boundary expiry, isolation, privacy, receipts and Admin Security oversight.")
    finally:
        if org_ids:
            with connection() as conn:
                marks = ",".join(["%s"] * len(org_ids))
                execute(conn, f"DELETE FROM audit_log WHERE actor_type='ORGANISATION' AND actor_id IN ({marks})", tuple(org_ids))
                if admin_id:
                    execute(conn, "DELETE FROM audit_log WHERE event_type='ADMIN_SECURITY_VIEWED' AND actor_id=%s", (admin_id,))
                execute(conn, f"DELETE FROM request_history WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM inference_guards WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM verification_submissions WHERE organisation_id IN ({marks})", tuple(org_ids))
                cleanup_ids = [row["id"] for row in fetch_all(
                    conn, f"SELECT id FROM verifications WHERE organisation_id IN ({marks})", tuple(org_ids))]
                if cleanup_ids:
                    vm = ",".join(["%s"] * len(cleanup_ids))
                    execute(conn, f"DELETE FROM receipts WHERE verification_id IN ({vm})", tuple(cleanup_ids))
                    execute(conn, f"DELETE FROM verifications WHERE id IN ({vm})", tuple(cleanup_ids))
                if admin_session_id:
                    execute(conn, "DELETE FROM auth_sessions WHERE id=%s", (admin_session_id,))
                if admin_id:
                    execute(conn, "DELETE FROM admin_users WHERE id=%s", (admin_id,))
                if citizen_ids:
                    cm = ",".join(["%s"] * len(citizen_ids))
                    execute(conn, f"DELETE FROM citizens WHERE citizen_id IN ({cm})", tuple(citizen_ids))
                execute(conn, f"DELETE FROM organisations WHERE id IN ({marks})", tuple(org_ids))
                conn.commit()


if __name__ == "__main__":
    main()
