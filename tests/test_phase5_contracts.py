from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.verifier import ADMIN_FAILURE_REASONS, condition_from_form, prepare_request, validate_purpose
from app.verification import ClaimCode


@pytest.mark.parametrize("operator,low,high,normalized", [
    ("MINIMUM", "18", "", ">= 18"),
    ("MAXIMUM", "30", "", "<= 30"),
    ("EXACT", "21", "", "BETWEEN 21 AND 21"),
    ("RANGE", "18", "30", "BETWEEN 18 AND 30"),
])
def test_nontechnical_age_conditions_are_normalized(operator, low, high, normalized):
    prepared = prepare_request("AGE_COMPARE", "12345678901", operator, low, high, (), "Confirm customer eligibility")
    assert prepared.normalized_condition == normalized
    assert prepared.identifier not in prepared.requirement


@pytest.mark.parametrize("purpose", [
    "Use NIN 12345678901 for onboarding",
    "Call +2348031234567 about this request",
    "Review licence LIC-123456789 for delivery",
    "short",
])
def test_purpose_rejects_identifiers_and_unsafe_values(purpose):
    with pytest.raises(ValueError, match="without personal identifiers"):
        validate_purpose(purpose)


def test_exact_age_uses_inclusive_single_value_range():
    condition = condition_from_form(ClaimCode.AGE_COMPARE, "EXACT", "25")
    assert condition.operator == "BETWEEN"
    assert condition.threshold_low == condition.threshold_high == "25"
    prepared = prepare_request("AGE_COMPARE", "12345678901", "EXACT", "25", "", (), "Confirm customer eligibility")
    assert prepared.requirement == "Exactly 25 years old"


def test_phase5_migration_is_forward_only_and_idempotency_backed():
    sql = Path("db/migrations/011_phase5_verifier_portal.sql").read_text(encoding="utf-8").lower()
    assert "drop table" not in sql and "truncate" not in sql and "delete from" not in sql
    for required in ("verification_submissions", "submission_reference", "consent_request_id",
                     "uq_sms_consent_request", "delivery_status", "expires_at", "citizen_id"):
        assert required in sql


def test_phone_templates_expose_privacy_safe_inbox_contract():
    inbox = Path("app/templates/phone_messages.html").read_text(encoding="utf-8")
    detail = Path("app/templates/phone_message_detail.html").read_text(encoding="utf-8")
    assert "unread_count" in inbox and "ORDER BY" not in inbox
    assert "No personal information has been shared" in detail
    forbidden = ("synthetic_nin", "licence_number", "residential_address", "full_name")
    assert not any(value in (inbox + detail) for value in forbidden)


def test_verifier_templates_do_not_put_raw_identifier_in_urls():
    templates = "\n".join(path.read_text(encoding="utf-8") for path in Path("app/templates").glob("verification_*.html"))
    assert "/organisation/verifications/{{prepared.identifier}}" not in templates
    assert "subject_reference" in templates


def test_identity_record_verification_has_one_clear_outcome_to_request():
    details = Path("app/templates/verification_details.html").read_text(encoding="utf-8")
    assert 'value="RECORD_CONFIRMED"' in details
    assert "Status to verify" not in details
    assert "IS_VERIFIED" not in details and "IS_ACTIVE" not in details
    result = Path("app/templates/verification_result.html").read_text(encoding="utf-8")
    assert "Identity record not confirmed" not in result  # Outcome comes from the presentation model.
    assert "could not be confirmed against a valid identity record" in result
    assert set(ADMIN_FAILURE_REASONS) == {
        "NO_MATCHING_IDENTITY_RECORD", "IDENTITY_RECORD_INACTIVE", "IDENTITY_RECORD_REVOKED",
        "NO_MATCHING_LICENCE_RECORD",
    }
