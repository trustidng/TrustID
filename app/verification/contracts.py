from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum


class ClaimCode(StrEnum):
    AGE_COMPARE = "AGE_COMPARE"
    IDENTITY_STATUS = "IDENTITY_STATUS"
    LICENCE_STATUS = "LICENCE_STATUS"
    LICENCE_CLASS = "LICENCE_CLASS"
    FULL_LEGAL_NAME = "FULL_LEGAL_NAME"
    STATE_OF_ORIGIN = "STATE_OF_ORIGIN"
    RESIDENTIAL_ADDRESS = "RESIDENTIAL_ADDRESS"
    NAME_MATCH = "NAME_MATCH"
    REGISTERED_RESIDENCE = "REGISTERED_RESIDENCE"


class ResultCode(StrEnum):
    CONDITION_SATISFIED = "CONDITION_SATISFIED"
    CONDITION_NOT_SATISFIED = "CONDITION_NOT_SATISFIED"


class TTLClass(StrEnum):
    SHORT = "SHORT"
    MEDIUM = "MEDIUM"
    CONSENT = "CONSENT"


@dataclass(frozen=True)
class Condition:
    operator: str
    threshold_low: int | str | None = None
    threshold_high: int | None = None
    allowed_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class IdentityRecord:
    citizen_id: int
    date_of_birth: date
    identity_status: str
    record_status: str
    full_name: str
    state_of_origin: str
    residential_address: str
    photograph_reference: str
    surname: str = ""
    first_name: str = ""
    middle_name: str | None = None
    state_of_residence: str = ""
    lga_of_residence: str = ""
    gender: str = ""


@dataclass(frozen=True)
class LicenceRecord:
    licence_record_id: int
    holder_full_name: str
    holder_date_of_birth: date
    photograph_reference: str
    licence_class: str
    issue_date: date
    expiry_date: date
    licence_status: str
    holder_surname: str = ""
    holder_first_name: str = ""
    holder_middle_name: str | None = None
    holder_gender: str = ""


@dataclass(frozen=True)
class EvaluationResult:
    claim_code: ClaimCode
    normalized_condition: str
    result: ResultCode
    evaluated_at: datetime
    ttl_class: TTLClass
    source_authority: str
    source_record_id: int
    photograph_reference: str
    citizen_id: int | None = None

    def verifier_safe(self) -> dict[str, str]:
        """Return only fields safe to pass beyond the internal engine boundary."""
        return {
            "claim_code": self.claim_code.value,
            "condition": self.normalized_condition,
            "result": self.result.value,
            "evaluated_at": self.evaluated_at.isoformat(),
            "ttl_class": self.ttl_class.value,
        }

    def user_facing(self) -> dict[str, str]:
        from .catalog import CLAIM_CATALOG, RESULT_LABELS, condition_label

        return {
            "check": CLAIM_CATALOG[self.claim_code].label,
            "requirement": condition_label(self.claim_code, self.normalized_condition),
            "outcome": RESULT_LABELS[self.result],
        }
