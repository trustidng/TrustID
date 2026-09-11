from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from app.verification.contracts import Condition, IdentityRecord, LicenceRecord, ResultCode
from app.verification.engine import VerificationEngine
from app.verification.errors import ConsentRequired
from app.verifier import CONSENT_CLAIMS, NIGERIAN_STATES, prepare_request


ROOT = Path(__file__).resolve().parents[1]


class IdentitySource:
    def __init__(self, record=None): self.record = record
    def get_identity(self, _identifier): return self.record


class LicenceSource:
    def __init__(self, record=None): self.record = record
    def get_licence(self, _identifier): return self.record


def identity():
    return IdentityRecord(7, date(2000, 1, 1), "VERIFIED", "ACTIVE", "Private Name",
                          "Kaduna", "12 Fictional Close, Lagos", "PHOTO-0001")


def licence():
    return LicenceRecord(8, "Private Driver", date(1990, 1, 1), "PHOTO-0002", "B",
                         date(2020, 1, 1), date(2030, 1, 1), "VALID")


def test_name_match_supports_nin_and_driving_licence_without_disclosing_name():
    national = replace(identity(), surname="Ibrahim", first_name="Abubakar", middle_name="Sadiq")
    driving = replace(licence(), holder_surname="Okafor", holder_first_name="Chiamaka", holder_middle_name="Ada")
    engine = VerificationEngine(IdentitySource(national), LicenceSource(driving))

    nin_result = engine.evaluate(
        "NAME_MATCH", "12345678901", Condition("NAME_MATCH", allowed_values=("IBRAHIM", "Abubakar", "Sadiq")))
    licence_result = engine.evaluate(
        "NAME_MATCH", "LIC-123456789", Condition("NAME_MATCH", allowed_values=("Okafor", "Chiamaka", "Wrong")))

    assert nin_result.result == ResultCode.CONDITION_SATISFIED
    assert nin_result.source_authority == "NATIONAL_ID"
    assert licence_result.result == ResultCode.CONDITION_NOT_SATISFIED
    assert licence_result.source_authority == "DRIVING_LICENCE"
    assert "Abubakar" not in repr(nin_result.verifier_safe())


def test_name_match_accepts_optional_middle_name_and_normalizes_diacritics():
    record = replace(identity(), surname="Adéyẹmí", first_name="Ọlá", middle_name="Tunde")
    engine = VerificationEngine(IdentitySource(record), LicenceSource())
    result = engine.evaluate(
        "NAME_MATCH", "12345678901", Condition("NAME_MATCH", allowed_values=("Adeyemi", "Ola", "")))
    assert result.result == ResultCode.CONDITION_SATISFIED


def test_registered_residence_is_a_protected_binary_verification():
    prepared = prepare_request(
        "REGISTERED_RESIDENCE", "12345678901", "", "", "", (),
        "Confirm service availability in the applicant's location",
        residence_state="lagos", residence_lga="Ikeja")
    assert prepared.condition.allowed_values == ("Lagos", "Ikeja")
    assert prepared.normalized_condition == "CONSENT_REQUIRED"
    assert prepared.claim in CONSENT_CLAIMS
    assert len(NIGERIAN_STATES) == 37
    with pytest.raises(ConsentRequired):
        VerificationEngine(IdentitySource(identity()), LicenceSource()).evaluate(
            "REGISTERED_RESIDENCE", "12345678901", Condition("REGISTERED_RESIDENCE_MATCH"))


def test_match_inputs_reject_numbers_in_names_and_unknown_states():
    with pytest.raises(ValueError):
        prepare_request("NAME_MATCH", "12345678901", "", "", "", (),
                        "Confirm the applicant identity for onboarding",
                        surname="Ibrahim2", first_name="Abubakar")
    with pytest.raises(ValueError):
        prepare_request("REGISTERED_RESIDENCE", "12345678901", "", "", "", (),
                        "Confirm the applicant location for eligibility",
                        residence_state="Unknown State")


def test_migration_and_forms_preserve_private_match_inputs():
    migration = (ROOT / "db" / "migrations" / "028_name_and_registered_residence_checks.sql").read_text(encoding="utf-8")
    details = (ROOT / "app" / "templates" / "verification_details.html").read_text(encoding="utf-8")
    review = (ROOT / "app" / "templates" / "verification_review.html").read_text(encoding="utf-8")
    signing = (ROOT / "app" / "signing.py").read_text(encoding="utf-8")
    for field in ("surname", "first_name", "middle_name", "state_of_residence", "lga_of_residence"):
        assert field in migration
    assert "consent_request_contexts" in migration
    assert "NAME_MATCH" in details and "REGISTERED_RESIDENCE" in details
    assert 'name="surname"' in review and 'name="residence_state"' in review
    assert "surname" not in signing and "state_of_residence" not in signing


def test_custom_categories_can_select_both_new_verifications():
    template = (ROOT / "app" / "templates" / "admin_categories.html").read_text(encoding="utf-8")
    routes = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    policy = (ROOT / "app" / "policy" / "engine.py").read_text(encoding="utf-8")
    assert "{% for claim in claims %}" in template
    assert 'name="claim_codes" value="{{claim.claim_code}}"' in template
    assert "SELECT claim_code FROM claim_definitions WHERE active=TRUE" in routes
    assert "category_claim_permissions" in policy and "d.active=TRUE" in policy
