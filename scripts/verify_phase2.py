"""End-to-end Phase 2 smoke test against the configured local MySQL database.

Creates temporary synthetic application/session records and removes them in a
finally block. It never runs schema.sql or seed_data.py.
"""
import re
import secrets
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.db import connection, execute, fetch_one
from app.main import app
from app.security import hash_password


def require(response, expected: int, label: str) -> None:
    if response.status_code != expected:
        raise AssertionError(f"{label}: expected HTTP {expected}, got {response.status_code}")


def hidden(html: str, name: str) -> str:
    match = re.search(rf'name="{re.escape(name)}" value="([^"]*)"', html)
    if not match:
        raise AssertionError(f"Missing hidden field {name}")
    return match.group(1)


def inbox_otp(html: str) -> str:
    match = re.search(r'letter-spacing:\.2rem">(\d{6})', html)
    if not match:
        raise AssertionError("Activation code was not present in the SMS inbox")
    return match.group(1)


def main() -> None:
    suffix = secrets.token_hex(4)
    email = f"phase2-{suffix}@trustid.test"
    admin_username = f"phase2-admin-{suffix}"
    admin_password = "UpdatedAdmin8"
    unknown_phone = f"+234809{secrets.randbelow(10_000_000):07d}"
    org_id = None
    citizen_id = None
    citizen_original = None
    ussd_citizen_id = None
    ussd_citizen_original = None
    admin_id = None
    client = TestClient(app, follow_redirects=False)
    try:
        with connection() as conn:
            retail_category_id = fetch_one(conn, "SELECT id FROM organisation_categories WHERE code='RETAIL'")["id"]
            execute(conn, "INSERT INTO admin_users (username,password_hash,must_change_password) VALUES (%s,%s,TRUE)", (admin_username, hash_password("InitialAdmin7")))
            admin_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            conn.commit()
        require(client.get("/health"), 200, "health")
        require(client.get("/"), 200, "home")

        response = client.post("/admin/login", data={"identifier": admin_username, "password": "InitialAdmin7"})
        require(response, 303, "admin login")
        if response.headers.get("location") != "/admin/change-password":
            raise AssertionError("Bootstrap administrator was not required to change password")
        change_page = client.get("/admin/change-password")
        require(change_page, 200, "administrator password-change page")
        csrf = hidden(change_page.text, "csrf_token")
        response = client.post("/admin/change-password", data={
            "csrf_token": csrf, "current_password": "InitialAdmin7", "new_password": admin_password, "password_confirm": admin_password,
        })
        require(response, 303, "administrator password change")
        require(client.get("/admin"), 200, "admin dashboard")

        client.cookies.clear()
        response = client.post("/organisation/register", data={
            "business_name": "Phase 2 Test Organisation",
            "email": email,
            "phone": "+2348030000001",
            "category_id": retail_category_id,
            "registration_reference": "PHASE2-SMOKE",
            "intended_use": "Automated Phase 2 workflow verification",
            "password": "TestingPass7",
            "password_confirm": "TestingPass7",
        })
        require(response, 303, "organisation registration")
        with connection() as conn:
            org = fetch_one(conn, "SELECT id, status FROM organisations WHERE email=%s", (email,))
            if not org or org["status"] != "PENDING":
                raise AssertionError("New organisation was not created as PENDING")
            org_id = org["id"]

        response = client.post("/organisation/login", data={"identifier": email, "password": "TestingPass7"})
        require(response, 303, "pending organisation login")
        pending_page = client.get("/organisation")
        require(pending_page, 200, "pending organisation dashboard")
        if "PENDING" not in pending_page.text:
            raise AssertionError("Pending status is not visible")

        client.cookies.clear()
        require(client.post("/admin/login", data={"identifier": admin_username, "password": admin_password}), 303, "admin relogin")
        admin_page = client.get("/admin")
        csrf = hidden(admin_page.text, "csrf_token")
        forbidden = client.post(f"/admin/organisations/{org_id}/status", data={
            "csrf_token": "invalid", "new_status": "APPROVED", "category_id": retail_category_id, "reason": "Must fail",
        })
        require(forbidden, 403, "CSRF rejection")
        response = client.post(f"/admin/organisations/{org_id}/status", data={
            "csrf_token": csrf, "new_status": "APPROVED", "category_id": retail_category_id, "reason": "Smoke test approval",
        })
        require(response, 303, "organisation approval")

        client.cookies.clear()
        require(client.post("/organisation/login", data={"identifier": email, "password": "TestingPass7"}), 303, "approved organisation login")
        approved_page = client.get("/organisation")
        require(approved_page, 200, "approved organisation dashboard")
        if "APPROVED" not in approved_page.text:
            raise AssertionError("Approved status is not visible")

        admin_client = TestClient(app, follow_redirects=False)
        require(admin_client.post("/admin/login", data={"identifier": admin_username, "password": admin_password}), 303, "administrator lifecycle login")
        admin_page = admin_client.get("/admin")
        admin_csrf = hidden(admin_page.text, "csrf_token")
        suspended = admin_client.post(f"/admin/organisations/{org_id}/status", data={
            "csrf_token": admin_csrf, "new_status": "SUSPENDED", "reason": "Temporary policy review",
        })
        require(suspended, 303, "organisation suspension")
        require(client.get("/organisation"), 303, "suspension session revocation")
        suspended_page = admin_client.get("/admin?status_filter=SUSPENDED")
        if "Reinstate organization" not in suspended_page.text:
            raise AssertionError("Suspended organization did not receive a reinstatement action")
        reinstated = admin_client.post(f"/admin/organisations/{org_id}/status", data={
            "csrf_token": admin_csrf, "new_status": "APPROVED",
        })
        require(reinstated, 303, "organisation reinstatement")
        with connection() as conn:
            lifecycle = fetch_one(conn, "SELECT status,status_reason FROM organisations WHERE id=%s", (org_id,))
            reinstatement_event = fetch_one(conn, "SELECT id FROM audit_log WHERE event_type='ORG_REINSTATED' AND target_reference=%s", (str(org_id),))
            if lifecycle["status"] != "APPROVED" or lifecycle["status_reason"] is not None or not reinstatement_event:
                raise AssertionError("Reinstatement did not restore a clean approved state with an audit event")
        require(client.post("/organisation/login", data={"identifier": email, "password": "TestingPass7"}), 303, "reinstated organisation login")
        approved_page = client.get("/organisation")
        org_csrf = hidden(approved_page.text, "csrf_token")
        require(client.post("/logout", data={"csrf_token": org_csrf}), 303, "organisation logout")
        require(client.get("/organisation"), 303, "logged-out organisation route protection")

        for _ in range(5):
            client.post("/organisation/login", data={"identifier": email, "password": "WrongPassword7"})
        with connection() as conn:
            locked = fetch_one(conn, "SELECT locked_until FROM organisations WHERE id=%s", (org_id,))
            if not locked or locked["locked_until"] is None:
                raise AssertionError("Repeated failures did not lock the organisation account")

        client.cookies.clear()
        with connection() as conn:
            citizen = fetch_one(conn, """SELECT citizen_id, pin_hash, account_activated, activated_at,
                failed_pin_attempts, locked_until, last_login_at
                FROM citizens WHERE account_activated=FALSE AND record_status='ACTIVE' LIMIT 1""")
            phone = fetch_one(conn, "SELECT registered_phone FROM citizens WHERE citizen_id=%s", (citizen["citizen_id"],))["registered_phone"]
            citizen_id = citizen["citizen_id"]
            citizen_original = citizen

        activation = client.post("/citizen/activate/request", data={"phone": phone})
        require(activation, 200, "activation-code request")
        challenge_id = hidden(activation.text, "challenge_id")
        if "Open SMS inbox" in activation.text or "/phone/inbox/" in activation.text:
            raise AssertionError("Activation page exposed an unnecessary SMS inbox shortcut")

        connect = client.post("/phone/connect", data={"phone_number": phone})
        require(connect, 303, "TrustID Phone connection")
        if connect.headers.get("location") != "/phone":
            raise AssertionError("TrustID Phone did not open after connecting the registered number")
        require(client.get("/phone"), 200, "TrustID Phone home")

        second_activation = client.post("/citizen/activate/request", data={"phone": phone})
        require(second_activation, 200, "second activation-code request")
        challenge_id = hidden(second_activation.text, "challenge_id")
        inbox_page = client.get("/phone/messages")
        require(inbox_page, 200, "SMS inbox")
        message_links = re.findall(r'href="(/phone/messages/\d+)"', inbox_page.text)
        if len(message_links) < 2:
            raise AssertionError("The phone inbox did not retain older messages")
        message = client.get(message_links[0])
        require(message, 200, "SMS message detail")
        if "Welcome to TrustID" not in message.text:
            raise AssertionError("Activation SMS is missing the TrustID welcome message")
        otp = inbox_otp(message.text)
        response = client.post("/citizen/activate/complete", data={
            "challenge_id": challenge_id, "otp": otp, "pin": "4826", "pin_confirm": "4826",
        })
        require(response, 303, "activation completion")
        already_active = client.post("/citizen/activate/request", data={"phone": phone})
        require(already_active, 200, "already-active activation request")
        if "already active" not in already_active.text or "/phone/inbox/" in already_active.text:
            raise AssertionError("Already-active account did not receive the correct activation guidance")
        require(client.post("/citizen/login", data={"identifier": phone, "password": "4826"}), 303, "citizen login")
        citizen_page = client.get("/citizen")
        require(citizen_page, 200, "citizen dashboard")
        citizen_csrf = hidden(citizen_page.text, "csrf_token")
        require(client.post("/logout", data={"csrf_token": citizen_csrf}), 303, "citizen logout")
        require(client.get("/citizen"), 303, "logged-out citizen route protection")

        require(client.get("/phone/dialer"), 200, "phone dialler")
        ussd = client.post("/phone/dial", data={"service_code": "*7305#"})
        require(ussd, 200, "USSD returning-citizen recognition")
        if "Welcome back to TrustID. Enter your TrustID PIN using numbers only" not in ussd.text or "1. Sign in" in ussd.text:
            raise AssertionError("USSD did not take the active citizen directly to the PIN prompt")
        ussd_token = hidden(ussd.text, "ussd_token")
        signed_in = client.post("/phone/ussd/respond", data={"ussd_token": ussd_token, "response": "4826"})
        require(signed_in, 200, "USSD PIN login")
        if "requests are awaiting your attention" not in signed_in.text and "request is awaiting your attention" not in signed_in.text:
            raise AssertionError("USSD did not open the authenticated TrustID menu")
        require(client.get("/citizen"), 200, "USSD-authenticated citizen dashboard")

        client.cookies.clear()
        with connection() as conn:
            ussd_citizen = fetch_one(conn, """SELECT citizen_id, registered_phone, pin_hash, account_activated,
                activated_at, failed_pin_attempts, locked_until, last_login_at
                FROM citizens WHERE account_activated=FALSE AND record_status='ACTIVE' AND citizen_id<>%s LIMIT 1""", (citizen_id,))
            if not ussd_citizen:
                raise AssertionError("No inactive citizen is available for the USSD activation test")
            ussd_citizen_id = ussd_citizen["citizen_id"]
            ussd_citizen_original = ussd_citizen
        require(client.post("/phone/connect", data={"phone_number": ussd_citizen["registered_phone"]}), 303, "USSD activation phone connection")
        ussd = client.post("/phone/dial", data={"service_code": "*7305#"})
        require(ussd, 200, "USSD activation menu")
        if "1. Activate account" not in ussd.text:
            raise AssertionError("USSD did not show the inactive-citizen menu")
        activation_token = hidden(ussd.text, "ussd_token")
        invalid_option = client.post("/phone/ussd/respond", data={"ussd_token": activation_token, "response": "9"})
        if "Invalid option" not in invalid_option.text:
            raise AssertionError("USSD did not keep the session open after an invalid menu option")
        new_pin = client.post("/phone/ussd/respond", data={"ussd_token": activation_token, "response": "1"})
        if "Create a 4–6 digit TrustID PIN using numbers only" not in new_pin.text or "Confirm your TrustID PIN" in new_pin.text:
            raise AssertionError("USSD did not present PIN creation as a single step")
        confirm_pin = client.post("/phone/ussd/respond", data={"ussd_token": activation_token, "response": "7319"})
        if "Confirm your TrustID PIN using numbers only" not in confirm_pin.text or "Create a 4–6 digit" in confirm_pin.text:
            raise AssertionError("USSD did not advance to a separate PIN-confirmation step")
        mismatch = client.post("/phone/ussd/respond", data={"ussd_token": activation_token, "response": "7318"})
        if "PINs do not match" not in mismatch.text or "Create a 4–6 digit TrustID PIN" not in mismatch.text:
            raise AssertionError("USSD did not restart PIN creation after a mismatch")
        client.post("/phone/ussd/respond", data={"ussd_token": activation_token, "response": "7319"})
        activated = client.post("/phone/ussd/respond", data={"ussd_token": activation_token, "response": "7319"})
        if "activated successfully" not in activated.text:
            raise AssertionError("USSD activation did not complete after matching PINs")

        client.cookies.clear()
        require(client.post("/phone/connect", data={"phone_number": unknown_phone}), 303, "unrecognized-number phone start")
        clean_inbox = client.get("/phone/messages")
        require(clean_inbox, 200, "clean inbox after changing number")
        if "No messages" not in clean_inbox.text:
            raise AssertionError("Changing the phone number did not clear the visible handset inbox")
        response = client.post("/phone/dial", data={"service_code": "*7305#"})
        require(response, 200, "unrecognized-number USSD response")
        if "Please dial using the mobile number registered with your NIN" not in response.text:
            raise AssertionError("USSD did not return the professional unrecognized-number guidance")

        print("Phase 2 smoke test passed: admin lifecycle, SMS inbox, centralized phone, citizen activation, USSD, lockouts, sessions and cleanup.")
    finally:
        with connection() as conn:
            if org_id is not None:
                execute(conn, "DELETE FROM auth_sessions WHERE actor_type='ORGANISATION' AND actor_id=%s", (org_id,))
                execute(conn, "DELETE FROM audit_log WHERE target_reference=%s", (str(org_id),))
                execute(conn, "DELETE FROM organisations WHERE id=%s", (org_id,))
            if citizen_id is not None and citizen_original is not None:
                execute(conn, "DELETE FROM auth_sessions WHERE actor_type='CITIZEN' AND actor_id=%s", (citizen_id,))
                execute(conn, "DELETE FROM phone_sessions WHERE citizen_id=%s", (citizen_id,))
                execute(conn, "DELETE FROM otp_challenges WHERE citizen_id=%s", (citizen_id,))
                execute(conn, "DELETE FROM audit_log WHERE actor_type='CITIZEN' AND actor_id=%s AND event_type='ACCOUNT_ACTIVATED'", (citizen_id,))
                execute(conn, """UPDATE citizens SET pin_hash=%s, account_activated=%s, activated_at=%s,
                    failed_pin_attempts=%s, locked_until=%s, last_login_at=%s WHERE citizen_id=%s""",
                    (citizen_original["pin_hash"], citizen_original["account_activated"], citizen_original["activated_at"],
                     citizen_original["failed_pin_attempts"], citizen_original["locked_until"], citizen_original["last_login_at"], citizen_id))
            if ussd_citizen_id is not None and ussd_citizen_original is not None:
                execute(conn, "DELETE FROM auth_sessions WHERE actor_type='CITIZEN' AND actor_id=%s", (ussd_citizen_id,))
                execute(conn, "DELETE FROM phone_sessions WHERE citizen_id=%s", (ussd_citizen_id,))
                execute(conn, "DELETE FROM audit_log WHERE actor_type='CITIZEN' AND actor_id=%s AND event_type='ACCOUNT_ACTIVATED'", (ussd_citizen_id,))
                execute(conn, """UPDATE citizens SET pin_hash=%s, account_activated=%s, activated_at=%s,
                    failed_pin_attempts=%s, locked_until=%s, last_login_at=%s WHERE citizen_id=%s""",
                    (ussd_citizen_original["pin_hash"], ussd_citizen_original["account_activated"], ussd_citizen_original["activated_at"],
                     ussd_citizen_original["failed_pin_attempts"], ussd_citizen_original["locked_until"], ussd_citizen_original["last_login_at"], ussd_citizen_id))
            if admin_id is not None:
                execute(conn, "DELETE FROM auth_sessions WHERE actor_type='ADMIN' AND actor_id=%s", (admin_id,))
                execute(conn, "DELETE FROM admin_users WHERE id=%s", (admin_id,))
            execute(conn, "DELETE FROM phone_sessions WHERE phone_number=%s", (unknown_phone,))
            conn.commit()


if __name__ == "__main__":
    main()
