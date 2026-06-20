"""Password policy (backend-design AUTH §3). Enforced on REGISTER only (login accepts legacy
passwords). The bundled common-passwords list is a starter set (expandable) — see data/."""
import functools
from pathlib import Path

_DATA = Path(__file__).resolve().parent / "data" / "common_passwords.txt"
MIN_BYTES, MAX_BYTES = 8, 72   # 72 = bcrypt's hard limit; count BYTES (multibyte-safe)


@functools.lru_cache
def common_passwords() -> frozenset:
    try:
        return frozenset(
            line.strip().lower()
            for line in _DATA.read_text(encoding="utf-8").splitlines() if line.strip())
    except FileNotFoundError:   # degrade gracefully — length/letter/digit rules still apply
        return frozenset()


def validate_password_policy(v: str) -> None:
    """Raise ValueError (human-readable) if the password violates policy; return None if OK."""
    n = len(v.encode("utf-8"))
    if n < MIN_BYTES:
        raise ValueError("Password must be at least 8 characters.")
    if n > MAX_BYTES:
        raise ValueError("Password must be at most 72 bytes.")
    if not any(c.isalpha() for c in v):
        raise ValueError("Password must contain a letter.")
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain a digit.")
    if v.lower() in common_passwords():
        raise ValueError("Password is too common — pick something less guessable.")
