"""Password hashing and recruiter token handling. No DB, no Redis, no AI."""
import pytest

from services.auth_service import (
    MAX_PASSWORD_BYTES,
    hash_password,
    verify_password,
)


def test_hash_is_not_the_plaintext():
    h = hash_password("correct horse battery")
    assert h != "correct horse battery"
    assert h.startswith("$2b$")


def test_verify_accepts_correct_password():
    assert verify_password("s3cret-pass", hash_password("s3cret-pass"))


def test_verify_rejects_wrong_password():
    assert not verify_password("wrong-pass", hash_password("s3cret-pass"))


def test_same_password_hashes_differently():
    """Distinct salts — two recruiters with the same password must not collide."""
    assert hash_password("same-pass-1") != hash_password("same-pass-1")


def test_verify_survives_a_malformed_hash():
    """A corrupt hash is a failed login, never a 500."""
    assert not verify_password("whatever", "not-a-bcrypt-hash")


def test_oversized_password_is_rejected_not_truncated():
    """bcrypt silently ignores bytes past 72; we must not accept a prefix."""
    long_pw = "a" * (MAX_PASSWORD_BYTES + 10)
    with pytest.raises(ValueError):
        hash_password(long_pw)


def test_oversized_password_cannot_authenticate_via_prefix():
    h = hash_password("a" * MAX_PASSWORD_BYTES)
    assert not verify_password("a" * (MAX_PASSWORD_BYTES + 10), h)
