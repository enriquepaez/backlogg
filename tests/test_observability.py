"""Tests for observability: structured JSON logging, request IDs, Sentry (feature #38).

Acceptance criteria validated here:
  AC1  Middleware assigns/propagates X-Request-ID per request, in logs and response
  AC2  Structured JSON logs with configurable LOG_LEVEL; each request logs
       method/path/status/duration
  AC3  Sensitive data (passwords, API keys, tokens, X-API-Key) never appear in logs
  AC4  Sentry only initialised when SENTRY_DSN is set; absent = no overhead / no failure
  AC5  Unhandled exceptions captured, correlated with the request id
  AC6  Tests verify the request id in the response and the redaction of secrets
"""

import io
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi.testclient import TestClient

from backlogg.core.observability import (
    JSONFormatter,
    configure_logging,
    init_sentry,
    redact_text,
    request_id_ctx,
)
from backlogg.main import app

client = TestClient(app, raise_server_exceptions=True)

# A throwaway route that raises so the global exception handler can be exercised.
_boom_client = TestClient(app, raise_server_exceptions=False)


# The exception message embeds secrets in the three risky shapes (bare kwarg,
# dict-repr and Authorization scheme) so the traceback redaction is exercised for
# real, not just the trivially-masked ``password=`` case.
_BOOM_SECRETS = ("hunter2", "sk-leak-boom", "eyJleaktoken")


@app.get("/_test/boom")
async def _boom():
    raise RuntimeError(
        "kaboom with password=hunter2 headers={'X-Api-Key': 'sk-leak-boom', "
        "'Authorization': 'Bearer eyJleaktoken'}"
    )


# ── Helpers ────────────────────────────────────────────────────────────────────


class _CaptureHandler(logging.Handler):
    """Capture emitted records as JSON strings produced by JSONFormatter."""

    def __init__(self) -> None:
        super().__init__()
        self.setFormatter(JSONFormatter())
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(self.format(record))

    def records(self) -> list[dict]:
        return [json.loads(line) for line in self.lines]


@contextmanager
def capture_logs() -> Iterator[_CaptureHandler]:
    """Attach a JSON-capturing handler to the root logger.

    Forces the root level to DEBUG for the duration (other test modules and the
    pytest logging plugin may leave it higher, which would otherwise filter the
    INFO access log before it reaches the handler) and restores it afterwards.
    """
    handler = _CaptureHandler()
    handler.setLevel(logging.DEBUG)
    root = logging.getLogger()
    previous_level = root.level

    # The pytest logging plugin (and other tests' caplog usage) can leave logging
    # globally disabled and individual app loggers flagged ``disabled=True``,
    # which short-circuits records before they reach any handler. Re-enable both
    # for the duration and restore the prior state afterwards.
    previous_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    affected = [root, logging.getLogger("backlogg.request"), logging.getLogger("backlogg.main")]
    previous_disabled = {lg: lg.disabled for lg in affected}
    for lg in affected:
        lg.disabled = False

    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    try:
        yield handler
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)
        logging.disable(previous_disable)
        for lg, flag in previous_disabled.items():
            lg.disabled = flag


# ── AC1 / AC6: request id ──────────────────────────────────────────────────────


def test_request_id_present_in_response():
    """AC1: every response carries an X-Request-ID header."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.headers.get("x-request-id")


def test_request_id_generated_is_uuid_like():
    """AC1: a generated request id is a non-trivial unique token."""
    r1 = client.get("/health")
    r2 = client.get("/health")
    id1 = r1.headers.get("x-request-id")
    id2 = r2.headers.get("x-request-id")
    assert id1 and id2
    assert id1 != id2


def test_request_id_inbound_is_respected():
    """AC1: an inbound X-Request-ID is propagated to the response unchanged."""
    supplied = "test-correlation-123"
    response = client.get("/health", headers={"X-Request-ID": supplied})
    assert response.headers.get("x-request-id") == supplied


def test_request_id_propagated_to_logs():
    """AC1/AC2: the per-request access log carries the same request id."""
    supplied = "log-correlation-999"
    with capture_logs() as handler:
        response = client.get("/health", headers={"X-Request-ID": supplied})

    assert response.headers.get("x-request-id") == supplied
    completed = [r for r in handler.records() if r["message"] == "request.completed"]
    assert completed, "expected a request.completed log line"
    assert any(r["request_id"] == supplied for r in completed)


# ── AC2: structured JSON access log ─────────────────────────────────────────────


def test_access_log_has_method_path_status_duration():
    """AC2: each request logs method, path, status and duration in JSON."""
    with capture_logs() as handler:
        client.get("/health")

    completed = [r for r in handler.records() if r["message"] == "request.completed"]
    assert completed
    entry = completed[-1]
    assert entry["method"] == "GET"
    assert entry["path"] == "/health"
    assert entry["status"] == 200
    assert isinstance(entry["duration_ms"], (int, float))
    # Core schema fields are always present.
    for field in ("timestamp", "level", "logger", "message", "request_id"):
        assert field in entry


def test_json_formatter_output_is_parseable():
    """AC2: the formatter always emits a single parseable JSON object."""
    record = logging.LogRecord(
        name="backlogg.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    payload = json.loads(JSONFormatter().format(record))
    assert payload["message"] == "hello world"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "backlogg.test"


def test_configure_logging_is_idempotent():
    """AC2: repeated configuration never stacks duplicate handlers."""
    configure_logging("INFO")
    before = len(logging.getLogger().handlers)
    configure_logging("DEBUG")
    after = len(logging.getLogger().handlers)
    assert after == before == 1
    assert logging.getLogger().level == logging.DEBUG
    # Restore the default level for the rest of the suite.
    configure_logging("INFO")


# ── AC3 / AC6: secret redaction ─────────────────────────────────────────────────


def test_redaction_of_extra_fields():
    """AC3: sensitive extra fields never appear in clear text."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JSONFormatter())
    handler.setLevel(logging.DEBUG)
    logger = logging.getLogger("backlogg.test.redaction")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    try:
        logger.info(
            "user login",
            extra={
                "password": "hunter2",
                "api_key": "sk-secret-abc",
                "authorization": "Bearer xyz",
                "refresh_token": "rt-1234",
                "username": "alice",
            },
        )
    finally:
        logger.removeHandler(handler)

    raw = stream.getvalue()
    assert "hunter2" not in raw
    assert "sk-secret-abc" not in raw
    assert "Bearer xyz" not in raw
    assert "rt-1234" not in raw
    # Non-sensitive fields survive.
    payload = json.loads(raw)
    assert payload["username"] == "alice"
    assert payload["password"] == "***REDACTED***"


