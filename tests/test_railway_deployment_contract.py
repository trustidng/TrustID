from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_railway_staging_uses_safe_startup_and_healthcheck():
    config = (ROOT / "railway.toml").read_text(encoding="utf-8")
    assert "python db/migrate.py && uvicorn app.main:app" in config
    assert "--host 0.0.0.0 --port $PORT" in config
    assert 'healthcheckPath = "/health"' in config
    assert "seed_data.py" not in config
    assert "schema.sql" not in config


def test_railway_guide_keeps_database_private_and_storage_persistent():
    guide = (ROOT / "docs" / "Railway_Staging_Deployment.md").read_text(encoding="utf-8")
    assert "Do not enable public networking for MySQL" in guide
    assert "EVIDENCE_STORAGE_PATH=/app/var/organisation-evidence" in guide
    assert "COOKIE_SECURE=true" in guide
    assert "Do not upload `.env`" in guide
