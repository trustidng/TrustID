from pathlib import Path


def test_gender_and_middle_name_migration_preserves_authority_consistency():
    sql = Path("db/migrations/029_gender_middle_names_and_portrait_alignment.sql").read_text(encoding="utf-8")
    lowered = sql.lower()
    assert "add column gender" in lowered
    assert "add column holder_gender" in lowered
    assert "concat_ws(' ',n.first_name,n.middle_name,n.surname)" in lowered
    assert "c.full_name=l.holder_full_name" in lowered
    assert "c.date_of_birth=l.holder_date_of_birth" in lowered
    for reference in ("PHOTO-0001", "PHOTO-0002", "PHOTO-0015", "PHOTO-0016"):
        assert reference in sql


def test_seed_profiles_include_optional_middle_names_and_gender_matched_portraits():
    source = Path("db/seed_data.py").read_text(encoding="utf-8")
    assert "IDENTITY_PROFILES" in source
    assert '("Zainab", "Musa", "Abubakar", "FEMALE")' in source
    assert '("Aishatu", "Anisa", "Lawal", "FEMALE")' in source
    assert '("Yasmin", "Fatima", "Usman", "FEMALE")' in source
    assert "MALE_PORTRAITS" in source and "FEMALE_PORTRAITS" in source
    assert "holder_gender" in source


def test_gender_is_not_exposed_on_verifier_facing_surfaces():
    surface_paths = (
        "app/templates/verification_result.html",
        "app/templates/verification_history.html",
        "app/templates/receipt_detail.html",
        "app/templates/public_verification_result.html",
    )
    rendered_surfaces = "\n".join(Path(path).read_text(encoding="utf-8").lower() for path in surface_paths)
    assert "holder_gender" not in rendered_surfaces
    assert "identity.gender" not in rendered_surfaces
    assert "record.gender" not in rendered_surfaces
