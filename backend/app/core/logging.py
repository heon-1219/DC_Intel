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


def redact(logger, method_name, event_dict):
    """Strip secrets by key, then mask emails unless this is an auth.* event (§10.3)."""
    for k in list(event_dict.keys()):
        if _is_secret_key(k):
            event_dict[k] = "***"
    if event_dict.get("event") not in _AUTH_EVENTS:
        for k, v in list(event_dict.items()):
            if k not in _EMAIL_OK_KEYS and isinstance(v, str) and _EMAIL_RE.search(v):
                event_dict[k] = _EMAIL_RE.sub("***@***", v)
    return event_dict


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
