import pytest

from app.security import normalize_phone, validate_password, validate_pin


@pytest.mark.parametrize("raw,expected", [
    ("08031234567", "+2348031234567"),
    ("2348031234567", "+2348031234567"),
    ("+2348031234567", "+2348031234567"),
    ("09031234567", "+2349031234567"),
    ("09131234567", "+2349131234567"),
    (" +234 803 123 4567 ", "+2348031234567"),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["123", "+12025550123", "0803abc4567"])
def test_rejects_invalid_phone(raw):
    with pytest.raises(ValueError):
        normalize_phone(raw)


def test_password_policy():
    validate_password("CorrectHorse7")
    validate_password("professional password")
    with pytest.raises(ValueError):
        validate_password("short")


@pytest.mark.parametrize("password", ["password123", "qwerty12345", "trustid123"])
def test_rejects_common_passwords(password):
    with pytest.raises(ValueError):
        validate_password(password)


def test_password_does_not_require_character_categories():
    validate_password("lowercaseonly")


@pytest.mark.parametrize("pin", ["1234", "0000", "12ab", "1234567"])
def test_rejects_weak_pin(pin):
    with pytest.raises(ValueError):
        validate_pin(pin)


def test_accepts_nontrivial_pin():
    validate_pin("4826")
