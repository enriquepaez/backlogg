"""Observability — structured JSON logging, request correlation, optional Sentry.

This module is the platform-layer entry point for logging and error tracking
(precedent: ``core/rate_limit.py``). It has three responsibilities:

1. **Structured logging** — a stdlib-only :class:`JSONFormatter` renders every
   log record as a single JSON line with a stable set of fields (timestamp,
   level, logger, message, request_id) plus any ``extra`` fields. No third-party
   dependency is used for the JSON rendering.

2. **Request correlation** — a :class:`RequestIDMiddleware` reads or generates an
   ``X-Request-ID`` per request, stores it in a :class:`~contextvars.ContextVar`
   so *every* log emitted while handling the request carries it, logs one
   access line (method, path, status, duration_ms) on completion, and echoes the
   id back in the response header.

3. **Secret redaction** — the formatter never emits the values of sensitive
   fields (passwords, API keys, tokens, authorization headers, …). Redaction is
   applied defensively to both the ``extra`` fields and, best-effort, to the
   formatted message text.

Sentry is optional: :func:`init_sentry` imports ``sentry_sdk`` lazily and only
when ``SENTRY_DSN`` is set. With no DSN the import never happens, so there is no
runtime overhead and nothing to fail.
"""

import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ── Request correlation ───────────────────────────────────────────────────────

REQUEST_ID_HEADER = "X-Request-ID"

# Holds the current request's id. Defaults to None outside a request so logs
# emitted at startup or in background jobs still format cleanly.
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


# ── Secret redaction ──────────────────────────────────────────────────────────

REDACTED = "***REDACTED***"

# Field/key names whose values must never reach the logs. Matched
# case-insensitively as a substring of the key (so "smtp_password" matches
# "password", "x-api-key" matches "api_key", etc.).
SENSITIVE_KEYS: tuple[str, ...] = (
    "password",
    "api_key",
    "apikey",
    "token",
    "authorization",
    "x-api-key",
    "refresh_token",
    "smtp_password",
    "secret",
)

# Reserved LogRecord attributes — anything else on the record is treated as an
# ``extra`` field and included in the JSON payload.
_RESERVED_RECORD_ATTRS = frozenset(
    logging.makeLogRecord({}).__dict__.keys() | {"message", "asctime", "taskName"}
)

_KEY_ALT = "|".join(re.escape(k) for k in SENSITIVE_KEYS)

# key=value / key: value pairs with optional quotes around the key and/or the
# value. Covers kwargs (password=x), dict-repr ('password': 'x') and JSON
# ("password": "x") forms — the common cases when a dict is logged via f-string,
# ``%s`` or appears inside a traceback.
_KEYVALUE_SECRET_RE = re.compile(
    r"(?i)(?P<qk>['\"]?)(?P<key>" + _KEY_ALT + r")(?P=qk)"
    r"(?P<sep>\s*[=:]\s*)"
    r"(?:(?P<qv>['\"])(?P<qval>.*?)(?P=qv)|(?P<uval>[^\s,;)}\]'\"]+))"
)

# Authorization-scheme credentials: redact the token after Bearer/Token. The
# key=value pass alone would stop at the space and leave the real token intact,
# so this runs first and masks the credential up to the next delimiter.
_SCHEME_SECRET_RE = re.compile(r"(?i)\b(?P<scheme>Bearer|Token)\s+(?P<tok>[^\s,;\"')}\]]+)")


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(sensitive in lowered for sensitive in SENSITIVE_KEYS)


def redact_value(key: str, value: object) -> object:
    """Redact *value* when *key* is sensitive, recursing into dicts/lists."""
    if _is_sensitive_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact_value(k, v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(key, v) for v in value]
    return value


def _redact_keyvalue(match: re.Match) -> str:
    quote_key = match.group("qk")
    prefix = f"{quote_key}{match.group('key')}{quote_key}{match.group('sep')}"
    quote_val = match.group("qv")
    if quote_val is not None:
        return f"{prefix}{quote_val}{REDACTED}{quote_val}"
    return f"{prefix}{REDACTED}"


def redact_text(text: str) -> str:
    """Mask secrets embedded in free-form message / traceback text.

    Handles ``key=value`` and ``key: value`` pairs with or without quotes around
    the key or value (so kwargs, dict-repr and JSON forms are all covered) and
    Authorization-scheme credentials (``Bearer``/``Token`` <secret>). The scheme
    pass runs first so the credential is masked before the key=value pass, which
    would otherwise stop at the space and leave the token exposed.
    """
    text = _SCHEME_SECRET_RE.sub(lambda m: f"{m.group('scheme')} {REDACTED}", text)
    return _KEYVALUE_SECRET_RE.sub(_redact_keyvalue, text)


# ── JSON formatter ────────────────────────────────────────────────────────────


class JSONFormatter(logging.Formatter):
    """Render a :class:`logging.LogRecord` as a single JSON line.

    Emits a stable core schema (timestamp, level, logger, message, request_id)
    and appends any non-reserved record attributes (the ``extra=`` fields) after
    redacting sensitive values. Exception info is included as a formatted string.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact_text(record.getMessage()),
            "request_id": request_id_ctx.get(),
        }

        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key.startswith("_"):
                continue
            payload[key] = redact_value(key, value)

        if record.exc_info:
            # Redact secrets that may be embedded in an exception message/traceback.
            payload["exception"] = redact_text(self.formatException(record.exc_info))

        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON handler on the root logger. Idempotent.

    Replaces any existing handlers with a single ``StreamHandler`` using
    :class:`JSONFormatter`, so calling this more than once (e.g. app reloads in
    tests) never stacks duplicate handlers.
    """
    root = logging.getLogger()
    root.setLevel(level.upper())

    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())

    # Idempotency: drop previously-installed handlers before adding ours.
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)


# ── Request ID middleware ─────────────────────────────────────────────────────


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Assign/propagate an ``X-Request-ID`` and log one access line per request.

    Reads an inbound ``X-Request-ID`` (or generates a uuid4), stores it in the
    request-scoped ContextVar so every log during the request is correlated,
    measures wall-clock duration, logs method/path/status/duration_ms on
    completion, and echoes the id in the response header.
    """

    _logger = logging.getLogger("backlogg.request")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        # Set (not reset) the context var: every request overwrites it up front,
        # and leaving it set means the outer global exception handler — which
        # runs after this middleware unwinds when call_next raises — still sees
        # the id to correlate the error.
        request_id_ctx.set(request_id)
        start = time.perf_counter()

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        self._logger.info(
            "request.completed",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


# ── Sentry (optional) ─────────────────────────────────────────────────────────


def init_sentry() -> bool:
    """Initialise Sentry only when ``SENTRY_DSN`` is set. Lazy import.

    Returns ``True`` when Sentry was initialised, ``False`` otherwise (no DSN, or
    the ``sentry_sdk`` package is not installed). Never raises: a missing package
    is logged as a warning and the app continues without error tracking.
    """
    from backlogg.core.config import settings

    dsn = settings.SENTRY_DSN.strip()
    if not dsn:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
    except ImportError:
        logging.getLogger("backlogg.observability").warning(
            "SENTRY_DSN is set but sentry-sdk is not installed; error tracking disabled"
        )
        return False

    sentry_sdk.init(dsn=dsn, integrations=[FastApiIntegration()])
    return True
