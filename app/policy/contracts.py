from dataclasses import dataclass
from enum import StrEnum


class PolicyDecisionCode(StrEnum):
    ALLOW_INSTANT = "ALLOW_INSTANT"
    REQUIRE_CONSENT = "REQUIRE_CONSENT"
    REQUIRE_STRONG_CONSENT = "REQUIRE_STRONG_CONSENT"
    DENY_ORG_NOT_APPROVED = "DENY_ORG_NOT_APPROVED"
    DENY_UNAUTHORIZED_CLAIM = "DENY_UNAUTHORIZED_CLAIM"
    DENY_RATE_LIMIT = "DENY_RATE_LIMIT"
    DENY_INFERENCE_RISK = "DENY_INFERENCE_RISK"


@dataclass(frozen=True)
class PolicyDecision:
    code: PolicyDecisionCode
    reason_code: str
    message: str

    @property
    def permitted(self) -> bool:
        return self.code in {
            PolicyDecisionCode.ALLOW_INSTANT,
            PolicyDecisionCode.REQUIRE_CONSENT,
            PolicyDecisionCode.REQUIRE_STRONG_CONSENT,
        }

    @property
    def requires_approval(self) -> bool:
        return self.code in {
            PolicyDecisionCode.REQUIRE_CONSENT,
            PolicyDecisionCode.REQUIRE_STRONG_CONSENT,
        }
