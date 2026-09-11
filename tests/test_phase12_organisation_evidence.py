from pathlib import Path

import pytest

from app.evidence import validate_evidence


ROOT = Path(__file__).resolve().parents[1]


def test_phase12_schema_keeps_evidence_private_and_category_driven():
    migration = (ROOT / "db" / "migrations" / "032_organisation_application_evidence.sql").read_text(encoding="utf-8")
    assert "category_evidence_requirements" in migration
    assert "organisation_evidence_submissions" in migration
    assert "registration_reference_required" in migration


def test_application_is_multipart_and_changes_evidence_with_category():
    template = (ROOT / "app" / "templates" / "org_register.html").read_text(encoding="utf-8")
    assert 'enctype="multipart/form-data"' in template
    assert "data-category-panel" in template
    assert ".pdf,.png,.jpg,.jpeg" in template
    assert "Assurance level" not in template


def test_admin_can_define_evidence_for_custom_categories():
    template = (ROOT / "app" / "templates" / "admin_categories.html").read_text(encoding="utf-8")
    assert "Add evidence requirement" in template
    assert "One of the alternatives" in template
    assert "requires_document_number" in template


def test_evidence_validation_checks_magic_bytes_and_extension():
    pdf = validate_evidence("registration.pdf", b"%PDF-1.7\nexample")
    assert pdf.mime_type == "application/pdf"
    assert len(pdf.digest) == 64
    with pytest.raises(ValueError):
        validate_evidence("registration.jpg", b"%PDF-1.7\nexample")
    with pytest.raises(ValueError):
        validate_evidence("script.exe", b"MZ")


def test_evidence_files_are_not_mounted_as_static_content():
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert 'app.mount("/static"' in main
    assert "evidence_storage_path" in main
    assert 'app.mount("/evidence"' not in main
