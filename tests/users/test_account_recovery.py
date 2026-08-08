"""Tests for account recovery — email verification and password reset.

Covers the service layer (backlogg/users/service.py) against the real test DB
and the HTTP endpoints through httpx.AsyncClient. The EmailSender is always
mocked so no real mail server is contacted; the fallback (no SMTP host) path is
tested against the real ``get_email_sender`` factory.
"""

import logging
import smtplib
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from backlogg.core import email as email_mod
from backlogg.core.email import (
    EmailSender,
    LoggingEmailSender,
    SmtpEmailSender,
    get_email_sender,
)
from backlogg.main import app
from backlogg.users import repository as repo
from backlogg.users import service
from backlogg.users.auth import hash_opaque_token, hash_refresh_token
from backlogg.users.models import (
    TOKEN_PURPOSE_EMAIL_VERIFY,
    TOKEN_PURPOSE_PASSWORD_RESET,
)
from backlogg.users.schemas import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    UserCreate,
    UserLogin,
    VerifyConfirmRequest,
)


class FakeEmailSender(EmailSender):
    """Records every send so tests can assert on the link that was mailed."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        self.sent.append({"to": to, "subject": subject, "html": html, "text": text})


class ExplodingEmailSender(EmailSender):
    """Simulates a mail-server outage — always raises."""

    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        raise RuntimeError("smtp is down")


@contextmanager
def capture_email_logs():
    """Capture records from the email module logger, robust to the full suite.

    Another test's caplog machinery may leave the logger disabled or
    logging globally disabled; this re-enables both for the duration and
    restores the previous state afterwards.
    """
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.NOTSET)
    email_mod.logger.addHandler(handler)
    previous_level = email_mod.logger.level
    email_mod.logger.setLevel(logging.INFO)
    previous_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    previous_disabled_flag = email_mod.logger.disabled
    email_mod.logger.disabled = False
    try:
        yield records
    finally:
        logging.disable(previous_disable)
        email_mod.logger.disabled = previous_disabled_flag
        email_mod.logger.removeHandler(handler)
        email_mod.logger.setLevel(previous_level)


async def _register(db, username: str) -> object:
    await service.register_user(
        db,
        UserCreate(
            username=username,
            email=f"{username}@example.com",
            password="s3cret-password",
        ),
    )
    return await repo.get_user_by_username(db, username)


# ── EmailSender factory / fallback ─────────────────────────────────────────────


def test_get_email_sender_falls_back_to_logging_without_smtp_host(monkeypatch):
    monkeypatch.setattr(email_mod.settings, "SMTP_HOST", "")
    assert isinstance(get_email_sender(), LoggingEmailSender)


def test_get_email_sender_uses_smtp_with_host(monkeypatch):
    monkeypatch.setattr(email_mod.settings, "SMTP_HOST", "smtp.example.com")
    sender = get_email_sender()
    assert isinstance(sender, SmtpEmailSender)


async def test_logging_sender_logs_link_but_no_secret():
    """The fallback logs the link but never a credential."""
    with capture_email_logs() as records:
        sender = LoggingEmailSender()
        await sender.send(
            to="someone@example.com",
            subject="Verify",
            html="<a>link</a>",
            text="http://localhost:8000/verify-email?token=abc",
        )

    joined = " ".join(r.getMessage() for r in records)
    assert "token=abc" in joined
    # The fallback never receives credentials, so none can leak.
    assert "SMTP_PASSWORD" not in joined


async def test_smtp_sender_does_not_leak_password_on_failure(monkeypatch):
    """A send failure is logged generically — the SMTP password never leaks."""
    secret_password = "super-secret-smtp-pw"

    class _BrokenSMTP:
        def __init__(self, host, port):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self):
            pass

        def login(self, username, password):
            # Reference the password so a naive repr/log would expose it.
            raise smtplib.SMTPAuthenticationError(535, f"auth failed for {password}")

        def send_message(self, message):
            pass

    monkeypatch.setattr(smtplib, "SMTP", _BrokenSMTP)

    sender = SmtpEmailSender(
        host="smtp.example.com",
        port=587,
        username="user@example.com",
        password=secret_password,
        from_email="no-reply@backlogg.local",
        starttls=True,
    )

    with capture_email_logs() as records:
        # The service layer swallows the failure and logs generically.
        await service._send_email_safe(
            sender,
            to="dest@example.com",
            subject="Reset your password",
            html="<a>link</a>",
            text="http://localhost:8000/reset-password?token=xyz",
        )

    joined = " ".join(r.getMessage() for r in records)
    assert secret_password not in joined


def test_smtp_sender_builds_multipart_message():
    """The built message carries both text and HTML alternatives."""
    sender = SmtpEmailSender(
        host="smtp.example.com",
        port=587,
        username="",
        password="",
        from_email="no-reply@backlogg.local",
        starttls=True,
    )
    message = sender._build_message(
        to="dest@example.com",
        subject="Verify",
        html="<p>hi</p>",
        text="hi",
    )
    assert message["From"] == "no-reply@backlogg.local"
    assert message["To"] == "dest@example.com"
    assert message.is_multipart()
    subtypes = {part.get_content_subtype() for part in message.iter_parts()}
    assert {"plain", "html"} <= subtypes


# ── Email verification (service) ───────────────────────────────────────────────


async def test_request_verification_persists_only_hash_and_mails_link(db):
    user = await _register(db, "verify-req-user")
    sender = FakeEmailSender()

    result = await service.request_email_verification(db, user, sender)
    assert result.detail

    assert len(sender.sent) == 1
    link = sender.sent[0]["text"]
    # Extract the plaintext token from the mailed link.
    token = link.split("token=")[1]
    stored = await repo.get_account_token_by_hash(db, hash_opaque_token(token))
    assert stored is not None
    assert stored.purpose == TOKEN_PURPOSE_EMAIL_VERIFY
    assert stored.consumed_at is None
    # Only the hash is stored, never the plaintext.
    assert stored.token_hash != token


async def test_confirm_verification_marks_email_verified(db):
    user = await _register(db, "verify-confirm-user")
    assert user.email_verified is False
    sender = FakeEmailSender()

    await service.request_email_verification(db, user, sender)
    token = sender.sent[0]["text"].split("token=")[1]

    await service.confirm_email_verification(db, VerifyConfirmRequest(token=token))
    refreshed = await repo.get_user_by_username(db, "verify-confirm-user")
    assert refreshed.email_verified is True


async def test_confirm_verification_is_single_use(db):
    user = await _register(db, "verify-single-use")
    sender = FakeEmailSender()
    await service.request_email_verification(db, user, sender)
    token = sender.sent[0]["text"].split("token=")[1]

    await service.confirm_email_verification(db, VerifyConfirmRequest(token=token))
    with pytest.raises(HTTPException) as exc_info:
        await service.confirm_email_verification(db, VerifyConfirmRequest(token=token))
    assert exc_info.value.status_code == 400


async def test_confirm_verification_invalid_token_400(db):
    with pytest.raises(HTTPException) as exc_info:
        await service.confirm_email_verification(db, VerifyConfirmRequest(token="never-issued"))
    assert exc_info.value.status_code == 400


async def test_confirm_verification_expired_token_400(db):
    user = await _register(db, "verify-expired")
    plaintext = "expired-verify-token"
    past = datetime.now(UTC) - timedelta(hours=1)
    await repo.create_account_token(
        db, user.id, hash_opaque_token(plaintext), TOKEN_PURPOSE_EMAIL_VERIFY, past
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.confirm_email_verification(db, VerifyConfirmRequest(token=plaintext))
    assert exc_info.value.status_code == 400


async def test_confirm_verification_rejects_wrong_purpose(db):
    """A password-reset token must not verify an email."""
    user = await _register(db, "verify-wrong-purpose")
    plaintext = "reset-token-used-for-verify"
    future = datetime.now(UTC) + timedelta(hours=1)
    await repo.create_account_token(
        db, user.id, hash_opaque_token(plaintext), TOKEN_PURPOSE_PASSWORD_RESET, future
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.confirm_email_verification(db, VerifyConfirmRequest(token=plaintext))
    assert exc_info.value.status_code == 400


# ── Password reset (service) ───────────────────────────────────────────────────


async def test_forgot_password_no_enumeration_for_unknown_email(db):
    """Unknown email issues no token but returns the same acknowledgement."""
    sender = FakeEmailSender()
    result = await service.request_password_reset(
        db, ForgotPasswordRequest(email="nobody-registered@example.com"), sender
    )
    assert result.detail
    assert sender.sent == []


async def test_forgot_password_known_email_issues_reset_token(db):
    user = await _register(db, "forgot-known")
    sender = FakeEmailSender()
    result = await service.request_password_reset(
        db, ForgotPasswordRequest(email=user.email), sender
    )
    assert result.detail
    assert len(sender.sent) == 1
    token = sender.sent[0]["text"].split("token=")[1]
    stored = await repo.get_account_token_by_hash(db, hash_opaque_token(token))
    assert stored is not None
    assert stored.purpose == TOKEN_PURPOSE_PASSWORD_RESET


async def test_forgot_password_same_message_for_known_and_unknown(db):
    user = await _register(db, "forgot-compare")
    sender = FakeEmailSender()
    known = await service.request_password_reset(
        db, ForgotPasswordRequest(email=user.email), sender
    )
    unknown = await service.request_password_reset(
        db, ForgotPasswordRequest(email="ghost@example.com"), sender
    )
    assert known.detail == unknown.detail


async def test_forgot_password_provider_failure_still_acks(db):
    """A mail-server outage must not break the response nor reveal the email exists."""
    user = await _register(db, "forgot-provider-down")
    sender = ExplodingEmailSender()
    result = await service.request_password_reset(
        db, ForgotPasswordRequest(email=user.email), sender
    )
    assert result.detail
    # The token was still issued and persisted despite the send failure.
    from sqlalchemy import select

    from backlogg.users.models import AccountToken

    rows = (
        (await db.execute(select(AccountToken).where(AccountToken.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_reset_password_changes_hash_and_revokes_refresh_tokens(db):
    user = await _register(db, "reset-revokes")
    old_hash = user.password_hash

    # Active refresh token (feature 35) that must be revoked on reset.
    login = await service.login_user(
        db, UserLogin(username="reset-revokes", password="s3cret-password")
    )
    refresh_stored = await repo.get_refresh_token_by_hash(
        db, hash_refresh_token(login.refresh_token)
    )
    assert refresh_stored.revoked_at is None

    sender = FakeEmailSender()
    await service.request_password_reset(db, ForgotPasswordRequest(email=user.email), sender)
    token = sender.sent[0]["text"].split("token=")[1]

    await service.reset_password(
        db, ResetPasswordRequest(token=token, new_password="brand-new-password")
    )

    refreshed = await repo.get_user_by_username(db, "reset-revokes")
    assert refreshed.password_hash != old_hash
    assert service.verify_password("brand-new-password", refreshed.password_hash)

    revoked = await repo.get_refresh_token_by_hash(db, hash_refresh_token(login.refresh_token))
    assert revoked.revoked_at is not None


async def test_reset_password_is_single_use(db):
    user = await _register(db, "reset-single-use")
    sender = FakeEmailSender()
    await service.request_password_reset(db, ForgotPasswordRequest(email=user.email), sender)
    token = sender.sent[0]["text"].split("token=")[1]

    await service.reset_password(
        db, ResetPasswordRequest(token=token, new_password="first-new-password")
    )
    with pytest.raises(HTTPException) as exc_info:
        await service.reset_password(
            db, ResetPasswordRequest(token=token, new_password="second-new-password")
        )
    assert exc_info.value.status_code == 400


async def test_reset_password_invalid_token_400(db):
    with pytest.raises(HTTPException) as exc_info:
        await service.reset_password(
            db, ResetPasswordRequest(token="never-issued", new_password="whatever-8chars")
        )
    assert exc_info.value.status_code == 400


# ── Endpoint tests ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def sender():
    return FakeEmailSender()


@pytest_asyncio.fixture
async def client(db, sender):
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_email_sender] = lambda: sender
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def _register_and_login_http(client, username: str) -> dict:
    await client.post(
        "/auth/register",
        json={
            "username": username,
            "email": f"{username}@example.com",
            "password": "s3cret-password",
        },
    )
    response = await client.post(
        "/auth/login", json={"username": username, "password": "s3cret-password"}
    )
    return response.json()


async def test_verify_request_requires_auth(client):
    response = await client.post("/auth/verify/request")
    assert response.status_code == 401


async def test_verify_request_and_confirm_flow(client, sender):
    pair = await _register_and_login_http(client, "http-verify-user")
    headers = {"Authorization": f"Bearer {pair['access_token']}"}

    req = await client.post("/auth/verify/request", headers=headers)
    assert req.status_code == 202

    token = sender.sent[0]["text"].split("token=")[1]
    confirm = await client.post("/auth/verify/confirm", json={"token": token})
    assert confirm.status_code == 200

    me = await client.get("/users/me", headers=headers)
    assert me.json()["email_verified"] is True


async def test_verify_confirm_invalid_returns_400(client):
    response = await client.post("/auth/verify/confirm", json={"token": "bogus"})
    assert response.status_code == 400


async def test_forgot_password_always_202(client):
    # Unknown email.
    unknown = await client.post("/auth/password/forgot", json={"email": "nobody-here@example.com"})
    assert unknown.status_code == 202

    # Known email.
    await _register_and_login_http(client, "http-forgot-user")
    known = await client.post(
        "/auth/password/forgot", json={"email": "http-forgot-user@example.com"}
    )
    assert known.status_code == 202


async def test_password_reset_flow(client, sender):
    await _register_and_login_http(client, "http-reset-user")
    await client.post("/auth/password/forgot", json={"email": "http-reset-user@example.com"})
    token = sender.sent[-1]["text"].split("token=")[1]

    reset = await client.post(
        "/auth/password/reset", json={"token": token, "new_password": "totally-new-pass"}
    )
    assert reset.status_code == 200

    # Old password no longer works, new one does.
    old = await client.post(
        "/auth/login", json={"username": "http-reset-user", "password": "s3cret-password"}
    )
    assert old.status_code == 401
    new = await client.post(
        "/auth/login", json={"username": "http-reset-user", "password": "totally-new-pass"}
    )
    assert new.status_code == 200


async def test_password_reset_invalid_token_returns_400(client):
    response = await client.post(
        "/auth/password/reset", json={"token": "bogus", "new_password": "whatever-8chars"}
    )
    assert response.status_code == 400
