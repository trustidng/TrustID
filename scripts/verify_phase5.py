"""Database-backed Phase 5 portal, privacy, consent-SMS, and isolation acceptance test."""
from datetime import timedelta
from pathlib import Path
import re
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.auth import utcnow_naive
from app.db import connection, execute, fetch_all, fetch_one
from app.main import app
from app.security import digest_token, hash_password


def hidden(html: str, name: str) -> str:
    match = re.search(rf'name="{name}" value="([^"]*)"', html)
    if not match:
        raise AssertionError(f"Missing hidden field {name}")
    return match.group(1)


def main() -> None:
    suffix = secrets.token_hex(4).upper()
    org_ids = []
    verification_ids = []
    client = TestClient(app, follow_redirects=False)
    other = TestClient(app, follow_redirects=False)
    try:
        with connection() as conn:
            financial = fetch_one(conn, "SELECT id FROM organisation_categories WHERE code='FINANCIAL'")["id"]
            citizen = fetch_one(conn, """SELECT citizen_id,synthetic_nin,registered_phone FROM citizens
                WHERE record_status='ACTIVE' ORDER BY citizen_id LIMIT 1""")
            other_citizen = fetch_one(conn, """SELECT citizen_id,registered_phone FROM citizens
                WHERE record_status='ACTIVE' AND citizen_id<>%s ORDER BY citizen_id LIMIT 1""", (citizen["citizen_id"],))
            for index in range(2):
                execute(conn, """INSERT INTO organisations
                    (business_name,email,phone,category_id,status,password_hash,intended_use)
                    VALUES (%s,%s,%s,%s,'APPROVED',%s,'Phase 5 acceptance testing')""",
                    (f"Phase 5 Organization {index} {suffix}", f"phase5-{index}-{suffix}@trustid.test",
                     f"+234803100000{index}",
                     financial, hash_password("Phase5Portal88")))
                org_ids.append(fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"])
            conn.commit()

        login = client.post("/organisation/login", data={"identifier": f"phase5-0-{suffix}@trustid.test", "password": "Phase5Portal88"})
        if login.status_code != 303:
            raise AssertionError("Phase 5 organization login failed")
        dashboard = client.get("/organisation")
        csrf = hidden(dashboard.text, "csrf_token")
        choices = client.get("/organisation/verifications/new")
        if choices.status_code != 200 or "Verify age requirement" not in choices.text or "Request legal name" not in choices.text:
            raise AssertionError("Permitted Verify/Request choices were not rendered")

        age_form = {
            "csrf_token": csrf, "claim_code": "AGE_COMPARE", "identifier": citizen["synthetic_nin"],
            "operator": "MINIMUM", "threshold_low": "18", "threshold_high": "",
            "purpose": "Confirm eligibility for account registration",
        }
        review = client.post("/organisation/verifications/review", data=age_form)
        token = hidden(review.text, "submission_token")
        submitted = dict(age_form, submission_token=token)
        first = client.post("/organisation/verifications/submit", data=submitted)
        second = client.post("/organisation/verifications/submit", data=submitted)
        if first.status_code != 303 or second.headers.get("location") != first.headers.get("location"):
            raise AssertionError(f"Duplicate instant submission was not idempotent: first={first.status_code} {first.headers.get('location')} second={second.status_code} {second.headers.get('location')} first-body={first.text[-1200:]}")
        instant_reference = first.headers["location"].rsplit("/", 1)[-1]

        consent_form = {
            "csrf_token": csrf, "claim_code": "FULL_LEGAL_NAME", "identifier": citizen["synthetic_nin"],
            "operator": "DISCLOSE_WITH_CONSENT", "threshold_low": "", "threshold_high": "",
            "purpose": "Complete a regulated customer registration",
        }
        review = client.post("/organisation/verifications/review", data=consent_form)
        consent_token = hidden(review.text, "submission_token")
        consent_submit = dict(consent_form, submission_token=consent_token)
        pending = client.post("/organisation/verifications/submit", data=consent_submit)
        duplicate = client.post("/organisation/verifications/submit", data=consent_submit)
        if pending.status_code != 303 or duplicate.headers.get("location") != pending.headers.get("location"):
            raise AssertionError("Duplicate consent submission was not idempotent")
        pending_reference = pending.headers["location"].rsplit("/", 1)[-1]

        with connection() as conn:
            instant = fetch_one(conn, "SELECT * FROM verifications WHERE public_reference=%s", (instant_reference,))
            pending_row = fetch_one(conn, "SELECT * FROM verifications WHERE public_reference=%s", (pending_reference,))
            verification_ids.extend([instant["id"], pending_row["id"]])
            consent = fetch_one(conn, "SELECT * FROM consent_requests WHERE verification_id=%s", (pending_row["id"],))
            sms = fetch_all(conn, "SELECT * FROM sms_deliveries WHERE consent_request_id=%s", (consent["id"],))
            history = fetch_all(conn, "SELECT * FROM request_history WHERE organisation_id=%s AND subject_reference=%s", (org_ids[0], instant["subject_reference"]))
            if len(sms) != 1 or len(history) != 1:
                raise AssertionError("Expected one SMS and one privacy-safe age history record")
            if instant["expires_at"] - instant["issued_at"] != timedelta(hours=24):
                raise AssertionError("Short result TTL is not 24 hours")
            if consent["expires_at"] <= utcnow_naive() or pending_row["result"] != "PENDING":
                raise AssertionError("Consent request is not pending with expiry")
            leaked = str(fetch_all(conn, "SELECT detail FROM audit_log WHERE target_reference IN (%s,%s)", (instant_reference, pending_reference)))
            if citizen["synthetic_nin"] in leaked:
                raise AssertionError("Raw identifier leaked into audit data")

        phone = TestClient(app, follow_redirects=False)
        connected = phone.post("/phone/connect", data={"phone_number": citizen["registered_phone"]})
        inbox = phone.get("/phone/messages")
        if connected.status_code != 303 or "sent a new TrustID request" not in inbox.text or "1 unread" not in inbox.text:
            raise AssertionError(f"Persistent consent inbox did not render an unread message: connect={connected.status_code} body={inbox.text[-1600:]}")
        message_id = re.search(r'/phone/messages/(\d+)', inbox.text).group(1)
        detail = phone.get(f"/phone/messages/{message_id}")
        if "No personal information has been shared" not in detail.text:
            raise AssertionError("Consent SMS detail was not privacy safe")
        phone.post("/phone/connect", data={"phone_number": other_citizen["registered_phone"]})
        other_inbox = phone.get("/phone/messages")
        if f"Phase 5 Organization 0 {suffix}" in other_inbox.text:
            raise AssertionError("Switching phone numbers exposed another number's inbox")
        phone.post("/phone/connect", data={"phone_number": citizen["registered_phone"]})
        restored_inbox = phone.get("/phone/messages")
        if f"Phase 5 Organization 0 {suffix}" not in restored_inbox.text or "0 unread" not in restored_inbox.text:
            raise AssertionError("Returning to a phone number did not restore its persistent read inbox")

        # Delivery state is independent from consent state and failure is non-fatal.
        with connection() as conn:
            execute(conn, "UPDATE sms_deliveries SET delivery_status='FAILED',delivered_at=NULL,failure_code='PROVIDER_UNAVAILABLE' WHERE consent_request_id=%s", (consent["id"],))
            still_pending = fetch_one(conn, "SELECT status FROM consent_requests WHERE id=%s", (consent["id"],))
            if still_pending["status"] != "PENDING":
                raise AssertionError("SMS delivery failure cancelled the pending consent request")
            conn.commit()

        other.post("/organisation/login", data={"identifier": f"phase5-1-{suffix}@trustid.test", "password": "Phase5Portal88"})
        isolated = other.get(f"/organisation/verifications/{instant_reference}")
        if isolated.status_code != 303:
            raise AssertionError("Cross-organization verification reference was exposed")

        forged = client.post("/organisation/verifications/review", data={
            "csrf_token": csrf, "claim_code": "LICENCE_STATUS", "identifier": "LIC-000000000",
            "operator": "IS_VALID", "purpose": "Confirm driver eligibility for onboarding",
        })
        if "not available for your organization" not in forged.text:
            raise AssertionError("Forged unpermitted claim was not rejected")

        # A status change after review must be enforced again before source access.
        review = client.post("/organisation/verifications/review", data=age_form)
        blocked_token = hidden(review.text, "submission_token")
        with connection() as conn:
            execute(conn, "UPDATE organisations SET status='SUSPENDED',status_reason='Acceptance check' WHERE id=%s", (org_ids[0],))
            conn.commit()
        blocked = client.post("/organisation/verifications/submit", data=dict(age_form, submission_token=blocked_token))
        with connection() as conn:
            token_row = fetch_one(conn, "SELECT verification_id FROM verification_submissions WHERE token_hash=%s", (digest_token(blocked_token),))
            execute(conn, "UPDATE organisations SET status='APPROVED',status_reason=NULL WHERE id=%s", (org_ids[0],))
            conn.commit()
        if blocked.status_code != 303 or token_row["verification_id"] is not None:
            raise AssertionError("Organization status change was not rechecked at submission")

        with connection() as conn:
            execute(conn, "UPDATE verifications SET expires_at=UTC_TIMESTAMP()-INTERVAL 1 MINUTE WHERE id=%s", (pending_row["id"],))
            conn.commit()
        expired = client.get(f"/organisation/verifications/{pending_reference}")
        if "approval request has expired" not in expired.text:
            raise AssertionError("Expired consent request did not show the professional expired state")

        print("Phase 5 acceptance test passed: guided portal, policy enforcement, idempotency, TTL, privacy-safe history, consent SMS, persistent inbox and organization isolation.")
    finally:
        with connection() as conn:
            if org_ids:
                marks = ",".join(["%s"] * len(org_ids))
                execute(conn, f"DELETE FROM auth_sessions WHERE actor_type='ORGANISATION' AND actor_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM audit_log WHERE actor_type='ORGANISATION' AND actor_id IN ({marks})", tuple(org_ids))
                execute(conn, f"""DELETE a FROM audit_log a JOIN verifications v
                    ON v.public_reference=a.target_reference WHERE v.organisation_id IN ({marks})""", tuple(org_ids))
                execute(conn, f"DELETE FROM request_history WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM sms_deliveries WHERE consent_request_id IN (SELECT id FROM consent_requests WHERE organisation_id IN ({marks}))", tuple(org_ids))
                execute(conn, f"DELETE FROM consent_requests WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM receipts WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"UPDATE verification_submissions SET verification_id=NULL WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM verifications WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM verification_submissions WHERE organisation_id IN ({marks})", tuple(org_ids))
                execute(conn, f"DELETE FROM organisations WHERE id IN ({marks})", tuple(org_ids))
            conn.commit()


if __name__ == "__main__":
    main()
