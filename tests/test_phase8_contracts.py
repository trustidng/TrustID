from pathlib import Path

from app.consent import decrypt_value, encrypt_value


ROOT = Path(__file__).resolve().parents[1]


def test_disclosure_encryption_is_authenticated_and_not_plaintext():
    ciphertext, nonce = encrypt_value("14 College Road, Kano", 11, 12, 13, "RESIDENTIAL_ADDRESS")
    row = {"ciphertext": ciphertext, "nonce": nonce, "verification_id": 11,
           "organisation_id": 12, "citizen_id": 13, "claim_code": "RESIDENTIAL_ADDRESS"}
    assert b"College Road" not in ciphertext
    assert decrypt_value(row) == "14 College Road, Kano"


def test_phase8_surfaces_do_not_put_values_in_public_or_history_templates():
    for name in ("verification_history.html", "receipt_detail.html", "public_verification_result.html", "admin_verification_history.html"):
        text = (ROOT / "app" / "templates" / name).read_text(encoding="utf-8")
        assert "disclosure.value" not in text
    result = (ROOT / "app" / "templates" / "verification_result.html").read_text(encoding="utf-8")
    assert "disclosure.value" in result


def test_phase8_contract_keeps_sms_and_lifecycle_small():
    migration = (ROOT / "db" / "migrations" / "020_phase8_consent_disclosure.sql").read_text(encoding="utf-8")
    assert "CONSENT_APPROVAL_CODE" in migration
    assert "controlled_disclosures" in migration
    assert "WITHDRAWN" not in migration
    document = (ROOT / "docs" / "Phase8_Readiness.md").read_text(encoding="utf-8")
    assert "routine decision, expiry, receipt, login, USSD, or reminder" in document


def test_phase8_ui_is_card_based_mobile_ready_and_professional():
    dashboard = (ROOT / "app" / "templates" / "citizen_dashboard.html").read_text(encoding="utf-8")
    detail = (ROOT / "app" / "templates" / "citizen_request_detail.html").read_text(encoding="utf-8")
    ussd = (ROOT / "app" / "templates" / "phone_ussd.html").read_text(encoding="utf-8")
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert "Needs your attention" in dashboard and "Previous requests" in dashboard
    assert "Requesting organization" in detail and "Information requested" in detail and "Purpose" in detail
    assert "step=='consent'" in ussd and "@media(max-width:650px)" in base
    assert "REVIEW NEXT" not in ussd and ">CLOSE<" in ussd
    catalog = (ROOT / "app" / "verification" / "catalog.py").read_text(encoding="utf-8")
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    combined = (dashboard + detail + ussd + catalog + main).lower()
    assert "strong consent" not in combined and "otp challenge" not in combined and "ciphertext" not in combined
