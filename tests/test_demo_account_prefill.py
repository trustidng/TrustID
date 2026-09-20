from contextlib import contextmanager
from pathlib import Path

from app import main


ROOT = Path(__file__).resolve().parents[1]


@contextmanager
def fake_connection():
    yield object()


def test_admin_demo_link_prefills_only_an_active_selected_account(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "connection", fake_connection)
    monkeypatch.setattr(main, "_demo_administrator", lambda _conn: {
        "username": "admin", "email": "admin@trustid.test", "full_name": "Demo Admin",
    })
    monkeypatch.setattr(main, "page", lambda _request, _template, **context: captured.update(context) or context)

    main.admin_login_form(object(), demo=1)

    assert captured["identifier_value"] == "admin"
    assert captured["password_value"] == main.DEMO_PASSWORD
    assert captured["demo_prefill"] is True


def test_organization_demo_link_uses_public_reference_not_credentials(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "connection", fake_connection)
    monkeypatch.setattr(main, "_demo_organization", lambda _conn, reference: {
        "public_reference": reference, "email": "school@demo.test",
    } if reference == "ORG-ABC123" else None)
    monkeypatch.setattr(main, "page", lambda _request, _template, **context: captured.update(context) or context)

    main.org_login_form(object(), demo="org-abc123")

    assert captured["identifier_value"] == "school@demo.test"
    assert captured["password_value"] == main.DEMO_PASSWORD
    assert captured["demo_prefill"] is True


def test_invalid_demo_reference_is_rejected_before_database_lookup(monkeypatch):
    monkeypatch.setattr(main, "fetch_one", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("invalid references must not reach the database")))
    assert main._demo_organization(object(), "../../another-account") is None
    assert main._demo_organization(object(), "ORG-ABC?password=x") is None


def test_demo_buttons_never_put_passwords_or_emails_in_query_string():
    template = (ROOT / "app" / "templates" / "demo_credentials.html").read_text(encoding="utf-8")
    assert "/admin/login?demo=1" in template
    assert "/organisation/login?demo={{item.public_reference}}" in template
    assert "?password=" not in template and "?email=" not in template
    assert template.count("Use this demo account") == 2


def test_login_form_supports_explicit_demo_prefill_notice():
    template = (ROOT / "app" / "templates" / "login.html").read_text(encoding="utf-8")
    assert "Demo account ready" in template
    assert 'value="{{identifier_value or \'\'}}"' in template
    assert 'value="{{password_value or \'\'}}"' in template
