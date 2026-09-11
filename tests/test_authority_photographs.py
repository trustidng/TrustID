from pathlib import Path

import pytest

from app.photographs import portrait_png
from app.verification.pseudonyms import subject_reference, unconfirmed_subject_reference


def test_portrait_sheet_is_protected_and_cells_render_as_jpeg():
    asset = Path("trusted_source_assets/identity_photographs/synthetic_portraits_4x4.png")
    assert asset.is_file() and "app/static" not in str(asset)
    for reference in ("PHOTO-0001", "PHOTO-0008", "PHOTO-0016"):
        image = portrait_png(reference)
        assert image.startswith(b"\xff\xd8") and len(image) > 10_000
    with pytest.raises(ValueError):
        portrait_png("PHOTO-0017")


def test_authority_pseudonyms_are_domain_separated_without_changing_national_contract():
    secret = "authority-separated-test-secret-at-least-32-chars"
    national = subject_reference(4, 9, secret)
    assert national == subject_reference(4, 9, secret, authority="NATIONAL_ID")
    assert national != subject_reference(4, 9, secret, authority="DRIVING_LICENCE")
    unmatched = unconfirmed_subject_reference(4, "12345678901", secret)
    assert unmatched == unconfirmed_subject_reference(4, "12345678901", secret)
    assert unmatched != unconfirmed_subject_reference(5, "12345678901", secret)
    assert "12345678901" not in unmatched


def test_independent_authority_migration_copies_then_removes_the_old_link():
    sql = Path("db/migrations/018_independent_authorities_and_photographs.sql").read_text(encoding="utf-8").lower()
    assert sql.index("set l.holder_full_name") < sql.index("drop column citizen_reference")
    for required in ("licence_record_id", "holder_full_name", "holder_date_of_birth",
                     "holder_photograph_reference", "subject_authority", "source_record_id",
                     "identity_photo_rate_limits", "identity_photo_viewed"):
        assert required in sql
    assert "delete from" not in sql and "truncate" not in sql


def test_photo_is_excluded_from_receipts_history_and_public_pages():
    private_result = Path("app/templates/verification_result.html").read_text(encoding="utf-8")
    other_surfaces = "\n".join(Path(path).read_text(encoding="utf-8") for path in (
        "app/templates/verification_history.html", "app/templates/receipt_detail.html",
        "app/templates/public_verification_result.html"))
    assert "photograph_url" in private_result
    assert "identity-photograph" not in other_surfaces and "photograph_reference" not in other_surfaces


def test_photo_endpoint_requires_a_matched_identity_record():
    source = Path("app/main.py").read_text(encoding="utf-8")
    route = source[source.index("def verification_identity_photograph"):source.index("def public_verification_result")]
    assert "CONDITION_NOT_SATISFIED" in route and "source_record_id" in route
    photo_helper = Path("app/photographs.py").read_text(encoding="utf-8")
    assert 'not row["source_record_id"]' in photo_helper


def test_organisation_receipt_hides_signing_implementation_details():
    receipt = Path("app/templates/receipt_detail.html").read_text(encoding="utf-8")
    admin = Path("app/templates/admin_verification_history.html").read_text(encoding="utf-8")
    assert "Technical details" not in receipt and "signing_key_id" not in receipt
    assert "Signing details" in admin and "signing_key_id" in admin
