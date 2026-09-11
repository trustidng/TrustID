from dataclasses import dataclass

from .contracts import ClaimCode, ResultCode, TTLClass


@dataclass(frozen=True)
class ClaimDefinition:
    label: str
    description: str
    operators: tuple[str, ...]
    ttl_class: TTLClass


CLAIM_CATALOG = {
    ClaimCode.AGE_COMPARE: ClaimDefinition(
        "Verify age requirement", "Confirm whether someone meets an age requirement without revealing their age.",
        (">", ">=", "<", "<=", "BETWEEN"), TTLClass.SHORT,
    ),
    ClaimCode.IDENTITY_STATUS: ClaimDefinition(
        "Verify identity record", "Confirm that the submitted NIN matches a valid identity record held by the national identity authority.",
        ("RECORD_CONFIRMED",), TTLClass.MEDIUM,
    ),
    ClaimCode.LICENCE_STATUS: ClaimDefinition(
        "Verify driving licence status", "Confirm whether a driving licence has the required status.",
        ("IS_VALID", "IS_EXPIRED", "IS_SUSPENDED"), TTLClass.SHORT,
    ),
    ClaimCode.LICENCE_CLASS: ClaimDefinition(
        "Verify driving licence class", "Confirm whether a driving licence belongs to a required class.",
        ("EQUALS", "IN_SET"), TTLClass.SHORT,
    ),
    ClaimCode.FULL_LEGAL_NAME: ClaimDefinition(
        "Request legal name", "Receive the legal name confirmed by the identity source.", (), TTLClass.CONSENT,
    ),
    ClaimCode.STATE_OF_ORIGIN: ClaimDefinition(
        "Request state of origin", "Request a state of origin with the citizen's approval.", (), TTLClass.CONSENT,
    ),
    ClaimCode.RESIDENTIAL_ADDRESS: ClaimDefinition(
        "Request residential address", "Request a residential address with the citizen's approval.", (), TTLClass.CONSENT,
    ),
    ClaimCode.NAME_MATCH: ClaimDefinition(
        "Verify name match", "Confirm whether the supplied name matches the selected identity source without revealing the registered name.",
        ("NAME_MATCH",), TTLClass.SHORT,
    ),
    ClaimCode.REGISTERED_RESIDENCE: ClaimDefinition(
        "Verify registered residence", "Confirm whether a supplied location matches the citizen's registered residence without revealing the complete address.",
        ("REGISTERED_RESIDENCE_MATCH",), TTLClass.SHORT,
    ),
}


RESULT_LABELS = {
    ResultCode.CONDITION_SATISFIED: "Requirement met",
    ResultCode.CONDITION_NOT_SATISFIED: "Requirement not met",
}


def condition_label(claim: ClaimCode, normalized: str) -> str:
    if claim == ClaimCode.AGE_COMPARE:
        if normalized.startswith("BETWEEN "):
            low, high = normalized.removeprefix("BETWEEN ").split(" AND ")
            if low == high:
                return f"Exactly {low} years old"
            return f"Between {low} and {high} years old"
        operator, age = normalized.split(" ", 1)
        labels = {">=": "At least", ">": "Older than", "<": "Younger than", "<=": "Not older than"}
        return f"{labels[operator]} {age} years old"
    status_labels = {
        "RECORD_CONFIRMED": "Valid identity record",
        # Retained for the display of historical results created before this
        # verification was simplified.
        "IS_VERIFIED": "Identity has been verified",
        "IS_ACTIVE": "Identity record is currently active",
        "IS_VALID": "Licence is valid",
        "IS_EXPIRED": "Licence is expired",
        "IS_SUSPENDED": "Licence is suspended",
        "NAME_MATCH": "Supplied name matches the identity record",
        "REGISTERED_RESIDENCE_MATCH": "Supplied location matches the registered residence",
    }
    if normalized in status_labels:
        return status_labels[normalized]
    if normalized.startswith("EQUALS "):
        return f"Licence class is {normalized.removeprefix('EQUALS ')}"
    if normalized.startswith("IN_SET "):
        return f"Licence class is one of {normalized.removeprefix('IN_SET ').replace(',', ', ')}"
    return "Requested requirement"
