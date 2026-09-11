from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_review_schema_supports_more_information_and_document_assessment():
    sql = (ROOT / "db" / "migrations" / "033_organisation_application_review.sql").read_text(encoding="utf-8")
    assert "NEEDS_INFORMATION" in sql
    assert "review_status" in sql
    assert "organisation_application_reviews" in sql
    assert "MORE_INFORMATION_REQUESTED" in sql


def test_admin_review_is_dedicated_and_evidence_is_protected():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert '/admin/organisations/{organisation_id}/review' in source
    assert '/admin/organisations/{organisation_id}/evidence/{submission_id}' in source
    assert "require_actor(conn, request, \"ADMIN\")" in source
    assert "required_ok" in source
    assert "Content-Disposition" in source


def test_review_page_contains_complete_decision_workflow():
    page = (ROOT / "app" / "templates" / "admin_application_review.html").read_text(encoding="utf-8")
    for text in ("Review documents", "Accept evidence", "Reject evidence", "Approve organization",
                 "Request more information", "Reject application", "Review history", "Permitted verifications"):
        assert text in page


def test_organization_can_respond_to_more_information_request():
    dashboard = (ROOT / "app" / "templates" / "org_dashboard.html").read_text(encoding="utf-8")
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "More information is needed" in dashboard
    assert "Submit updated evidence" in dashboard
    assert "/organisation/application/evidence" in source


def test_directory_retains_every_application_and_uses_pagination():
    template = (ROOT / "app" / "templates" / "admin.html").read_text(encoding="utf-8")
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "Application &amp; documents" in template
    assert "page_number" in template
    assert "LIMIT %s OFFSET %s" in source
    assert "per_page = 10" in source


def test_category_management_uses_searchable_collapsed_sections():
    script = (ROOT / "app" / "static" / "validation.js").read_text(encoding="utf-8")
    assert "category-accordion" in script
    assert "Find a category" in script
