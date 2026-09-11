from datetime import datetime
from pathlib import Path

from app.history import wat_time


def test_phase7_uses_clear_wat_time_without_changing_signed_utc_values():
    assert wat_time(datetime(2026, 9, 1, 13, 5)) == "1 Sep 2026, 2:05 PM WAT"
    assert wat_time(datetime(2026, 9, 1, 14, 5), stored_as_utc=False) == "1 Sep 2026, 2:05 PM WAT"


def test_phase7_migration_is_forward_only_and_scoped_for_history():
    sql = Path("db/migrations/017_phase7_receipt_history.sql").read_text(encoding="utf-8").lower()
    assert "idx_receipts_org_issued" in sql
    assert "organisation_id, issued_at" in sql
    assert not any(value in sql for value in ("drop table", "truncate", "delete from"))


def test_phase7_history_and_receipt_ui_contract():
    history = Path("app/templates/verification_history.html").read_text(encoding="utf-8")
    receipt = Path("app/templates/receipt_detail.html").read_text(encoding="utf-8")
    result = Path("app/templates/verification_result.html").read_text(encoding="utf-8")
    public = Path("app/templates/public_verification_result.html").read_text(encoding="utf-8")
    assert "All requests" in history and "Verification receipts" in history
    assert "VR-… or SUB-…" in history and "Apply filters" in history
    assert "Print or save receipt" in receipt and "<dt>Purpose</dt>" in receipt
    assert "not part of the digitally signed result" not in receipt
    assert "View verification receipt" in result and "verification_qr" not in result
    assert result.index("summary-card") < result.index("Verification receipt ready")
    assert "Identity photograph" in result
    assert 'class="complete result-complete"' in result
    assert "<i>4</i>Result" not in result
    assert "A digital signature proves" not in public
    assert "Back to receipt" in public
    assert "?return_to=/organisation/receipts/{{receipt.transaction_id}}" in receipt


def test_phase7_templates_do_not_name_protected_identity_fields():
    rendered_sources = "\n".join(Path(path).read_text(encoding="utf-8") for path in (
        "app/templates/verification_history.html", "app/templates/receipt_detail.html"))
    forbidden = ("synthetic_nin", "licence_number", "date_of_birth", "full_name",
                 "residential_address", "registered_phone", "canonical_payload", "receipt.signature")
    assert not any(value in rendered_sources for value in forbidden)


def test_receipt_detail_lookup_is_organisation_scoped():
    source = Path("app/history.py").read_text(encoding="utf-8")
    detail = source[source.index("def organisation_receipt("):source.index("def receipt_count(")]
    assert "r.organisation_id=%s" in detail
    assert "verification_token" not in Path("app/templates/verification_history.html").read_text(encoding="utf-8")
