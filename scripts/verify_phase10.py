"""Database-backed Phase 10 safe failure, recovery, SMS and USSD acceptance."""
from datetime import timedelta
from pathlib import Path
import re
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.auth import PHONE_COOKIE, SESSION_COOKIE, create_phone_session, create_session, utcnow_naive
from app.consent import ConsentError, approve, start_web_approval
from app.db import connection, execute, fetch_all, fetch_one
from app.main import app
from app.resilience import change_status
from app.security import derive_delivery_otp, digest_token, hash_password
from app.verification.errors import TrustedSourceUnavailable
from app.verifier import create_submission, prepare_request, submit_request


def hidden(html, name):
    match = re.search(rf'name="{name}" value="([^"]+)"', html)
    if not match:
        raise AssertionError(f"Missing {name}")
    return match.group(1)


def main():
    suffix = secrets.token_hex(4).upper()
    org_id = citizen_id = licence_id = admin_id = admin_session_id = phone_session_id = None
    verification_ids = []
    original_services = {}
    try:
        with connection() as conn:
            original_services = {row["service_code"]: row["status"] for row in fetch_all(conn, "SELECT service_code,status FROM service_status")}
            category = fetch_one(conn, """SELECT p.category_id id FROM category_claim_permissions p
                JOIN organisation_categories c ON c.id=p.category_id WHERE c.active=TRUE
                AND p.claim_code IN ('AGE_COMPARE','LICENCE_STATUS','FULL_LEGAL_NAME')
                GROUP BY p.category_id HAVING COUNT(DISTINCT p.claim_code)=3 LIMIT 1""")
            if not category:
                execute(conn, "INSERT INTO organisation_categories (code,name,description) VALUES (%s,%s,'Phase 10 acceptance')",
                        (f"PHASE10_{suffix}", f"Phase 10 Category {suffix}"))
                category_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
                for claim in ("AGE_COMPARE", "LICENCE_STATUS", "FULL_LEGAL_NAME"):
                    execute(conn, "INSERT INTO category_claim_permissions (category_id,claim_code) VALUES (%s,%s)", (category_id, claim))
            else:
                category_id = category["id"]
            execute(conn, """INSERT INTO organisations
                (public_reference,business_name,email,phone,category_id,status,password_hash,intended_use)
                VALUES (%s,%s,%s,%s,%s,'APPROVED',%s,'Phase 10 resilience testing')""",
                (f"ORG-10{suffix}", f"Phase 10 Organization {suffix}", f"phase10-{suffix}@trustid.test",
                 f"+234806{suffix[:7]}", category_id, hash_password("Phase10Acceptance!")))
            org_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            nin = "7" + str(secrets.randbelow(10**10)).zfill(10)
            phone = "+234805" + str(secrets.randbelow(10**7)).zfill(7)
            execute(conn, """INSERT INTO citizens
                (synthetic_nin,full_name,surname,first_name,middle_name,date_of_birth,gender,registered_phone,
                 identity_status,record_status,state_of_origin,state_of_residence,lga_of_residence,
                 residential_address,identity_photograph_reference,pin_hash,account_activated)
                VALUES (%s,'Amina Musa Bello','Bello','Amina','Musa','1991-05-14','FEMALE',%s,
                'VERIFIED','ACTIVE','Kano','Kano','Kano Municipal',
                '10 Recovery Road, Kano','PHOTO-0002',%s,TRUE)""", (nin, phone, hash_password("2846")))
            citizen_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            licence = "LIC-" + str(secrets.randbelow(10**9)).zfill(9)
            execute(conn, """INSERT INTO licences
                (licence_number,holder_full_name,holder_surname,holder_first_name,holder_middle_name,
                 holder_date_of_birth,holder_gender,holder_photograph_reference,
                 licence_class,issue_date,expiry_date,licence_status,record_status)
                VALUES (%s,'Bashir Musa Adamu','Adamu','Bashir','Musa','1990-01-20','MALE',
                'PHOTO-0003','B','2024-01-01','2030-01-01','VALID','ACTIVE')""", (licence,))
            licence_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            execute(conn, """INSERT INTO admin_users (username,role,active,password_hash,must_change_password)
                VALUES (%s,'ADMIN',TRUE,%s,FALSE)""", (f"phase10.{suffix.lower()}", hash_password("Phase10Admin!")))
            admin_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            admin_token, csrf = create_session(conn, "ADMIN", admin_id)
            admin_session_id = fetch_one(conn, "SELECT id FROM auth_sessions WHERE token_hash=%s", (digest_token(admin_token),))["id"]
            conn.commit()

        age = prepare_request("AGE_COMPARE", nin, "MINIMUM", "18", "", (), "Confirm customer eligibility")
        with connection() as conn:
            token = create_submission(conn, org_id, age.claim)
            change_status(conn, "NATIONAL_ID", "UNAVAILABLE", admin_id, "Resilience acceptance")
            conn.commit()
        try:
            with connection() as conn:
                submit_request(conn, org_id, token, age)
            raise AssertionError("Identity verification did not fail closed")
        except TrustedSourceUnavailable as exc:
            assert "identity verification service" in exc.safe_message
        with connection() as conn:
            assert fetch_one(conn, "SELECT COUNT(*) count FROM verifications WHERE organisation_id=%s", (org_id,))["count"] == 0
            change_status(conn, "NATIONAL_ID", "AVAILABLE", admin_id); conn.commit()
        with connection() as conn:
            verification_id, message = submit_request(conn, org_id, token, age)
            verification_ids.append(verification_id); assert verification_id and message is None

        licence_request = prepare_request("LICENCE_STATUS", licence, "IS_VALID", "", "", (), "Confirm driver eligibility")
        with connection() as conn:
            licence_token = create_submission(conn, org_id, licence_request.claim)
            change_status(conn, "DRIVING_LICENCE", "UNAVAILABLE", admin_id); conn.commit()
        try:
            with connection() as conn:
                submit_request(conn, org_id, licence_token, licence_request)
            raise AssertionError("Licence verification did not fail closed")
        except TrustedSourceUnavailable as exc:
            assert "driving licence verification service" in exc.safe_message
        with connection() as conn:
            change_status(conn, "DRIVING_LICENCE", "AVAILABLE", admin_id); conn.commit()
        with connection() as conn:
            verification_id, _ = submit_request(conn, org_id, licence_token, licence_request)
            verification_ids.append(verification_id)

        consent = prepare_request("FULL_LEGAL_NAME", nin, "DISCLOSE_WITH_CONSENT", "", "", (), "Complete customer registration")
        with connection() as conn:
            consent_token = create_submission(conn, org_id, consent.claim)
            change_status(conn, "SMS", "UNAVAILABLE", admin_id); conn.commit()
        with connection() as conn:
            consent_verification, _ = submit_request(conn, org_id, consent_token, consent)
            verification_ids.append(consent_verification)
            consent_id = fetch_one(conn, "SELECT id FROM consent_requests WHERE verification_id=%s", (consent_verification,))["id"]
            failed = fetch_one(conn, "SELECT delivery_status FROM sms_deliveries WHERE consent_request_id=%s", (consent_id,))
            assert failed["delivery_status"] == "FAILED"
            try:
                start_web_approval(conn, citizen_id, consent_id, "2846")
                raise AssertionError("Approval code was created while SMS was unavailable")
            except ConsentError as exc:
                assert "could not be sent" in str(exc)
            conn.commit()
        with connection() as conn:
            change_status(conn, "SMS", "AVAILABLE", admin_id); conn.commit()
        with connection() as conn:
            challenge = start_web_approval(conn, citizen_id, consent_id, "2846"); conn.commit()
            delivery = fetch_one(conn, "SELECT code_nonce FROM sms_deliveries WHERE challenge_id=%s", (challenge,))
            change_status(conn, "NATIONAL_ID", "UNAVAILABLE", admin_id); conn.commit()
        with connection() as conn:
            try:
                approve(conn, citizen_id, consent_id, channel="WEB", challenge_id=challenge,
                        code=derive_delivery_otp(delivery["code_nonce"]))
                raise AssertionError("Disclosure occurred while identity source was unavailable")
            except ConsentError as exc:
                assert "identity verification service" in str(exc)
            conn.commit()
        with connection() as conn:
            assert fetch_one(conn, "SELECT status FROM consent_requests WHERE id=%s", (consent_id,))["status"] == "PENDING"
            assert fetch_one(conn, "SELECT COUNT(*) count FROM controlled_disclosures WHERE verification_id=%s", (consent_verification,))["count"] == 0
            change_status(conn, "NATIONAL_ID", "AVAILABLE", admin_id); conn.commit()
        with connection() as conn:
            approve(conn, citizen_id, consent_id, channel="WEB", challenge_id=challenge,
                    code=derive_delivery_otp(delivery["code_nonce"])); conn.commit()

        admin_client = TestClient(app, follow_redirects=False)
        admin_client.cookies.set(SESSION_COOKIE, admin_token)
        security = admin_client.get("/admin/security")
        assert security.status_code == 200 and "Service status" in security.text and "National identity service" in security.text
        response = admin_client.post("/admin/security/services/SMS", data={"csrf_token": csrf, "status": "UNAVAILABLE", "reason_code": "MAINTENANCE"})
        assert response.status_code == 303
        activation_client = TestClient(app, follow_redirects=False)
        with connection() as conn:
            challenge_count = fetch_one(conn, "SELECT COUNT(*) count FROM otp_challenges WHERE citizen_id=%s", (citizen_id,))["count"]
        activation = activation_client.post("/citizen/activate/request", data={"phone": phone})
        assert activation.status_code == 200 and "activation code could not be sent" in activation.text
        with connection() as conn:
            assert fetch_one(conn, "SELECT COUNT(*) count FROM otp_challenges WHERE citizen_id=%s", (citizen_id,))["count"] == challenge_count
        assert admin_client.post("/admin/security/services/SMS", data={"csrf_token": "invalid", "status": "AVAILABLE"}).status_code == 403
        response = admin_client.post("/admin/security/services/SMS", data={"csrf_token": csrf, "status": "AVAILABLE"})
        assert response.status_code == 303

        with connection() as conn:
            phone_token = create_phone_session(conn, phone, citizen_id)
            phone_session_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            conn.commit()
        phone_client = TestClient(app, follow_redirects=False)
        phone_client.cookies.set(PHONE_COOKIE, phone_token)
        inbox = phone_client.get("/phone/messages")
        assert "FAILED" not in inbox.text and "Resilience Test" not in inbox.text
        assert admin_client.post("/admin/security/services/USSD", data={"csrf_token": csrf, "status": "UNAVAILABLE", "reason_code": "MAINTENANCE"}).status_code == 303
        with connection() as conn:
            sessions_before = fetch_one(conn, "SELECT COUNT(*) count FROM ussd_sessions WHERE phone_session_id=%s", (phone_session_id,))["count"]
        unavailable_ussd = phone_client.post("/phone/dial", data={"service_code": "*7305#"})
        assert "USSD is currently unavailable due to maintenance" in unavailable_ussd.text and "CLOSE" in unavailable_ussd.text
        with connection() as conn:
            assert fetch_one(conn, "SELECT COUNT(*) count FROM ussd_sessions WHERE phone_session_id=%s", (phone_session_id,))["count"] == sessions_before
        assert admin_client.post("/admin/security/services/USSD", data={"csrf_token": csrf, "status": "AVAILABLE"}).status_code == 303
        history_page = admin_client.get("/admin/security/services/history")
        assert f"phase10.{suffix.lower()}" in history_page.text and "Service status history" in history_page.text
        dial = phone_client.post("/phone/dial", data={"service_code": "*7305#"})
        ussd_token = hidden(dial.text, "ussd_token")
        with connection() as conn:
            execute(conn, "UPDATE ussd_sessions SET expires_at=%s WHERE token_hash=%s",
                    (utcnow_naive()-timedelta(seconds=1), digest_token(ussd_token))); conn.commit()
        expired = phone_client.post("/phone/ussd/respond", data={"ussd_token": ussd_token, "response": "2846"})
        assert "session has ended for your security" in expired.text and "CLOSE" in expired.text
        with connection() as conn:
            assert fetch_one(conn, "SELECT COUNT(*) count FROM audit_log WHERE event_type='SERVICE_UNAVAILABLE'")["count"] >= 4
        print("Phase 10 acceptance passed: source, SMS and USSD safe failure, clean recovery, attributed service history, no false receipts or messages, and session expiry.")
    finally:
        with connection() as conn:
            for code, status in original_services.items():
                execute(conn, "UPDATE service_status SET status=%s,status_message=NULL,changed_by_admin_id=NULL WHERE service_code=%s", (status, code))
            if org_id:
                execute(conn, "DELETE FROM audit_log WHERE actor_id=%s AND actor_type='ORGANISATION'", (org_id,))
                execute(conn, "DELETE FROM request_history WHERE organisation_id=%s", (org_id,))
                execute(conn, "DELETE FROM inference_guards WHERE organisation_id=%s", (org_id,))
                execute(conn, "DELETE FROM verification_submissions WHERE organisation_id=%s", (org_id,))
                rows = fetch_all(conn, "SELECT id FROM verifications WHERE organisation_id=%s", (org_id,))
                ids = [row["id"] for row in rows]
                if ids:
                    marks = ",".join(["%s"]*len(ids))
                    execute(conn, f"DELETE FROM receipts WHERE verification_id IN ({marks})", tuple(ids))
                    execute(conn, f"DELETE FROM controlled_disclosures WHERE verification_id IN ({marks})", tuple(ids))
                    execute(conn, f"DELETE FROM consent_requests WHERE verification_id IN ({marks})", tuple(ids))
                    execute(conn, f"DELETE FROM verifications WHERE id IN ({marks})", tuple(ids))
                execute(conn, "DELETE FROM organisations WHERE id=%s", (org_id,))
            if citizen_id:
                execute(conn, "DELETE FROM sms_deliveries WHERE citizen_id=%s", (citizen_id,))
                execute(conn, "DELETE FROM otp_challenges WHERE citizen_id=%s", (citizen_id,))
                execute(conn, "DELETE FROM ussd_sessions WHERE citizen_id=%s", (citizen_id,))
                execute(conn, "DELETE FROM phone_sessions WHERE citizen_id=%s", (citizen_id,))
                execute(conn, "DELETE FROM citizens WHERE citizen_id=%s", (citizen_id,))
            if licence_id:
                execute(conn, "DELETE FROM licences WHERE licence_record_id=%s", (licence_id,))
            if admin_id:
                execute(conn, "DELETE FROM audit_log WHERE actor_id=%s AND actor_type='ADMIN'", (admin_id,))
                execute(conn, "DELETE FROM auth_sessions WHERE actor_type='ADMIN' AND actor_id=%s", (admin_id,))
                execute(conn, "DELETE FROM admin_users WHERE id=%s", (admin_id,))
            execute(conn, "DELETE FROM organisation_categories WHERE code=%s", (f"PHASE10_{suffix}",))
            conn.commit()


if __name__ == "__main__":
    main()
