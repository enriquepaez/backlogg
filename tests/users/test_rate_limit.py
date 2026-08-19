"""Rate limiting tests for the auth endpoints.

Covers POST /auth/login, /auth/register plus the account-recovery and refresh
routes (feature 56): /auth/password/forgot, /auth/password/reset,
/auth/verify/request, /auth/verify/confirm and /auth/refresh.
"""

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from backlogg.core import config
from backlogg.core.email import EmailSender, get_email_sender
from backlogg.core.rate_limit import get_rate_limiter
from backlogg.main import app


class _FakeClock:
    def __init__(self, start: float = 5000.0) -> None:
        self.value = start

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@pytest_asyncio.fixture
async def client(db):
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _register_payload(username: str, email: str, password: str = "s3cret-password") -> dict:
    return {"username": username, "email": email, "password": password}


async def test_login_rate_limited_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(config.settings, "RATE_LIMIT_AUTH", "2/60")

    # First two attempts pass the limiter (they 401 on bad creds — not rate limited).
    for _ in range(2):
        resp = await client.post("/v1/auth/login", json={"username": "nobody", "password": "x"})
        assert resp.status_code == 401

    # Third attempt from the same IP is rejected by the limiter.
    resp = await client.post("/v1/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 429
    assert "retry-after" in {k.lower() for k in resp.headers}
    assert int(resp.headers["retry-after"]) >= 1
    # Generic message — no IP, limits or internal state leaked.
    detail = resp.json()["detail"]
    assert detail == "Too many requests. Please try again later."


async def test_register_rate_limited_returns_429(client, monkeypatch):
    monkeypatch.setattr(config.settings, "RATE_LIMIT_AUTH", "2/60")

    r1 = await client.post("/v1/auth/register", json=_register_payload("rl-a", "rl-a@example.com"))
    assert r1.status_code == 201
    r2 = await client.post("/v1/auth/register", json=_register_payload("rl-b", "rl-b@example.com"))
    assert r2.status_code == 201
    r3 = await client.post("/v1/auth/register", json=_register_payload("rl-c", "rl-c@example.com"))
    assert r3.status_code == 429
    assert int(r3.headers["retry-after"]) >= 1


async def test_auth_limit_resets_after_window(client, monkeypatch):
    monkeypatch.setattr(config.settings, "RATE_LIMIT_AUTH", "2/60")
    clock = _FakeClock()
    limiter = get_rate_limiter()
    monkeypatch.setattr(limiter, "_now", clock)

    for _ in range(2):
        resp = await client.post("/v1/auth/login", json={"username": "nobody", "password": "x"})
        assert resp.status_code == 401
    # Limit reached.
    resp = await client.post("/v1/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 429

    # Advance past the window — the limiter forgets the old hits.
    clock.advance(61)
    resp = await client.post("/v1/auth/login", json={"username": "nobody", "password": "x"})
    assert resp.status_code == 401


async def test_login_not_rate_limited_under_the_limit(client):
    """Normal traffic under the (generous) default limit is unaffected."""
    await client.post(
        "/v1/auth/register", json=_register_payload("rl-normal", "rl-normal@example.com")
    )
    resp = await client.post(
        "/v1/auth/login", json={"username": "rl-normal", "password": "s3cret-password"}
    )
    assert resp.status_code == 200


# ── Feature 56: account recovery + refresh routes share the same auth bucket ──
#
# rate_limit_auth keys solely by client IP ("auth:{ip}") — every /auth/* route
# shares one bucket per caller, matching /auth/login and /auth/register above.


class _FakeEmailSender(EmailSender):
    async def send(self, *, to: str, subject: str, html: str, text: str) -> None:
        pass


@pytest_asyncio.fixture
async def email_client(db):
    """Same as `client`, but also overrides the email sender (no real SMTP)."""
    from backlogg.core.database import get_db

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_email_sender] = lambda: _FakeEmailSender()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


async def test_refresh_rate_limited_returns_429(client, monkeypatch):
    monkeypatch.setattr(config.settings, "RATE_LIMIT_AUTH", "2/60")

    for _ in range(2):
        resp = await client.post("/v1/auth/refresh", json={"refresh_token": "bogus-token"})
        assert resp.status_code == 401

    resp = await client.post("/v1/auth/refresh", json={"refresh_token": "bogus-token"})
    assert resp.status_code == 429
    assert "retry-after" in {k.lower() for k in resp.headers}
    assert int(resp.headers["retry-after"]) >= 1


async def test_password_forgot_rate_limited_returns_429(email_client, monkeypatch):
    monkeypatch.setattr(config.settings, "RATE_LIMIT_AUTH", "2/60")

    for _ in range(2):
        resp = await email_client.post(
            "/v1/auth/password/forgot", json={"email": "nobody-here@example.com"}
        )
        assert resp.status_code == 202

    resp = await email_client.post(
        "/v1/auth/password/forgot", json={"email": "nobody-here@example.com"}
    )
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1


async def test_password_reset_rate_limited_returns_429(client, monkeypatch):
    monkeypatch.setattr(config.settings, "RATE_LIMIT_AUTH", "2/60")

    for _ in range(2):
        resp = await client.post(
            "/v1/auth/password/reset",
            json={"token": "bogus", "new_password": "whatever-8chars"},
        )
        assert resp.status_code == 400

    resp = await client.post(
        "/v1/auth/password/reset",
        json={"token": "bogus", "new_password": "whatever-8chars"},
    )
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1


async def test_verify_confirm_rate_limited_returns_429(client, monkeypatch):
    monkeypatch.setattr(config.settings, "RATE_LIMIT_AUTH", "2/60")

    for _ in range(2):
        resp = await client.post("/v1/auth/verify/confirm", json={"token": "bogus"})
        assert resp.status_code == 400

    resp = await client.post("/v1/auth/verify/confirm", json={"token": "bogus"})
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1


async def test_verify_request_rate_limited_returns_429(email_client, monkeypatch):
    # Register + log in against the default (generous) limit first, then reset
    # the limiter so those two hits don't eat into the tight budget below.
    await email_client.post(
        "/v1/auth/register", json=_register_payload("rl-verify-req", "rl-verify-req@example.com")
    )
    login = await email_client.post(
        "/v1/auth/login", json={"username": "rl-verify-req", "password": "s3cret-password"}
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    get_rate_limiter().reset()

    monkeypatch.setattr(config.settings, "RATE_LIMIT_AUTH", "2/60")

    for _ in range(2):
        resp = await email_client.post("/v1/auth/verify/request", headers=headers)
        assert resp.status_code == 202

    resp = await email_client.post("/v1/auth/verify/request", headers=headers)
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1
