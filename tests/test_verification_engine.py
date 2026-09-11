from datetime import date

import pytest
import mysql.connector

from app.verification.adapters import IdentitySourceAdapter
from app.verification.contracts import ClaimCode, Condition, IdentityRecord, LicenceRecord, ResultCode, TTLClass
from app.verification.engine import VerificationEngine, age_on
from app.verification.errors import ConsentRequired, InvalidVerificationRequest, SubjectNotFound, TrustedSourceUnavailable
from app.verification.pseudonyms import subject_reference


AS_OF = date(2026, 8, 31)


class IdentitySource:
    def __init__(self, record=None):
        self.record = record

    def get_identity(self, identifier):
        if not self.record:
            raise SubjectNotFound()
        return self.record


class LicenceSource:
    def __init__(self, record=None):
        self.record = record

    def get_licence(self, identifier):
        if not self.record:
            raise SubjectNotFound()
        return self.record


def identity(age=18, status="VERIFIED"):
    return IdentityRecord(7, date(AS_OF.year - age, AS_OF.month, AS_OF.day), status, "ACTIVE",
                          "Private Name", "Kaduna", "12 Fictional Close, Kaduna", "PHOTO-0001")


def licence(status="VALID", expiry=date(2027, 8, 31), licence_class="B"):
    return LicenceRecord(7, "Private Driver", date(1990, 1, 1), "PHOTO-0002",
                         licence_class, date(2020, 1, 1), expiry, status)


def engine(identity_record=None, licence_record=None):
    return VerificationEngine(IdentitySource(identity_record), LicenceSource(licence_record))


@pytest.mark.parametrize("operator,threshold,expected", [
    (">=", 18, True), (">", 18, False), ("<", 19, True), ("<=", 18, True),
    (">=", 21, False), ("<", 65, True),
])
def test_flexible_age_comparisons(operator, threshold, expected):
    result = engine(identity()).evaluate("AGE_COMPARE", "raw-id", Condition(operator, threshold), as_of=AS_OF)
    assert (result.result == ResultCode.CONDITION_SATISFIED) is expected


@pytest.mark.parametrize("age,operator,expected", [
    (18, ">=", True), (18, ">", False), (30, "<=", True), (30, "<", False),
])
def test_required_age_boundaries(age, operator, expected):
    result = engine(identity(age)).evaluate(ClaimCode.AGE_COMPARE, "raw-id", Condition(operator, age), as_of=AS_OF)
    assert (result.result == ResultCode.CONDITION_SATISFIED) is expected


@pytest.mark.parametrize("age,expected", [(18, True), (30, True), (17, False), (31, False)])
def test_between_is_inclusive(age, expected):
    result = engine(identity(age)).evaluate("AGE_COMPARE", "raw-id", Condition("BETWEEN", 18, 30), as_of=AS_OF)
    assert result.normalized_condition == "BETWEEN 18 AND 30"
    assert (result.result == ResultCode.CONDITION_SATISFIED) is expected


def test_age_calculation_handles_birthday_and_leap_day():
    assert age_on(date(2008, 9, 1), AS_OF) == 17
    assert age_on(date(2008, 8, 31), AS_OF) == 18
    assert age_on(date(2004, 2, 29), date(2025, 2, 28)) == 20
    assert age_on(date(2004, 2, 29), date(2025, 3, 1)) == 21


@pytest.mark.parametrize("condition", [
    Condition("BETWEEN", 30, 18), Condition(">=", -1), Condition("<", 121),
    Condition("BETWEEN", 18, None), Condition("EQUALS", 18), Condition(">=", "18.5"),
])
def test_invalid_age_conditions_are_rejected(condition):
    with pytest.raises(InvalidVerificationRequest):
        engine(identity()).evaluate("AGE_COMPARE", "raw-id", condition, as_of=AS_OF)


@pytest.mark.parametrize("status,expected", [
    ("VERIFIED", True), ("ACTIVE", True), ("REVOKED", False),
])
def test_identity_record_confirmation(status, expected):
    result = engine(identity(status=status)).evaluate(
        "IDENTITY_STATUS", "raw-id", Condition("RECORD_CONFIRMED"), as_of=AS_OF)
    assert result.ttl_class == TTLClass.MEDIUM
    assert (result.result == ResultCode.CONDITION_SATISFIED) is expected


