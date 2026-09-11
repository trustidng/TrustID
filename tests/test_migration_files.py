from pathlib import Path


def test_phase2_migration_is_non_destructive():
    sql = Path("db/migrations/002_phase2_auth.sql").read_text(encoding="utf-8").upper()
    assert "DROP TABLE" not in sql
    assert "TRUNCATE" not in sql
    assert "DELETE FROM" not in sql


def test_phase2_migration_contains_required_security_state():
    sql = "\n".join(path.read_text(encoding="utf-8") for path in Path("db/migrations").glob("*.sql")).lower()
    for required in ("auth_sessions", "otp_challenges", "locked_until", "failed_login_attempts", "failed_pin_attempts"):
        assert required in sql


def test_sms_delivery_does_not_store_plaintext_code():
    sql = Path("db/migrations/003_phase2_refinement.sql").read_text(encoding="utf-8").lower()
    assert "sms_deliveries" in sql
    assert "code_nonce" in sql
    assert "otp_plaintext" not in sql
    assert "activation_code varchar" not in sql


def test_phone_session_uses_hashed_token_and_shared_number_context():
    sql = Path("db/migrations/004_trustid_phone.sql").read_text(encoding="utf-8").lower()
    assert "phone_sessions" in sql
    assert "token_hash" in sql
    assert "phone_number" in sql
    assert "raw_token" not in sql


def test_messages_are_bound_to_a_phone_session():
    sql = Path("db/migrations/005_phone_message_retention.sql").read_text(encoding="utf-8").lower()
    assert "phone_session_id" in sql
    assert "on delete set null" in sql
    assert "drop table" not in sql


def test_identity_attribute_migration_preserves_states_and_backfills_addresses():
    sql = Path("db/migrations/007_identity_origin_and_address.sql").read_text(encoding="utf-8").lower()
    assert "change column state_of_residence state_of_origin" in sql
    assert "add column residential_address" in sql
    assert "update citizens" in sql
    assert "where residential_address is null" in sql
    assert "drop table" not in sql
    assert "delete from" not in sql


def test_residential_address_location_is_independent_of_origin():
    sql = Path("db/migrations/008_independent_residential_addresses.sql").read_text(encoding="utf-8").lower()
    assert "update citizens" in sql
    assert "residential_address" in sql
    assert "state_of_origin" not in sql
    assert "fct - abuja" in sql and "lagos" in sql and "yobe" in sql
    assert "drop table" not in sql and "delete from" not in sql


def test_phase4_migration_normalizes_categories_and_fixes_privacy_modes():
    sql = Path("db/migrations/009_dynamic_categories_and_policy.sql").read_text(encoding="utf-8").lower()
    for required in ("organisation_categories", "claim_definitions", "category_claim_permissions", "category_id"):
        assert required in sql
    assert "'residential_address','requestresidentialaddress','request','strong_consent'" in sql.replace(" ", "").replace("\n", "")
    assert "change column category legacy_category" in sql
    assert "drop table" not in sql and "truncate" not in sql and "delete from" not in sql


def test_organisation_reinstatement_is_auditable():
    sql = Path("db/migrations/010_organisation_reinstatement.sql").read_text(encoding="utf-8").lower()
    assert "org_reinstated" in sql
    assert "drop table" not in sql and "delete from" not in sql


def test_unconfirmed_identity_results_do_not_require_a_source_record():
    sql = Path("db/migrations/026_unconfirmed_identity_results.sql").read_text(encoding="utf-8").lower()
    assert "modify column source_record_id bigint null" in sql
    assert "drop table" not in sql and "delete from" not in sql


def test_admin_identity_failure_reason_is_privacy_safe():
    sql = Path("db/migrations/027_admin_identity_failure_reasons.sql").read_text(encoding="utf-8").lower()
    assert "internal_reason_code" in sql
    assert "synthetic_nin" not in sql and "drop table" not in sql and "delete from" not in sql
