"""Structured logging (backend-design §10): structlog JSON lines on stdout with request_id binding,
and a BINDING redaction processor (§10.3) — never log passwords, Authorization headers / JWTs, or API
keys/tokens; emails appear ONLY in auth.* events, masked everywhere else."""
import logging
import re
import sys

import structlog

# Any event-dict key whose lowercased name contains one of these is replaced with '***'.
_SECRET_SUBSTRINGS = ("password", "authorization", "api_key", "apikey", "access_token",
                      "refresh_token", "secret", "jwt", "bearer", "auth_token", "ct0", "cookie")
# A bare 'token' key (but not 'token_type') is also a secret.
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_AUTH_EVENTS = {"auth.register", "auth.login.success", "auth.login.failed"}
_EMAIL_OK_KEYS = {"event", "level", "timestamp", "logger"}


def _is_secret_key(key: str) -> bool:
    lk = key.lower()
    if lk == "token" or lk.endswith("_token"):
        return lk != "token_type"
    return any(s in lk for s in _SECRET_SUBSTRINGS)


def _scrub(value, mask_email: bool):
    """Recursively redact secret keys + mask emails inside nested dict/list values, returning NEW
    containers (never mutating caller-owned nested objects)."""
    if isinstance(value, dict):
        return {k: ("***" if _is_secret_key(k) else _scrub(v, mask_email)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return type(value)(_scrub(v, mask_email) for v in value)
    if mask_email and isinstance(value, str) and _EMAIL_RE.search(value):
        return _EMAIL_RE.sub("***@***", value)
    return value


def redact(logger, method_name, event_dict):
    """Strip secrets by key and mask emails (unless an auth.* event), recursing into nested
    structured fields so a secret/email buried in a dict or list value is redacted too (§10.3)."""
    mask_email = event_dict.get("event") not in _AUTH_EVENTS
    out = {}
    for k, v in event_dict.items():
        if _is_secret_key(k):
            out[k] = "***"
        elif k in _EMAIL_OK_KEYS:
            out[k] = v
        else:
            out[k] = _scrub(v, mask_email)
    return out


_configured = False


def configure_logging(level: str = "INFO") -> None:
    """Idempotent structlog config: contextvars (request_id) + level + ISO ts + redact + JSON."""
    global _configured
    if _configured:
        return
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redact,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str = "dcintel"):
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)
