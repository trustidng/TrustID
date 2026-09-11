from app.policy.contracts import PolicyDecision, PolicyDecisionCode
from app.policy.messages import CONSENT_STATUS_MESSAGES, POLICY_MESSAGES


def test_policy_messages_are_professional_and_hide_confirmation_mechanics():
    assert POLICY_MESSAGES[PolicyDecisionCode.REQUIRE_CONSENT] == "The citizen's approval is required to continue."
    assert POLICY_MESSAGES[PolicyDecisionCode.REQUIRE_STRONG_CONSENT] == POLICY_MESSAGES[PolicyDecisionCode.REQUIRE_CONSENT]
    combined = " ".join(POLICY_MESSAGES.values()).casefold()
    assert "pin" not in combined and "otp" not in combined and "hmac" not in combined
    assert CONSENT_STATUS_MESSAGES["REJECTED"] == "The citizen declined this request."


def test_policy_decision_properties():
    consent = PolicyDecision(PolicyDecisionCode.REQUIRE_CONSENT, "CITIZEN_APPROVAL_REQUIRED", POLICY_MESSAGES[PolicyDecisionCode.REQUIRE_CONSENT])
    denied = PolicyDecision(PolicyDecisionCode.DENY_UNAUTHORIZED_CLAIM, "CLAIM_NOT_PERMITTED_FOR_CATEGORY", POLICY_MESSAGES[PolicyDecisionCode.DENY_UNAUTHORIZED_CLAIM])
    assert consent.permitted and consent.requires_approval
    assert not denied.permitted and not denied.requires_approval
