from pathlib import Path

from app.abuse import AGE_ATTEMPT_LIMIT, AGE_WINDOW, BLOCK_MESSAGE

ROOT = Path(__file__).resolve().parents[1]


def test_phase9_rule_is_clear_and_professional():
    assert AGE_ATTEMPT_LIMIT == 3
    assert AGE_WINDOW.total_seconds() == 30 * 60
    assert "too many similar requests" in BLOCK_MESSAGE
    assert "3" not in BLOCK_MESSAGE and "30" not in BLOCK_MESSAGE


def test_phase9_migration_removes_answers_and_adds_atomic_guard():
    sql = (ROOT / "db" / "migrations" / "021_phase9_abuse_controls.sql").read_text(encoding="utf-8").lower()
    assert "drop column result" in sql
    assert "inference_guards" in sql and "primary key (organisation_id,subject_reference,claim_family)" in sql
    assert "denial_message" in sql and "admin_security_viewed" in sql
    assert "drop table" not in sql and "truncate" not in sql and "delete from" not in sql


def test_phase9_ui_is_privacy_safe_and_has_security_workflow():
    listing = (ROOT / "app" / "templates" / "admin_security.html").read_text(encoding="utf-8")
    detail = (ROOT / "app" / "templates" / "admin_security_incident.html").read_text(encoding="utf-8")
    assert "Requests blocked" in listing and "Organizations flagged" in listing
    assert "Apply filters" in listing and "View details" in listing
    assert "Privacy-safe record" not in detail and "Manage organization" in detail
    combined = (listing + detail).lower()
    for forbidden in ("synthetic_nin", "date_of_birth", "full_name", "pin_hash", "verification answer:"):
        assert forbidden not in combined
