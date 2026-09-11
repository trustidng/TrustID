from pathlib import Path


def test_admin_governance_migrations_are_forward_only_and_protected():
    sql = "\n".join(
        Path(path).read_text(encoding="utf-8").lower()
        for path in ("db/migrations/012_admin_governance.sql", "db/migrations/013_admin_role_audit.sql")
    )
    assert "drop table" not in sql and "truncate" not in sql and "delete from" not in sql
    for contract in (
        "super_admin", "admin_deactivated", "admin_password_reset",
        "admin_role_changed", "admin_verification_history_viewed",
    ):
        assert contract in sql


def test_admin_management_requires_confirmation_and_has_lifecycle_controls():
    template = Path("app/templates/admin_administrators.html").read_text(encoding="utf-8")
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert template.count('name="password_confirm"') == 2
    assert "Deactivate" in template and "Restore access" in template and "Reset password" in template
    assert "final_super" in source and "administrator_id == session[\"actor_id\"]" in source
    assert "ADMIN_PASSWORD_RESET" in source


def test_admin_history_template_and_query_are_privacy_safe():
    template = Path("app/templates/admin_verification_history.html").read_text(encoding="utf-8")
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "View verification history" in Path("app/templates/admin.html").read_text(encoding="utf-8")
    assert "ADMIN_VERIFICATION_HISTORY_VIEWED" in source
    assert "ORDER BY v.created_at DESC" in source
    forbidden = ("synthetic_nin", "licence_number", "phone_number", "date_of_birth", "full_name", "residential_address")
    assert not any(value in template for value in forbidden)
    assert "Internal failure reason" in template
    assert "internal_reason_code" in source
