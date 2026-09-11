from pathlib import Path


def test_tamper_demo_is_marker_guarded_and_has_full_lifecycle():
    source = Path("scripts/tamper_demo.py").read_text(encoding="utf-8")
    assert 'DEMO_MARKER = "TRUSTID_PHASE6_TAMPER_DEMO"' in source
    assert "guarded_rows(conn, state)" in source
    for action in ("create", "alter", "status", "restore", "cleanup"):
        assert f'"{action}"' in source
    assert "DELETE FROM receipts WHERE verification_id=%s" in source
    assert "DELETE FROM verifications WHERE id=%s" in source
    assert "intended_use=%s" in source
