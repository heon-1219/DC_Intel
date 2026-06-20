"""M6a password policy (backend-design AUTH §3): 8..72 BYTES, >=1 letter AND >=1 digit, not common."""
import pytest

from app.auth.passwords import validate_password_policy


def test_valid_password_passes():
    validate_password_policy("Tr0ubadour9x")    # 12 bytes, letter+digit, not common -> no raise


@pytest.mark.parametrize("pw", ["ab1", "a1b2c3"])   # < 8 bytes
def test_too_short_rejected(pw):
    with pytest.raises(ValueError):
        validate_password_policy(pw)


def test_too_long_rejected():
    with pytest.raises(ValueError):
        validate_password_policy("a1" + "x" * 71)   # 73 bytes


def test_letters_only_rejected():
    with pytest.raises(ValueError):
        validate_password_policy("abcdefghij")      # no digit


def test_digits_only_rejected():
    with pytest.raises(ValueError):
        validate_password_policy("1234567890")      # no letter


def test_common_password_rejected():
    with pytest.raises(ValueError):
        validate_password_policy("password1")       # in the bundled common list (has letter+digit)


def test_policy_uses_byte_length_not_char_length():
    # 26 chars but 74 bytes (Korean chars are 3 bytes) -> must be rejected on the BYTE limit.
    pw = "1a" + "가" * 24                        # 2 + 72 = 74 bytes
    assert len(pw) == 26
    with pytest.raises(ValueError):
        validate_password_policy(pw)
