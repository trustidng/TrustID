from pathlib import Path

from db.prepare_phase11_demo_data import ADMINISTRATORS, ORGANISATIONS

ROOT = Path(__file__).resolve().parents[1]


def test_phase11_demo_accounts_cover_requested_scope():
    assert len(ADMINISTRATORS) == 3
    assert len(ORGANISATIONS) == 20
    assert {row[3] for row in ORGANISATIONS} == {
        "RETAIL", "FINANCIAL", "PROGRAMME_OPERATOR", "GOVERNMENT", "TRANSPORT_LOGISTICS",
    }
    assert all(row[1].endswith(".test") for row in ORGANISATIONS)


def test_password_and_pin_guidance_is_consistent():
    templates = ROOT / "app" / "templates"
    assert "Password must contain at least 10 characters." in (templates / "org_register.html").read_text(encoding="utf-8")
    assert "Password must contain at least 10 characters." in (templates / "admin_change_password.html").read_text(encoding="utf-8")
    assert "Use 4–6 numbers only." in (templates / "citizen_activate.html").read_text(encoding="utf-8")
    assert (ROOT / "app" / "static" / "validation.js").exists()


def test_ussd_code_is_updated_everywhere_user_facing():
    paths = [ROOT / "app", ROOT / "scripts", ROOT / "docs", ROOT / "README.md"]
    files = []
    for path in paths:
        files.extend(path.rglob("*") if path.is_dir() else [path])
    text = "\n".join(p.read_text(encoding="utf-8", errors="ignore") for p in files if p.is_file() and "__pycache__" not in p.parts)
    assert "*123#" not in text
    assert "*7305#" in text


def test_admin_organization_directory_is_responsive_and_filterable():
    template = (ROOT / "app" / "templates" / "admin.html").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    security = (ROOT / "app" / "templates" / "admin_security.html").read_text(encoding="utf-8")
    for field in ('name="q"', 'name="status_filter"', 'name="category"',
                  'name="date_from"', 'name="date_to"', 'name="sort"'):
        assert field in template
    assert "organization-table" in template and "View verification history" in template
    assert "#suspend-" in template and "Reason for suspension" in template
    assert "organization-table-shell" in styles and "@media(max-width:760px)" in styles
    assert "Back to Organizations" in security


def test_sms_messages_remain_immutable_and_results_use_clear_states():
    message = (ROOT / "app" / "templates" / "phone_message_detail.html").read_text(encoding="utf-8")
    result = (ROOT / "app" / "templates" / "verification_result.html").read_text(encoding="utf-8")
    review = (ROOT / "app" / "templates" / "verification_review.html").read_text(encoding="utf-8")
    assert "no longer active" not in message
    assert "activation_code" in message
    assert "CONDITION_NOT_SATISFIED" in result and "result-mark" in result
    assert "Expected result" in review and "Information returned" not in review


def test_remaining_history_tables_have_task_specific_filters():
    service_history = (ROOT / "app" / "templates" / "admin_service_history.html").read_text(encoding="utf-8")
    citizen_history = (ROOT / "app" / "templates" / "citizen_dashboard.html").read_text(encoding="utf-8")
    for field in ('name="service"', 'name="status"', 'name="administrator"',
                  'name="date_from"', 'name="date_to"', 'name="sort"'):
        assert field in service_history
    for field in ('name="q"', 'name="status"', 'name="claim"',
                  'name="date_from"', 'name="date_to"'):
        assert field in citizen_history


def test_landing_page_has_complete_public_navigation_and_responsive_design():
    home = (ROOT / "app" / "templates" / "home.html").read_text(encoding="utf-8")
    styles = (ROOT / "app" / "static" / "home.css").read_text(encoding="utf-8")
    polish = (ROOT / "app" / "static" / "landing-polish.css").read_text(encoding="utf-8")
    base = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    for section in ('id="how"', 'id="services"', 'id="privacy"', 'id="contact"'):
        assert section in home
    for route in ("/organisation/login", "/organisation/register", "/citizen/login",
                  "/citizen/activate", "/phone", "/admin/login"):
        assert route in home
    assert "What would you like to do?" in home
    assert "Administrator access" in home and "TrustID Phone" in home
    assert "@media(max-width:700px)" in styles
    assert "landing-polish.css" in home
    assert "@media (max-width: 700px)" in polish
    assert ".early-cta .cta-signin summary" in polish
    assert "block navigation" in base and "block footer" in base and "block main_class" in base


def test_public_authentication_paths_are_reciprocal_and_role_aware():
    templates = ROOT / "app" / "templates"
    home = (templates / "home.html").read_text(encoding="utf-8")
    login = (templates / "login.html").read_text(encoding="utf-8")
    register = (templates / "org_register.html").read_text(encoding="utf-8")
    activate = (templates / "citizen_activate.html").read_text(encoding="utf-8")
    assert "signin-menu" in home and "signin-dropdown" in home
    assert "/organisation/login" in home and "/citizen/login" in home
    assert "/organisation/register" in login and "/citizen/activate" in login
    assert "/organisation/login" in register and "/citizen/login" in activate
    assert "NEU Neural Defenders" in home
    assert "+234 813 700 6617" in home
    assert "vaisah.zirra@student.neu.edu.ng" in home
    assert "Start with TrustID" in home
    assert "Verify confidently.<br>Collect responsibly." in home
    assert "Use a simpler, privacy-conscious approach to identity verification." in home
    assert "cta-signin" in home
