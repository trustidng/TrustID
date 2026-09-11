"""Database-backed Phase 8 approval, disclosure, isolation, receipt and SMS acceptance."""
from datetime import timedelta
from pathlib import Path
import secrets
import sys
import re

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.auth import SESSION_COOKIE, create_session, utcnow_naive
from app.consent import decrypt_value
from app.db import connection, execute, fetch_all, fetch_one
from app.security import derive_delivery_otp, hash_password
from app.main import app


def hidden(html: str, name: str) -> str:
    match = re.search(rf'name="{name}" value="([^"]+)"', html)
    if not match:
        raise AssertionError(f"Missing {name}")
    return match.group(1)


def main():
    suffix = secrets.token_hex(4).upper()
    org_ids, citizen_id, verification_ids = [], None, []
    references = [f"VR-8WA{suffix}", f"VR-8WR{suffix}", f"VR-8UA{suffix}", f"VR-8UR{suffix}"]
    try:
        with connection() as conn:
            category = fetch_one(conn, "SELECT id FROM organisation_categories WHERE code='FINANCIAL'")["id"]
            for index in range(2):
                execute(conn, """INSERT INTO organisations
                    (public_reference,business_name,email,phone,category_id,status,password_hash,intended_use)
                    VALUES (%s,%s,%s,%s,%s,'APPROVED',%s,'Phase 8 acceptance testing')""",
                    (f"ORG-8{index}{suffix}", f"Phase 8 Organization {index+1}",
                     f"phase8-{index}-{suffix}@trustid.test", f"+23480988{index}{suffix[:4]}",
                     category, hash_password("Phase8Acceptance!")))
                org_ids.append(fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"])
            execute(conn, """INSERT INTO citizens
                (synthetic_nin,full_name,surname,first_name,middle_name,date_of_birth,gender,registered_phone,
                 identity_status,record_status,state_of_origin,state_of_residence,lga_of_residence,
                 residential_address,identity_photograph_reference,pin_hash,account_activated)
                VALUES (%s,'Amina Musa Bello','Bello','Amina','Musa','1992-04-12','FEMALE',%s,
                'VERIFIED','ACTIVE','Kano','Kano','Kano Municipal',
                '18 College Road, Kano','PHOTO-0002',%s,TRUE)""",
                ("8" + str(secrets.randbelow(10**10)).zfill(10), "+234807" + str(secrets.randbelow(10**7)).zfill(7), hash_password("2746")))
            citizen_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            for reference, claim in zip(references, (
                "RESIDENTIAL_ADDRESS", "FULL_LEGAL_NAME", "STATE_OF_ORIGIN", "RESIDENTIAL_ADDRESS"
            )):
                execute(conn, """INSERT INTO verifications
                    (public_reference,organisation_id,citizen_id,subject_authority,source_record_id,subject_reference,
                     claim_code,condition_expression,purpose,policy_decision,policy_reason,result,expires_at)
                    VALUES (%s,%s,%s,'NATIONAL_ID',%s,%s,%s,'CONSENT_REQUIRED','Complete customer registration',
                    'REQUIRE_CONSENT','CITIZEN_APPROVAL_REQUIRED','PENDING',%s)""",
                    (reference, org_ids[0], citizen_id, citizen_id, f"SUB-8{suffix}", claim, utcnow_naive()+timedelta(hours=24)))
                verification_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
                verification_ids.append(verification_id)
                execute(conn, """INSERT INTO consent_requests
                    (verification_id,citizen_id,organisation_id,claim_code,purpose,expires_at)
                    VALUES (%s,%s,%s,%s,'Complete customer registration',%s)""",
                    (verification_id,citizen_id,org_ids[0],claim,utcnow_naive()+timedelta(hours=24)))
            marks = ",".join(["%s"] * len(verification_ids))
            consent_ids = [row["id"] for row in fetch_all(
                conn, f"SELECT id FROM consent_requests WHERE verification_id IN ({marks}) ORDER BY id",
                tuple(verification_ids))]
            citizen_token, _ = create_session(conn, "CITIZEN", citizen_id)
            organisation_token, _ = create_session(conn, "ORGANISATION", org_ids[0])
            other_token, _ = create_session(conn, "ORGANISATION", org_ids[1])
            conn.commit()

            citizen_client = TestClient(app, follow_redirects=False)
            citizen_client.cookies.set(SESSION_COOKIE, citizen_token)
            dashboard = citizen_client.get("/citizen")
            detail = citizen_client.get(f"/citizen/requests/{consent_ids[0]}")
            csrf = hidden(dashboard.text, "csrf_token")
            assert dashboard.status_code == 200 and "4 requests awaiting your decision" in dashboard.text
            assert "Phase 8 Organization 1" in dashboard.text and "Needs your attention" in dashboard.text
            assert detail.status_code == 200 and "Who" not in detail.text and "Information requested" in detail.text

            code_page = citizen_client.post(f"/citizen/requests/{consent_ids[0]}/approve",
                data={"csrf_token": csrf, "pin": "2746"})
            challenge = int(hidden(code_page.text, "challenge_id"))
            conn.commit()
            delivery = fetch_one(conn, "SELECT code_nonce FROM sms_deliveries WHERE challenge_id=%s", (challenge,))
            approved_page = citizen_client.post(f"/citizen/requests/{consent_ids[0]}/confirm",
                data={"csrf_token": csrf, "challenge_id": challenge, "code": derive_delivery_otp(delivery["code_nonce"])})
            declined_page = citizen_client.post(f"/citizen/requests/{consent_ids[1]}/decline",
                data={"csrf_token": csrf, "pin": "2746"})
            assert "approval has been recorded" in approved_page.text and "request has been declined" in declined_page.text
            conn.commit()

            phone_client = TestClient(app, follow_redirects=False)
            assert phone_client.post("/phone/connect", data={"phone_number": fetch_one(conn, "SELECT registered_phone FROM citizens WHERE citizen_id=%s", (citizen_id,))["registered_phone"]}).status_code == 303
            dial = phone_client.post("/phone/dial", data={"service_code": "*7305#"})
            ussd_token = hidden(dial.text, "ussd_token")
            menu = phone_client.post("/phone/ussd/respond", data={"ussd_token": ussd_token, "response": "2746"})
            assert "1. Review requests" in menu.text
            listing = phone_client.post("/phone/ussd/respond", data={"ussd_token": ussd_token, "response": "1"})
            assert "Phase 8 Organization 1" in listing.text
            request_screen = phone_client.post("/phone/ussd/respond", data={"ussd_token": ussd_token, "response": "1"})
            assert "requests your state of origin" in request_screen.text.lower()
            confirm = phone_client.post("/phone/ussd/respond", data={"ussd_token": ussd_token, "response": "1"})
            assert "Approve this request" in confirm.text
            completed = phone_client.post("/phone/ussd/respond", data={"ussd_token": ussd_token, "response": "1"})
            assert "approval has been recorded" in completed.text
            assert "CLOSE" in completed.text and "REVIEW NEXT" not in completed.text
            conn.commit()

            dial = phone_client.post("/phone/dial", data={"service_code": "*7305#"})
            ussd_token = hidden(dial.text, "ussd_token")
            menu = phone_client.post("/phone/ussd/respond", data={"ussd_token": ussd_token, "response": "2746"})
            assert "1. Review requests" in menu.text
            listing = phone_client.post("/phone/ussd/respond", data={"ussd_token": ussd_token, "response": "1"})
            assert "Phase 8 Organization 1" in listing.text
            request_screen = phone_client.post("/phone/ussd/respond", data={"ussd_token": ussd_token, "response": "1"})
            assert "requests your residential address" in request_screen.text.lower()
            confirm = phone_client.post("/phone/ussd/respond", data={"ussd_token": ussd_token, "response": "2"})
            assert "Decline this request" in confirm.text
            completed = phone_client.post("/phone/ussd/respond", data={"ussd_token": ussd_token, "response": "1"})
            assert "request has been declined" in completed.text
            assert "CLOSE" in completed.text and "REVIEW NEXT" not in completed.text
            conn.commit()

            approved = fetch_one(conn, "SELECT * FROM consent_requests WHERE id=%s", (consent_ids[0],))
            rejected = fetch_one(conn, "SELECT * FROM consent_requests WHERE id=%s", (consent_ids[1],))
            ussd_approved = fetch_one(conn, "SELECT * FROM consent_requests WHERE id=%s", (consent_ids[2],))
            ussd_rejected = fetch_one(conn, "SELECT * FROM consent_requests WHERE id=%s", (consent_ids[3],))
            disclosure = fetch_one(conn, "SELECT * FROM controlled_disclosures WHERE verification_id=%s", (verification_ids[0],))
            ussd_disclosure = fetch_one(conn, "SELECT * FROM controlled_disclosures WHERE verification_id=%s", (verification_ids[2],))
            assert approved["status"] == "APPROVED" and rejected["status"] == "REJECTED"
            assert ussd_approved["status"] == "APPROVED" and ussd_approved["resolved_channel"] == "USSD"
            assert ussd_rejected["status"] == "REJECTED" and ussd_rejected["resolved_channel"] == "USSD"
            assert decrypt_value(disclosure) == "18 College Road, Kano"
            assert decrypt_value(ussd_disclosure) == "Kano"
            assert b"College Road" not in bytes(disclosure["ciphertext"])
            assert disclosure["expires_at"] - disclosure["issued_at"] == timedelta(days=30)
            assert fetch_one(conn, "SELECT COUNT(*) count FROM receipts WHERE verification_id=%s", (verification_ids[0],))["count"] == 1
            assert fetch_one(conn, "SELECT COUNT(*) count FROM receipts WHERE verification_id=%s", (verification_ids[1],))["count"] == 0
            assert fetch_one(conn, "SELECT COUNT(*) count FROM receipts WHERE verification_id=%s", (verification_ids[2],))["count"] == 1
            assert fetch_one(conn, "SELECT COUNT(*) count FROM receipts WHERE verification_id=%s", (verification_ids[3],))["count"] == 0
            assert fetch_one(conn, "SELECT COUNT(*) count FROM controlled_disclosures WHERE verification_id=%s AND organisation_id=%s", (verification_ids[0],org_ids[1]))["count"] == 0
            reference_marks = ",".join(["%s"] * len(references))
            text = str(fetch_all(conn, f"SELECT detail FROM audit_log WHERE target_reference IN ({reference_marks})", tuple(references)))
            assert "18 College Road" not in text and "Amina Phase Eight" not in text
            assert fetch_one(conn, "SELECT COUNT(*) count FROM sms_deliveries d JOIN otp_challenges o ON o.id=d.challenge_id WHERE o.consent_request_id=%s AND d.message_type='CONSENT_APPROVAL_CODE'", (consent_ids[0],))["count"] == 1
            organisation_client = TestClient(app, follow_redirects=False)
            organisation_client.cookies.set(SESSION_COOKIE, organisation_token)
            other_client = TestClient(app, follow_redirects=False)
            other_client.cookies.set(SESSION_COOKIE, other_token)
            private_result = organisation_client.get(f"/organisation/verifications/{references[0]}")
            isolated = other_client.get(f"/organisation/verifications/{references[0]}")
            assert private_result.status_code == 200 and "18 College Road, Kano" in private_result.text
            assert "Information provided" in private_result.text
            assert isolated.status_code == 303 and "18 College Road" not in isolated.text
            citizen_history = citizen_client.get("/citizen")
            assert "Approved" in citizen_history.text and "Declined" in citizen_history.text
            print("Phase 8 acceptance passed: web and USSD approval and decline, approval code, encrypted disclosure, 30-day validity, receipts, isolation, privacy, SMS cost controls and close-only USSD completion.")
    finally:
        if citizen_id:
            with connection() as conn:
                reference_marks = ",".join(["%s"] * len(references))
                execute(conn, f"DELETE FROM audit_log WHERE target_reference IN ({reference_marks})", tuple(references))
                execute(conn, "DELETE FROM sms_deliveries WHERE citizen_id=%s", (citizen_id,))
                execute(conn, "DELETE FROM otp_challenges WHERE citizen_id=%s", (citizen_id,))
                execute(conn, "DELETE FROM auth_sessions WHERE (actor_type='CITIZEN' AND actor_id=%s) OR (actor_type='ORGANISATION' AND actor_id IN (%s,%s))", (citizen_id,org_ids[0],org_ids[1]))
                execute(conn, "DELETE FROM ussd_sessions WHERE citizen_id=%s", (citizen_id,))
                execute(conn, "DELETE FROM phone_sessions WHERE citizen_id=%s", (citizen_id,))
                execute(conn, "DELETE FROM controlled_disclosures WHERE citizen_id=%s", (citizen_id,))
                for verification_id in verification_ids:
                    execute(conn, "DELETE FROM receipts WHERE verification_id=%s", (verification_id,))
                    execute(conn, "DELETE FROM consent_requests WHERE verification_id=%s", (verification_id,))
                    execute(conn, "DELETE FROM verifications WHERE id=%s", (verification_id,))
                execute(conn, "DELETE FROM citizens WHERE citizen_id=%s", (citizen_id,))
                for org_id in org_ids:
                    execute(conn, "DELETE FROM audit_log WHERE actor_id=%s AND actor_type='ORGANISATION'", (org_id,))
                    execute(conn, "DELETE FROM organisations WHERE id=%s", (org_id,))
                conn.commit()


if __name__ == "__main__":
    main()
