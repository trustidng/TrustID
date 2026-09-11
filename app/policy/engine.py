from ..auth import audit
from ..db import connection, fetch_all, fetch_one
from ..verification.contracts import ClaimCode
from .contracts import PolicyDecision, PolicyDecisionCode
from .messages import POLICY_MESSAGES


MODE_DECISIONS = {
    "INSTANT": PolicyDecisionCode.ALLOW_INSTANT,
    "CONSENT": PolicyDecisionCode.REQUIRE_CONSENT,
    "STRONG_CONSENT": PolicyDecisionCode.REQUIRE_STRONG_CONSENT,
}


class PolicyEngine:
    def __init__(self, connection_factory=connection):
        self.connection_factory = connection_factory

    def decide(self, organisation_id: int, claim_code: ClaimCode | str, *, rate_limited=False, inference_risk=False) -> PolicyDecision:
        try:
            claim = ClaimCode(claim_code).value
        except (ValueError, TypeError):
            claim = "UNKNOWN"
        with self.connection_factory() as conn:
            organisation = fetch_one(conn, """SELECT o.id,o.status,o.category_id,c.active AS category_active
                FROM organisations o JOIN organisation_categories c ON c.id=o.category_id
                WHERE o.id=%s""", (organisation_id,))
            if not organisation or organisation["status"] != "APPROVED":
                return self._record(conn, organisation_id, claim, PolicyDecisionCode.DENY_ORG_NOT_APPROVED, "ORGANISATION_NOT_APPROVED")
            permission = fetch_one(conn, """SELECT d.privacy_mode
                FROM category_claim_permissions p JOIN claim_definitions d ON d.claim_code=p.claim_code
                WHERE p.category_id=%s AND p.claim_code=%s AND d.active=TRUE""",
                (organisation["category_id"], claim)) if organisation["category_active"] else None
            if not permission:
                return self._record(conn, organisation_id, claim, PolicyDecisionCode.DENY_UNAUTHORIZED_CLAIM, "CLAIM_NOT_PERMITTED_FOR_CATEGORY")
            if rate_limited:
                return self._record(conn, organisation_id, claim, PolicyDecisionCode.DENY_RATE_LIMIT, "REQUEST_LIMIT_REACHED")
            if inference_risk:
                return self._record(conn, organisation_id, claim, PolicyDecisionCode.DENY_INFERENCE_RISK, "PERMITTED_VERIFICATION_LIMIT_EXCEEDED")
            code = MODE_DECISIONS[permission["privacy_mode"]]
            reason = {
                PolicyDecisionCode.ALLOW_INSTANT: "CATEGORY_PERMISSION_GRANTED",
                PolicyDecisionCode.REQUIRE_CONSENT: "CITIZEN_APPROVAL_REQUIRED",
                PolicyDecisionCode.REQUIRE_STRONG_CONSENT: "SENSITIVE_ATTRIBUTE_APPROVAL_REQUIRED",
            }[code]
            return self._record(conn, organisation_id, claim, code, reason)

    def available_claims(self, organisation_id: int) -> list[dict]:
        with self.connection_factory() as conn:
            organisation = fetch_one(conn, """SELECT o.status,o.category_id,c.active AS category_active
                FROM organisations o JOIN organisation_categories c ON c.id=o.category_id WHERE o.id=%s""", (organisation_id,))
            if not organisation or organisation["status"] != "APPROVED" or not organisation["category_active"]:
                return []
            rows = fetch_all(conn, """SELECT d.claim_code,d.display_name,d.action_type,d.privacy_mode
                FROM category_claim_permissions p JOIN claim_definitions d ON d.claim_code=p.claim_code
                WHERE p.category_id=%s AND d.active=TRUE
                ORDER BY d.action_type DESC,d.display_name""", (organisation["category_id"],))
        for row in rows:
            row["approval_required"] = row["privacy_mode"] != "INSTANT"
        return rows

    @staticmethod
    def _record(conn, organisation_id, claim, code, reason_code):
        audit(conn, "POLICY_DECISION", "ORGANISATION", organisation_id, str(organisation_id), {
            "claim_code": claim,
            "decision": code.value,
            "reason_code": reason_code,
        })
        conn.commit()
        return PolicyDecision(code, reason_code, POLICY_MESSAGES[code])
