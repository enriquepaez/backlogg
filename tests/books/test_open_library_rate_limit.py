"""Issue #26 — the Open Library adapter paces itself at 3 req/s.

Open Library's published policy (openlibrary.org/developers/api, edited
2026-05-05) allows 1 req/s to an anonymous client and 3 req/s to one that
identifies itself with an app name and a contact address. The identification
half has been in place since the adapter was written (``_OL_HEADERS``); this
module covers the half that was missing — the pacing.

Covered here:
- the pacer lets the first call through immediately and spaces the ones that
  follow by exactly ``1/3`` s, measured on an injected clock
- a *concurrent* burst (the shape the on-demand path actually produces: one
  ``/authors/{olid}.json`` per author, gathered) is spaced too — each caller
  reserves a distinct slot instead of all of them reading the same "now"
- a caller that arrives after a long idle stretch pays nothing
- ``_OL_MAX_RPS`` is 3, not 1: the identifying User-Agent is what buys the
  higher allowance, so the two must stay together
- the four request-issuing methods of ``OpenLibraryClient`` — ``search_book``,
  ``get_works_by_ids``, ``get_work_detail`` and ``get_author`` — all go
  through the pacer
- ``get_author``'s internal timeout retry is paced as well: a retry is a new
  request against the source's budget
- the pacer does not consume ``asyncio.sleep``: it captures it at
  construction, so the adapter tests that patch ``asyncio.sleep`` to count
  tenacity backoffs keep counting only backoffs
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backlogg.books.adapters import open_library as ol_adapter
from backlogg.books.adapters.open_library import _OL_MAX_RPS, OpenLibraryClient, _RequestPacer


class _FakeClock:
    """Monotonic clock that only advances when a sleep is awaited.

    The sleep yields to the event loop *before* advancing the clock, which is
    what makes the concurrent case honest: every coroutine of a burst gets to
    reserve its slot against the same "now", exactly as it would against the
    real one.
    """

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        target = self.now + seconds
        await asyncio.sleep(0)
        self.now = max(self.now, target)


def _pacer(clock: _FakeClock, rps: float = _OL_MAX_RPS) -> _RequestPacer:
    return _RequestPacer(rps, clock=clock, sleep=clock.sleep)


# ── The pacer itself ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_request_is_not_delayed():
    clock = _FakeClock()
    pacer = _pacer(clock)

    await pacer.wait()

    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_sequential_requests_are_spaced_by_one_third_of_a_second():
    clock = _FakeClock()
    pacer = _pacer(clock)

    for _ in range(4):
        await pacer.wait()

    # Four requests, three waits: 3 req/s means one slot every 1/3 s.
    assert len(clock.sleeps) == 3
    assert all(delay == pytest.approx(1 / 3) for delay in clock.sleeps)


@pytest.mark.asyncio
async def test_a_concurrent_burst_is_spaced_too():
    """The on-demand shape: several requests fired at once, not in a loop.

    Every caller reads the same ``now``; what keeps them apart is that each
    one *reserves* its slot before awaiting.
    """
    clock = _FakeClock()
    pacer = _pacer(clock)

    await asyncio.gather(*(pacer.wait() for _ in range(4)))

    assert sorted(clock.sleeps) == [
        pytest.approx(1 / 3),
        pytest.approx(2 / 3),
        pytest.approx(1.0),
    ]


@pytest.mark.asyncio
async def test_an_idle_stretch_costs_nothing():
    clock = _FakeClock()
    pacer = _pacer(clock)

    await pacer.wait()
    clock.now += 60.0
    await pacer.wait()

    assert clock.sleeps == []


@pytest.mark.asyncio
async def test_a_zero_rate_disables_the_pacer():
    """The switch the test suite's autouse fixture flips — no sleep at all."""
    clock = _FakeClock()
    pacer = _pacer(clock, rps=0)

    await pacer.wait()
    await pacer.wait()

    assert clock.sleeps == []


def test_the_rate_is_the_identified_one():
    """3 req/s, the allowance the identifying User-Agent buys — not 1."""
    assert _OL_MAX_RPS == 3.0
    assert "backlogg" in ol_adapter._OL_HEADERS["User-Agent"]
    assert "@" in ol_adapter._OL_HEADERS["User-Agent"]


# ── Every request-issuing method goes through it ─────────────────────────────


class _RecordingPacer:
    """Stand-in that counts ``wait`` calls without sleeping."""

    def __init__(self) -> None:
        self.calls = 0
        self.min_interval = 1 / 3

    async def wait(self) -> None:
        self.calls += 1

    def reset(self) -> None:
        self.calls = 0


def _mock_response(status_code: int, json_data: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"{status_code}", request=MagicMock(), response=response
        )
    else:
        response.raise_for_status.return_value = None
    return response


def _client_patch(response):
    """Patch ``httpx.AsyncClient`` so no request leaves the process."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=response)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return patch("httpx.AsyncClient", return_value=ctx), mock_client


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call,payload",
    [
        (lambda c: c.search_book("dune"), {"docs": []}),
        (lambda c: c.get_works_by_ids(["OL82563W"]), {"docs": [], "numFound": 0}),
        (lambda c: c.get_work_detail("OL82563W"), {"title": "Dune"}),
        (lambda c: c.get_author("OL22242A"), {"name": "Frank Herbert"}),
    ],
    ids=["search_book", "get_works_by_ids", "get_work_detail", "get_author"],
)
async def test_every_request_method_asks_the_pacer_first(monkeypatch, call, payload):
    pacer = _RecordingPacer()
    monkeypatch.setattr(ol_adapter, "_ol_pacer", pacer)
    client_patch, _ = _client_patch(_mock_response(200, payload))

    with client_patch:
        await call(OpenLibraryClient())

    assert pacer.calls == 1


@pytest.mark.asyncio
async def test_get_author_pays_the_pacer_on_every_retry(monkeypatch):
    """A retry is another request against the source's budget, not a free one."""
    pacer = _RecordingPacer()
    monkeypatch.setattr(ol_adapter, "_ol_pacer", pacer)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_client)
    ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=ctx):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await OpenLibraryClient().get_author("OL22242A")

    assert result is None
    assert pacer.calls == 3


@pytest.mark.asyncio
async def test_the_pacer_does_not_show_up_in_patched_asyncio_sleep():
    """``asyncio.sleep`` is captured at construction, not looked up per call.

    Several adapter tests patch ``asyncio.sleep`` globally and assert on the
    number of tenacity backoffs; a pacer that resolved the name at call time
    would silently inflate those counts.
    """
    pacer = _RequestPacer(_OL_MAX_RPS)

    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await pacer.wait()
        await pacer.wait()

    assert mock_sleep.await_count == 0
