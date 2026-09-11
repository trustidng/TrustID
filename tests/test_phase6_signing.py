import base64
from datetime import datetime, timezone
from io import BytesIO
import json

import pytest
from pathlib import Path
from PIL import Image
import zxingcpp

from app.signing import SIGNED_FIELDS, canonicalize, parse_canonical, qr_data_url, utc_text


def payload():
    return {field: {
        "verification_id": "VR-TEST", "issuer": "TrustID", "claim": "AGE_COMPARE",
        "condition": ">= 18", "result": "CONDITION_SATISFIED",
        "organisation_id": "ORG-TEST", "subject_reference": "SUB-TEST",
        "issued_at": "2026-08-31T10:00:00Z", "expires_at": "2026-09-01T10:00:00Z",
    }[field] for field in SIGNED_FIELDS}


def test_phase6_canonicalization_is_deterministic_and_exact():
    value = canonicalize(payload())
    assert value == json.dumps(payload(), sort_keys=True, separators=(",", ":"))
    assert parse_canonical(value) == payload()
    changed = payload()
    changed["purpose"] = "not signed"
    with pytest.raises(ValueError):
        canonicalize(changed)


def test_phase6_uses_rfc3339_utc_seconds():
    assert utc_text(datetime(2026, 8, 31, 10, 2, 3, 999, tzinfo=timezone.utc)) == "2026-08-31T10:02:03Z"


def test_qr_round_trip_contains_only_the_expected_url():
    url = "https://trustid.example/verify-result/" + "A" * 43
    encoded = qr_data_url(url)
    assert encoded.startswith("data:image/png;base64,")
    raw = base64.b64decode(encoded.split(",", 1)[1])
    decoded = zxingcpp.read_barcode(Image.open(BytesIO(raw)))
    assert raw.startswith(b"\x89PNG") and decoded and decoded.text == url
    assert b"synthetic_nin" not in raw


def test_phase6_migrations_and_atomic_integration_contract():
    sql = "\n".join(Path(path).read_text(encoding="utf-8").lower() for path in (
        "db/migrations/014_phase6_signing.sql", "db/migrations/015_organisation_public_reference_default.sql",
        "db/migrations/016_phase6_completion_hardening.sql"))
    assert "drop table" not in sql and "truncate" not in sql and "delete from" not in sql
    for value in ("signing_keys", "verification_token", "uq_receipt_verification", "result_authenticity_checked"):
        assert value in sql
    assert "authenticity_rate_limits" in sql
    source = Path("app/verifier.py").read_text(encoding="utf-8")
    assert source.index("sign_completed_result(conn, verification_id)") < source.index("conn.commit()", source.index("def submit_request"))


def test_public_receipt_template_has_only_privacy_safe_contract_fields():
    template = Path("app/templates/public_verification_result.html").read_text(encoding="utf-8")
    for expected in ("Authentic and current", "Authentic but expired", "Invalid or altered", "Result unavailable"):
        assert expected in template
    for forbidden in ("synthetic_nin", "licence_number", "phone_number", "date_of_birth", "full_name", "residential_address", "payload.signature"):
        assert forbidden not in template


def test_registration_assigns_public_organisation_reference():
    source = Path("app/main.py").read_text(encoding="utf-8")
    registration = source[source.index("def org_register("):source.index("def org_login_form")]
    assert "new_organisation_reference()" in registration


def test_application_lifespan_validates_signing_configuration():
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "validate_signing_configuration(conn)" in source
