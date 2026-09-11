from .contracts import PolicyDecisionCode


POLICY_MESSAGES = {
    PolicyDecisionCode.ALLOW_INSTANT: "You can proceed with this verification.",
    PolicyDecisionCode.REQUIRE_CONSENT: "The citizen's approval is required to continue.",
    PolicyDecisionCode.REQUIRE_STRONG_CONSENT: "The citizen's approval is required to continue.",
    PolicyDecisionCode.DENY_ORG_NOT_APPROVED: "Your organization must be approved before it can request verifications.",
    PolicyDecisionCode.DENY_UNAUTHORIZED_CLAIM: "Your organization is not authorized to request this verification.",
    PolicyDecisionCode.DENY_RATE_LIMIT: "The verification request limit has been reached. Please try again later.",
    PolicyDecisionCode.DENY_INFERENCE_RISK: "This request cannot be completed because it exceeds the permitted verification limits.",
}

CONSENT_STATUS_MESSAGES = {
    "PENDING": "Awaiting the citizen's approval.",
    "REJECTED": "The citizen declined this request.",
    "EXPIRED": "The approval request has expired. Please create a new verification request.",
}
