from pathlib import Path

from app.resilience import SERVICE_CODES, SERVICE_MESSAGES

ROOT = Path(__file__).resolve().parents[1]


def test_phase10_services_and_messages_are_explicit():
    assert SERVICE_CODES == {"NATIONAL_ID", "DRIVING_LICENCE", "SMS", "USSD"}
    assert "temporarily unavailable" in SERVICE_MESSAGES["NATIONAL_ID"]
    assert "temporarily unavailable" in SERVICE_MESSAGES["DRIVING_LICENCE"]
    assert "could not be sent" in SERVICE_MESSAGES["SMS"]
    assert "temporarily unavailable" in SERVICE_MESSAGES["USSD"]


def test_phase10_migration_is_forward_only_and_auditable():
    sql = (ROOT / "db" / "migrations" / "022_phase10_service_resilience.sql").read_text(encoding="utf-8").lower()
    for required in ("service_status", "national_id", "driving_licence", "sms", "service_status_changed", "service_unavailable"):
        assert required in sql
    ussd_sql = (ROOT / "db" / "migrations" / "023_phase10_ussd_and_service_history.sql").read_text(encoding="utf-8").lower()
    assert "'ussd'" in ussd_sql
    assert "drop table" not in sql and "truncate" not in sql and "delete from" not in sql


def test_phase10_ui_has_service_health_and_safe_recovery_controls():
    security = (ROOT / "app" / "templates" / "admin_security.html").read_text(encoding="utf-8")
    history = (ROOT / "app" / "templates" / "admin_service_history.html").read_text(encoding="utf-8")
    phone = (ROOT / "app" / "templates" / "phone_ussd.html").read_text(encoding="utf-8")
    assert "Service status" in security and "Mark unavailable" in security and "Restore service" in security
    assert "Maintenance" in security and "Service interruption" in security and "Technical issue" in security
    assert "data-service-other" in security and "phase10.js" in security
    assert "View service history" in security and "/admin/security/services/history" in security
    assert "Service status history" in history and "Administrator" in history
    assert "Unavailable services fail safely" not in security
    assert "REVIEW NEXT" not in phone and ">CLOSE<" in phone


def test_phase10_photographs_obey_source_availability():
    source = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    route = source[source.index("def verification_identity_photograph"):source.index("def public_verification_result")]
    assert "is_available(conn, service_code)" in route
    assert "status_code=503" in route