@pytest.mark.parametrize("operator", ["IS_VERIFIED", "IS_ACTIVE", ""])
def test_old_identity_status_choices_are_not_accepted_for_new_requests(operator):
    with pytest.raises(InvalidVerificationRequest):
        engine(identity()).evaluate("IDENTITY_STATUS", "raw-id", Condition(operator), as_of=AS_OF)


@pytest.mark.parametrize("record,operator,expected", [
    (licence(), "IS_VALID", True),
    (licence(expiry=date(2026, 8, 30)), "IS_EXPIRED", True),
    (licence(status="EXPIRED", expiry=date(2027, 1, 1)), "IS_EXPIRED", True),
    (licence(status="SUSPENDED"), "IS_SUSPENDED", True),
    (licence(status="SUSPENDED"), "IS_VALID", False),
])
def test_licence_status_uses_authority_status_and_dates(record, operator, expected):
    result = engine(licence_record=record).evaluate("LICENCE_STATUS", "raw-licence", Condition(operator), as_of=AS_OF)
    assert (result.result == ResultCode.CONDITION_SATISFIED) is expected


def test_licence_class_equals_and_in_set():
    verifier = engine(licence_record=licence(licence_class="B"))
    equals = verifier.evaluate("LICENCE_CLASS", "raw-licence", Condition("EQUALS", "b"), as_of=AS_OF)
    in_set = verifier.evaluate("LICENCE_CLASS", "raw-licence", Condition("IN_SET", allowed_values=("C", "B", "B")), as_of=AS_OF)
    assert equals.result == in_set.result == ResultCode.CONDITION_SATISFIED
    assert in_set.normalized_condition == "IN_SET B,C"
    assert equals.ttl_class == TTLClass.SHORT
    assert equals.source_authority == "DRIVING_LICENCE" and equals.citizen_id is None


def test_direct_attributes_cannot_be_evaluated_without_consent():
    for claim in ("FULL_LEGAL_NAME", "STATE_OF_ORIGIN", "RESIDENTIAL_ADDRESS", "REGISTERED_RESIDENCE"):
        with pytest.raises(ConsentRequired):
            engine().evaluate(claim, "raw-id", Condition(""), as_of=AS_OF)


def test_verifier_safe_result_excludes_internal_and_private_fields():
    raw_identifier = "12345678901"
    result = engine(identity()).evaluate("AGE_COMPARE", raw_identifier, Condition(">=", 18), as_of=AS_OF)
    safe = result.verifier_safe()
    serialized = repr(safe)
    assert result.citizen_id == 7
    assert "citizen_id" not in safe
    for forbidden in (raw_identifier, "date_of_birth", "full_name", "Private Name", "state_of_origin",
                      "Kaduna", "residential_address", "Fictional Close", "exact_age"):
        assert forbidden not in serialized


def test_result_has_plain_language_for_non_technical_users():
    result = engine(identity()).evaluate("AGE_COMPARE", "raw-id", Condition("BETWEEN", 21, 40), as_of=AS_OF)
    assert result.user_facing() == {
        "check": "Verify age requirement",
        "requirement": "Between 21 and 40 years old",
        "outcome": "Requirement not met",
    }


def test_subject_reference_is_deterministic_and_organisation_scoped():
    secret = "a-secure-dedicated-pseudonym-secret-12345"
    first = subject_reference(10, 7, secret)
    assert first == subject_reference(10, 7, secret)
    assert first != subject_reference(11, 7, secret)
    assert first.startswith("SUB-") and len(first) == 14
    assert first != subject_reference(10, 7, secret, authority="DRIVING_LICENCE")


def test_safe_errors_do_not_repeat_identifiers_or_source_records():
    raw_identifier = "sensitive-raw-identifier"
    with pytest.raises(SubjectNotFound) as captured:
        engine().evaluate("AGE_COMPARE", raw_identifier, Condition(">=", 18), as_of=AS_OF)
    assert raw_identifier not in str(captured.value)
    assert "No eligible record" in captured.value.safe_message


def test_adapter_converts_database_failure_to_safe_source_error():
    class FailedConnection:
        def __enter__(self):
            raise mysql.connector.Error("database details that must remain internal")

        def __exit__(self, *args):
            return False

    with pytest.raises(TrustedSourceUnavailable) as captured:
        IdentitySourceAdapter(lambda: FailedConnection()).get_identity("raw-id")
    assert "database details" not in str(captured.value)
    assert captured.value.status_code == 503