def test_redaction_of_nested_extra():
    """AC3: redaction recurses into nested dicts/lists in extra fields."""
    record = logging.LogRecord(
        name="backlogg.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="payload",
        args=(),
        exc_info=None,
    )
    record.data = {"x_api_key": "topsecret", "nested": {"token": "abc123"}}
    payload = json.loads(JSONFormatter().format(record))
    assert "topsecret" not in json.dumps(payload)
    assert "abc123" not in json.dumps(payload)


def test_redaction_of_inline_bare_kwargs():
    """AC3: bare ``key=value`` / ``key: value`` secrets in text are masked."""
    masked = redact_text("logging in with password=hunter2 and token: abc.def")
    assert "hunter2" not in masked
    assert "abc.def" not in masked
    assert "***REDACTED***" in masked


def test_redaction_of_dict_repr_secret():
    """AC3: a Python dict-repr with a sensitive key does not leak its value."""
    masked = redact_text("payload={'password': 'hunter2', 'user': 'alice'}")
    assert "hunter2" not in masked
    # Non-sensitive keys and their values survive.
    assert "alice" in masked
    assert "***REDACTED***" in masked


def test_redaction_of_json_form_secret():
    """AC3: a JSON ``"key": "value"`` pair with a sensitive key is masked."""
    masked = redact_text('body {"api_key": "sk-leak-123", "page": 2}')
    assert "sk-leak-123" not in masked
    assert "***REDACTED***" in masked


def test_redaction_of_authorization_bearer_token():
    """AC3: the credential after Bearer/Token is fully redacted, not just the scheme."""
    masked = redact_text("Authorization: Bearer eyJleaktoken.signature")
    assert "eyJleaktoken.signature" not in masked
    assert "***REDACTED***" in masked

    quoted = redact_text("headers={'Authorization': 'Bearer eyJleaktoken'}")
    assert "eyJleaktoken" not in quoted


# ── AC4: Sentry is optional ─────────────────────────────────────────────────────


def test_sentry_not_initialised_without_dsn(monkeypatch):
    """AC4: with an empty SENTRY_DSN, init_sentry is a no-op that never fails."""
    from backlogg.core import config

    monkeypatch.setattr(config.settings, "SENTRY_DSN", "")
    assert init_sentry() is False


def test_sentry_initialised_with_dsn(monkeypatch):
    """AC4: with a DSN set, Sentry is initialised with that DSN."""
    import sentry_sdk

    from backlogg.core import config

    captured = {}

    def fake_init(*args, **kwargs):
        captured["dsn"] = kwargs.get("dsn")

    monkeypatch.setattr(config.settings, "SENTRY_DSN", "https://public@sentry.example/1")
    monkeypatch.setattr(sentry_sdk, "init", fake_init)
    assert init_sentry() is True
    assert captured["dsn"] == "https://public@sentry.example/1"


# ── AC5 / AC6: unhandled exceptions ─────────────────────────────────────────────


def test_unhandled_exception_returns_500_with_request_id():
    """AC5: an uncaught exception yields a generic 500 carrying the request id."""
    supplied = "boom-correlation-777"
    response = _boom_client.get("/_test/boom", headers={"X-Request-ID": supplied})
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error"}
    assert response.headers.get("x-request-id") == supplied


def test_unhandled_exception_is_logged_and_correlated():
    """AC5: the exception is logged, correlated with the request id, and redacted."""
    supplied = "boom-log-555"
    with capture_logs() as handler:
        _boom_client.get("/_test/boom", headers={"X-Request-ID": supplied})

    errors = [r for r in handler.records() if r["message"] == "request.unhandled_exception"]
    assert errors, "expected an unhandled-exception log line"
    entry = errors[-1]
    assert entry["request_id"] == supplied
    assert entry["path"] == "/_test/boom"
    assert entry["level"] == "ERROR"
    assert "exception" in entry
    # The stack trace must not leak any secret embedded in the exception message,
    # in any of the risky shapes (bare kwarg, dict-repr, Authorization scheme).
    serialised = json.dumps(entry)
    for secret in _BOOM_SECRETS:
        assert secret not in serialised


def test_request_id_ctx_default_outside_request():
    """The context var is None outside of a request lifecycle."""
    assert request_id_ctx.get() is None
