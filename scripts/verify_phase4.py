"""End-to-end Phase 4 policy and custom-category acceptance test."""
import json
from pathlib import Path
import re
import secrets
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.db import connection, execute, fetch_all, fetch_one
from app.main import app
from app.policy import PolicyDecisionCode, PolicyEngine
from app.security import hash_password


def hidden(html: str, name: str) -> str:
    match = re.search(rf'name="{name}" value="([^"]*)"', html)
    if not match:
        raise AssertionError(f"Missing hidden field {name}")
    return match.group(1)


def main() -> None:
    suffix = secrets.token_hex(4).upper()
    admin_id = category_id = approved_org_id = pending_org_id = None
    client = TestClient(app, follow_redirects=False)
    try:
        with connection() as conn:
            execute(conn, "INSERT INTO admin_users (username,password_hash,must_change_password) VALUES (%s,%s,FALSE)",
                    (f"phase4-admin-{suffix}", hash_password("PolicyAdmin8")))
            admin_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            conn.commit()
        login = client.post("/admin/login", data={"identifier": f"phase4-admin-{suffix}", "password": "PolicyAdmin8"})
        if login.status_code != 303:
            raise AssertionError("Phase 4 administrator could not sign in")
        page = client.get("/admin/categories")
        if page.status_code != 200 or "Citizen approval required" not in page.text:
            raise AssertionError("Category management did not explain approval-protected claims")
        csrf = hidden(page.text, "csrf_token")
        create = client.post("/admin/categories", data={
            "csrf_token": csrf,
            "name": "Education Provider " + suffix,
            "code": "EDUCATION_" + suffix,
            "description": "Synthetic Phase 4 category",
            "claim_codes": ["AGE_COMPARE", "FULL_LEGAL_NAME", "RESIDENTIAL_ADDRESS",
                            "NAME_MATCH", "REGISTERED_RESIDENCE"],
        })
        if create.status_code != 303:
            raise AssertionError("Custom category creation failed")
        with connection() as conn:
            category = fetch_one(conn, "SELECT id FROM organisation_categories WHERE code=%s", ("EDUCATION_" + suffix,))
            if not category:
                raise AssertionError("Custom category was not stored")
            category_id = category["id"]
            execute(conn, """INSERT INTO organisations
                (business_name,email,phone,category_id,status,password_hash,intended_use)
                VALUES (%s,%s,'+2348030000002',%s,'APPROVED',%s,'Phase 4 policy acceptance')""",
                ("Approved Policy Org " + suffix, f"approved-{suffix}@trustid.test", category_id, hash_password("PolicyOrg88")))
            approved_org_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            execute(conn, """INSERT INTO organisations
                (business_name,email,phone,category_id,status,password_hash,intended_use)
                VALUES (%s,%s,'+2348030000003',%s,'PENDING',%s,'Phase 4 status precedence')""",
                ("Pending Policy Org " + suffix, f"pending-{suffix}@trustid.test", category_id, hash_password("PolicyOrg88")))
            pending_org_id = fetch_one(conn, "SELECT LAST_INSERT_ID() id")["id"]
            conn.commit()

        policy = PolicyEngine()
        expected = {
            "AGE_COMPARE": PolicyDecisionCode.ALLOW_INSTANT,
            "FULL_LEGAL_NAME": PolicyDecisionCode.REQUIRE_CONSENT,
            "RESIDENTIAL_ADDRESS": PolicyDecisionCode.REQUIRE_STRONG_CONSENT,
            "NAME_MATCH": PolicyDecisionCode.ALLOW_INSTANT,
            "REGISTERED_RESIDENCE": PolicyDecisionCode.REQUIRE_STRONG_CONSENT,
            "LICENCE_STATUS": PolicyDecisionCode.DENY_UNAUTHORIZED_CLAIM,
        }
        for claim, decision_code in expected.items():
            decision = policy.decide(approved_org_id, claim)
            if decision.code != decision_code:
                raise AssertionError(f"Unexpected policy result for {claim}: {decision.code}")
        if policy.decide(pending_org_id, "LICENCE_STATUS").code != PolicyDecisionCode.DENY_ORG_NOT_APPROVED:
            raise AssertionError("Organization approval was not checked before claim permission")
        if policy.decide(approved_org_id, "AGE_COMPARE", rate_limited=True).code != PolicyDecisionCode.DENY_RATE_LIMIT:
            raise AssertionError("Rate-limit policy hook failed")
        if policy.decide(approved_org_id, "AGE_COMPARE", inference_risk=True).code != PolicyDecisionCode.DENY_INFERENCE_RISK:
            raise AssertionError("Inference-risk policy hook failed")
        available = policy.available_claims(approved_org_id)
        if {item["claim_code"] for item in available} != {
                "AGE_COMPARE", "FULL_LEGAL_NAME", "RESIDENTIAL_ADDRESS",
                "NAME_MATCH", "REGISTERED_RESIDENCE"}:
            raise AssertionError("Available verification options did not match category permissions")
        if policy.available_claims(pending_org_id):
            raise AssertionError("A pending organization received verification options")

        page = client.get("/admin/categories")
        csrf = hidden(page.text, "csrf_token")
        update = client.post(f"/admin/categories/{category_id}", data={
            "csrf_token": csrf,
            "name": "Education Provider " + suffix,
            "description": "Updated synthetic Phase 4 category",
            "active": "1",
            "claim_codes": ["IDENTITY_STATUS"],
        })
        if update.status_code != 303:
            raise AssertionError("Custom category permission update failed")
        if policy.decide(approved_org_id, "AGE_COMPARE").code != PolicyDecisionCode.DENY_UNAUTHORIZED_CLAIM:
            raise AssertionError("Removed permission did not take effect immediately")
        if policy.decide(approved_org_id, "NAME_MATCH").code != PolicyDecisionCode.DENY_UNAUTHORIZED_CLAIM:
            raise AssertionError("Removed name-match permission did not take effect immediately")
        if policy.decide(approved_org_id, "REGISTERED_RESIDENCE").code != PolicyDecisionCode.DENY_UNAUTHORIZED_CLAIM:
            raise AssertionError("Removed residence permission did not take effect immediately")
        if policy.decide(approved_org_id, "IDENTITY_STATUS").code != PolicyDecisionCode.ALLOW_INSTANT:
            raise AssertionError("Added permission did not take effect immediately")
        with connection() as conn:
            address_mode = fetch_one(conn, "SELECT privacy_mode FROM claim_definitions WHERE claim_code='RESIDENTIAL_ADDRESS'")["privacy_mode"]
        if address_mode != "STRONG_CONSENT":
            raise AssertionError("Category management weakened a fixed claim privacy rule")

        page = client.get("/admin/categories")
        csrf = hidden(page.text, "csrf_token")
        client.post(f"/admin/categories/{category_id}", data={
            "csrf_token": csrf,
            "name": "Education Provider " + suffix,
            "description": "Disabled synthetic Phase 4 category",
            "claim_codes": ["IDENTITY_STATUS"],
        })
        if policy.available_claims(approved_org_id):
            raise AssertionError("A disabled category still exposed verification options")
        if policy.decide(approved_org_id, "IDENTITY_STATUS").code != PolicyDecisionCode.DENY_UNAUTHORIZED_CLAIM:
            raise AssertionError("A disabled category could still authorize a verification")

        with connection() as conn:
            audit_rows = fetch_all(conn, "SELECT detail FROM audit_log WHERE event_type='POLICY_DECISION' AND actor_id=%s", (approved_org_id,))
        for row in audit_rows:
            detail = row["detail"] if isinstance(row["detail"], dict) else json.loads(row["detail"])
            if set(detail) != {"claim_code", "decision", "reason_code"}:
                raise AssertionError("Policy audit detail exceeded its privacy-safe allowlist")
        print("Phase 4 acceptance test passed: custom categories, permissions, decision order, consent modes, filtering and audit records.")
    finally:
        with connection() as conn:
            for org_id in (approved_org_id, pending_org_id):
                if org_id:
                    execute(conn, "DELETE FROM auth_sessions WHERE actor_type='ORGANISATION' AND actor_id=%s", (org_id,))
                    execute(conn, "DELETE FROM audit_log WHERE actor_type='ORGANISATION' AND actor_id=%s", (org_id,))
                    execute(conn, "DELETE FROM organisations WHERE id=%s", (org_id,))
            if category_id:
                execute(conn, "DELETE FROM audit_log WHERE target_reference=%s", (str(category_id),))
                execute(conn, "DELETE FROM organisation_categories WHERE id=%s", (category_id,))
            if admin_id:
                execute(conn, "DELETE FROM auth_sessions WHERE actor_type='ADMIN' AND actor_id=%s", (admin_id,))
                execute(conn, "DELETE FROM admin_users WHERE id=%s", (admin_id,))
            conn.commit()


if __name__ == "__main__":
    main()
