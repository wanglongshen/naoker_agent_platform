import pytest
from app.core.security import create_access_token, hash_password, validate_password, verify_password


def test_password_hash_verifies_only_original_password() -> None:
    password_hash = hash_password("Password123")
    assert verify_password("Password123", password_hash) is True
    assert verify_password("Password124", password_hash) is False


def test_password_requires_letter_digit_and_eight_characters() -> None:
    with pytest.raises(ValueError, match="密码长度不能少于 8 位"):
        validate_password("abc123")
    with pytest.raises(ValueError, match="密码必须同时包含字母和数字"):
        validate_password("abcdefgh")


def test_password_requires_chinese_validation_messages() -> None:
    with pytest.raises(ValueError, match="密码长度不能少于 8 位"):
        validate_password("Abc123")
    with pytest.raises(ValueError, match="密码必须同时包含字母和数字"):
        validate_password("87654321")
