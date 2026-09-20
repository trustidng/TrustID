import base64
from hashlib import sha256
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app import abuse, signing


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


def test_offline_material_preserves_exact_signed_bytes(monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    canonical = signing.canonicalize({
        "verification_id": "VR-TEST", "issuer": "TrustID", "claim": "AGE_COMPARE",
        "condition": ">= 18", "result": "CONDITION_SATISFIED",
        "organisation_id": "ORG-TEST", "subject_reference": "SUB-TEST",
        "issued_at": "2026-09-20T09:00:00Z", "expires_at": "2026-09-21T09:00:00Z",
    })
    signature = private_key.sign(canonical.encode("utf-8"))
    receipt = {
        "signing_key_id": "KEY-1",
        "canonical_payload": canonical,
        "signature": base64.b64encode(signature).decode("ascii"),
    }
    monkeypatch.setattr(signing, "verify_receipt", lambda _conn, _token: (
        "CURRENT", {"verification_id": "VR-TEST"}, receipt))
    monkeypatch.setattr(signing, "fetch_one", lambda *_args, **_kwargs: {
        "key_id": "KEY-1", "algorithm": "Ed25519", "status": "ACTIVE",
        "public_key_b64": base64.b64encode(public_key).decode("ascii"),
    })

    state, material = signing.offline_receipt_material(object(), "A" * 43)
    assert state == "CURRENT"
    assert material["canonical_payload"] == canonical
    assert material["public_key_sha256"] == sha256(public_key).hexdigest()
    assert material["format"] == "trustid-offline-receipt-v1"
    Ed25519PublicKey.from_public_bytes(base64.b64decode(material["public_key_b64"])).verify(
        base64.b64decode(material["signature_b64"]), material["canonical_payload"].encode("utf-8"))


def test_offline_verifier_is_self_contained_and_honest_about_revocation():
    template = (ROOT / "app" / "templates" / "offline_receipt_verifier.html").read_text(encoding="utf-8")
    assert "crypto.subtle.verify" in template
    assert "crypto.subtle.digest" in template
    assert "canonical_payload" in template and "signature_b64" in template
    assert "cannot learn about a key or receipt revoked" in template
    for network_call in ("fetch(", "XMLHttpRequest", "<script src=", "http://", "https://"):
        assert network_call not in template


def test_offline_verifier_template_renders_as_one_self_contained_file():
    environment = Environment(
        loader=FileSystemLoader(ROOT / "app" / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    rendered = environment.get_template("offline_receipt_verifier.html").render(
        reference="VR-TEST",
        material={
            "format": "trustid-offline-receipt-v1", "algorithm": "Ed25519",
            "key_id": "KEY-1", "public_key_b64": "AA==",
            "public_key_sha256": "00", "canonical_payload": "{}", "signature_b64": "AA==",
        },
    )
    assert "TrustID offline verification — VR-TEST" in rendered
    assert 'const material={"algorithm": "Ed25519"' in rendered
    assert "{{" not in rendered and "{%" not in rendered


def test_existing_online_links_remain_and_offline_download_is_additive():
    receipt = (ROOT / "app" / "templates" / "receipt_detail.html").read_text(encoding="utf-8")
    public = (ROOT / "app" / "templates" / "public_verification_result.html").read_text(encoding="utf-8")
    assert "Verify this document" in receipt
    assert "receipt.verification_link" in receipt
    assert "Download offline verification file" in receipt
    assert "Download offline verification file" in public
