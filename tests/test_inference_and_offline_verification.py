from pathlib import Path

from app import abuse


ROOT = Path(__file__).resolve().parents[1]


def test_general_inference_guard_supports_all_probeable_claim_families(monkeypatch):
    executed = []
    audits = []

    def fake_execute(_conn, sql, params=()):
        executed.append((" ".join(sql.split()), params))
        return 1

    def fake_fetch(_conn, sql, params=()):
        normalized = " ".join(sql.split())
        if "decision='ALLOWED'" in normalized:
            return {"count": 3}
        if "COUNT(*) count" in normalized:
            return {"count": 3}
        if "LAST_INSERT_ID" in normalized:
            return {"id": 91}
        return {"organisation_id": 7}

    monkeypatch.setattr(abuse, "execute", fake_execute)
    monkeypatch.setattr(abuse, "fetch_one", fake_fetch)
    monkeypatch.setattr(abuse, "audit", lambda *args: audits.append(args))

    for family in ("AGE", "NAME_MATCH", "RESIDENCE"):
        decision = abuse.reserve_inference_attempt(object(), 7, "SUB-TEST", family)
        assert not decision.allowed
        assert decision.reason_code == f"REPEATED_{family}_VERIFICATION"

    history_rows = [params for sql, params in executed if "INSERT INTO request_history" in sql]
    assert [params[2] for params in history_rows] == ["AGE", "NAME_MATCH", "RESIDENCE"]
    assert [entry[5]["claim_family"] for entry in audits] == ["AGE", "NAME_MATCH", "RESIDENCE"]


def test_non_age_conditions_are_fingerprinted_before_security_history():
    first = abuse.condition_fingerprint(("Ada", "Okafor", ""))
    same = abuse.condition_fingerprint(("  ada ", "OKAFOR", ""))
    residence = abuse.condition_fingerprint(("Lagos", "Ikeja"))
    assert first == same and first != residence
    assert len(first) == 20
    assert "ada" not in first and "lagos" not in residence


def test_verifier_applies_generic_guard_to_name_and_residence():
    source = (ROOT / "app" / "verifier.py").read_text(encoding="utf-8")
    assert 'ClaimCode.NAME_MATCH: "NAME_MATCH"' in source
    assert 'ClaimCode.REGISTERED_RESIDENCE: "RESIDENCE"' in source
    assert "reserve_inference_attempt" in source
    assert "condition_fingerprint(prepared.condition.allowed_values)" in source


def test_receipt_uses_live_authenticity_check_without_offline_download():
    receipt = (ROOT / "app" / "templates" / "receipt_detail.html").read_text(encoding="utf-8")
    public = (ROOT / "app" / "templates" / "public_verification_result.html").read_text(encoding="utf-8")
    assert "Verify this document" in receipt
    assert "receipt.verification_link" in receipt
    assert "Download offline verification file" not in receipt
    assert "Download offline verification file" not in public
    assert "current status" in receipt
    assert "This live page confirms" in public
