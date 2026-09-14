"""Feature 79 — the Wikidata SPARQL client, against mocked responses only.

No test here touches the network: every SPARQL answer is a canned
``application/sparql-results+json`` payload, which is what the acceptance list
asks for ("tests con respuestas SPARQL mockeadas").  The payload shapes are
copies of real answers from ``query.wikidata.org`` taken on 2026-09-14 —
*The Shining* (film ``Q186341`` -> novel ``Q470937`` via ``P144``) and
*The Matrix* (``Q83495`` -> ``Q335340`` via ``P4969``).

Covered:
- the anchor query asks **by external identifier**: the ids travel verbatim in
  a ``VALUES`` block bound to the type's property, and no title or label
  appears anywhere in the query;
- each item type is asked with its own property, and GAME uses the *numeric*
  ``P9043`` rather than the slug-valued ``P5794``;
- an id Wikidata does not know about is simply absent from the answer (no
  fallback of any kind);
- an id claimed by two entities comes back as two QIDs, so the caller can
  refuse the ambiguity instead of the adapter picking one;
- the relations query asks both properties for a batch of subjects, and the
  property is read back from the answer as ``P144``/``P4969``;
- bindings that are not item entities (a statement node, a literal) are
  dropped rather than crashing the pass;
- the identifying ``User-Agent`` is sent (WDQS blocks generic clients) and the
  request is a POST, because a 500-id ``VALUES`` block does not fit in a URL;
- an id that could not be a real identifier is refused before it can reach a
  SPARQL literal;
- an empty batch issues no request at all;
- every request goes through the shared ``RequestPacer`` (the issue #26 policy
  applied to the second paced source).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backlogg.recommendations.adapters.wikidata import (
    _WD_MAX_RPS,
    ANCHOR_PROPERTIES,
    RELATION_PROPERTIES,
    WikidataClient,
    is_qid,
)
from backlogg.shared.pacing import RequestPacer

_ENTITY = "http://www.wikidata.org/entity/"
_PROP = "http://www.wikidata.org/prop/direct/"


def _mock_response(status_code: int, json_data: dict | None = None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.json = MagicMock(return_value=json_data or {})
    if status_code >= 400:
        response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                f"HTTP {status_code}", request=MagicMock(), response=response
            )
        )
    else:
        response.raise_for_status = MagicMock()
    return response


def _results(*bindings: dict) -> dict:
    return {"head": {"vars": []}, "results": {"bindings": list(bindings)}}


def _anchor_binding(qid: str, external_id: str) -> dict:
    return {
        "item": {"type": "uri", "value": f"{_ENTITY}{qid}"},
        "ext": {"type": "literal", "value": external_id},
    }


def _relation_binding(from_qid: str, property_id: str, to_qid: str) -> dict:
    return {
        "from": {"type": "uri", "value": f"{_ENTITY}{from_qid}"},
        "prop": {"type": "uri", "value": f"{_PROP}{property_id}"},
        "to": {"type": "uri", "value": f"{_ENTITY}{to_qid}"},
    }


def _fake_client(payload: dict, captured: dict):
    class FakeClient:
        def __init__(self, **kwargs):
            captured["headers"] = kwargs.get("headers")
            captured["timeout"] = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, data=None):
            captured["url"] = url
            captured["query"] = (data or {}).get("query", "")
            return _mock_response(200, payload)

    return FakeClient


# ── The anchor query is by external id, never by title ───────────────────────


@pytest.mark.asyncio
async def test_anchor_query_binds_the_external_ids_verbatim():
    captured: dict = {}
    payload = _results(_anchor_binding("Q186341", "694"), _anchor_binding("Q83495", "603"))

    with patch(
        "backlogg.recommendations.adapters.wikidata.httpx.AsyncClient",
        _fake_client(payload, captured),
    ):
        resolved = await WikidataClient().resolve_qids("P4947", ["694", "603", "42424242"])

    query = captured["query"]
    assert "VALUES ?ext" in query
    assert '"694"' in query and '"603"' in query and '"42424242"' in query
    assert "wdt:P4947" in query
    # The whole point of this source: nothing in the query is a name.
    for forbidden in ("rdfs:label", "?title", "skos:altLabel", "wikibase:label"):
        assert forbidden not in query

    assert resolved == {"694": ["Q186341"], "603": ["Q83495"]}
    # The id Wikidata does not carry is absent — no title fallback, no guess.
    assert "42424242" not in resolved


@pytest.mark.asyncio
async def test_each_item_type_uses_its_own_property_and_games_use_the_numeric_id():
    """``P5794`` is the IGDB *slug*; this catalog's game identity is the number."""
    assert ANCHOR_PROPERTIES["MOVIE"] == ("TMDB", "P4947")
    assert ANCHOR_PROPERTIES["SERIES"] == ("TMDB", "P4983")
    assert ANCHOR_PROPERTIES["BOOK"] == ("OPEN_LIBRARY", "P648")
    assert ANCHOR_PROPERTIES["GAME"] == ("IGDB", "P9043")
    assert all(prop != "P5794" for _, prop in ANCHOR_PROPERTIES.values())

    captured: dict = {}
    with patch(
        "backlogg.recommendations.adapters.wikidata.httpx.AsyncClient",
        _fake_client(_results(), captured),
    ):
        await WikidataClient().resolve_qids(ANCHOR_PROPERTIES["BOOK"][1], ["OL27448W"])
    assert "wdt:P648" in captured["query"]
    assert '"OL27448W"' in captured["query"]


@pytest.mark.asyncio
async def test_an_id_claimed_by_two_entities_comes_back_as_two_qids():
    """Ambiguity is surfaced, not resolved: the adapter must not pick a winner."""
    captured: dict = {}
    payload = _results(_anchor_binding("Q1", "694"), _anchor_binding("Q2", "694"))

    with patch(
        "backlogg.recommendations.adapters.wikidata.httpx.AsyncClient",
        _fake_client(payload, captured),
    ):
        resolved = await WikidataClient().resolve_qids("P4947", ["694"])

    assert resolved == {"694": ["Q1", "Q2"]}


@pytest.mark.asyncio
async def test_unsafe_external_ids_never_reach_a_sparql_literal():
    captured: dict = {}
    with patch(
        "backlogg.recommendations.adapters.wikidata.httpx.AsyncClient",
        _fake_client(_results(), captured),
    ):
        await WikidataClient().resolve_qids("P4947", ['694" } UNION { ?item ?p ?o', "603"])

    assert "UNION" not in captured["query"]
    assert '"603"' in captured["query"]


@pytest.mark.asyncio
async def test_an_empty_batch_issues_no_request():
    with patch(
        "backlogg.recommendations.adapters.wikidata.httpx.AsyncClient.post",
        new_callable=AsyncMock,
    ) as mock_post:
        client = WikidataClient()
        assert await client.resolve_qids("P4947", []) == {}
        assert await client.fetch_relations([]) == []
        assert await client.fetch_relations(["not-a-qid", "P31"]) == []
        mock_post.assert_not_called()


# ── The relations query ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_relations_query_asks_both_properties_for_the_batch_of_subjects():
    captured: dict = {}
    payload = _results(
        _relation_binding("Q186341", "P144", "Q470937"),
        _relation_binding("Q83495", "P4969", "Q335340"),
    )

    with patch(
        "backlogg.recommendations.adapters.wikidata.httpx.AsyncClient",
        _fake_client(payload, captured),
    ):
        statements = await WikidataClient().fetch_relations(["Q186341", "Q83495"])

    query = captured["query"]
    assert "wd:Q186341" in query and "wd:Q83495" in query
    assert "wdt:P144" in query and "wdt:P4969" in query

    assert [(s.from_qid, s.property_id, s.to_qid) for s in statements] == [
        ("Q186341", "P144", "Q470937"),
        ("Q83495", "P4969", "Q335340"),
    ]
    assert RELATION_PROPERTIES["P144"] == "ADAPTATION"
    assert RELATION_PROPERTIES["P4969"] == "DERIVATIVE"


@pytest.mark.asyncio
async def test_bindings_that_are_not_item_entities_are_dropped():
    """A statement node or a literal on either end is data noise, not a crash."""
    captured: dict = {}
    payload = _results(
        _relation_binding("Q186341", "P144", "Q470937"),
        {
            "from": {"type": "uri", "value": f"{_ENTITY}Q186341"},
            "prop": {"type": "uri", "value": f"{_PROP}P144"},
            "to": {"type": "literal", "value": "The Shining"},
        },
        {
            "from": {"type": "uri", "value": "http://www.wikidata.org/entity/statement/Q1-abc"},
            "prop": {"type": "uri", "value": f"{_PROP}P144"},
            "to": {"type": "uri", "value": f"{_ENTITY}Q2"},
        },
    )

    with patch(
        "backlogg.recommendations.adapters.wikidata.httpx.AsyncClient",
        _fake_client(payload, captured),
    ):
        statements = await WikidataClient().fetch_relations(["Q186341"])

    assert len(statements) == 1
    assert statements[0].to_qid == "Q470937"


# ── Politeness ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_requests_identify_themselves_and_are_posted():
    """WDQS blocks generic clients, and a 500-id VALUES block does not fit a URL."""
    captured: dict = {}
    with patch(
        "backlogg.recommendations.adapters.wikidata.httpx.AsyncClient",
        _fake_client(_results(), captured),
    ):
        await WikidataClient().resolve_qids("P4947", ["694"])

    user_agent = captured["headers"]["User-Agent"]
    assert "backlogg" in user_agent
    assert "contact@backlogg.app" in user_agent
    assert captured["headers"]["Accept"] == "application/sparql-results+json"
    assert captured["url"] == "https://query.wikidata.org/sparql"


@pytest.mark.asyncio
async def test_transient_failures_are_retried_and_a_400_is_not():
    """400 means the query itself is wrong; re-sending it burns the endpoint."""
    ok = _mock_response(200, _results(_anchor_binding("Q186341", "694")))
    responses = [_mock_response(503), _mock_response(503), ok]

    with (
        patch(
            "backlogg.recommendations.adapters.wikidata.httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=responses,
        ) as mock_post,
        patch("tenacity.nap.time.sleep"),
    ):
        resolved = await WikidataClient().resolve_qids("P4947", ["694"])
    assert resolved == {"694": ["Q186341"]}
    assert mock_post.await_count == 3

    with (
        patch(
            "backlogg.recommendations.adapters.wikidata.httpx.AsyncClient.post",
            new_callable=AsyncMock,
            return_value=_mock_response(400),
        ) as mock_post,
        patch("tenacity.nap.time.sleep"),
        pytest.raises(httpx.HTTPStatusError),
    ):
        await WikidataClient().resolve_qids("P4947", ["694"])
    assert mock_post.await_count == 1


# ── Small helpers ────────────────────────────────────────────────────────────


def test_is_qid_accepts_items_only():
    assert is_qid("Q42")
    assert is_qid("Q186341")
    assert not is_qid("P144")
    assert not is_qid("Q0")
    assert not is_qid("L1234")
    assert not is_qid("")


@pytest.mark.asyncio
async def test_every_request_goes_through_the_shared_pacer():
    """Issue #26's policy, applied to the second paced source.

    The global ``_disable_wikidata_pacing`` fixture zeroes the interval for the
    rest of the suite, so this test installs its own pacer with an injected
    clock — no real time is spent and the assertion is about spacing, not
    about wall clock.
    """

    class _FakeClock:
        def __init__(self) -> None:
            self.now = 1000.0
            self.sleeps: list[float] = []

        def __call__(self) -> float:
            return self.now

        async def sleep(self, seconds: float) -> None:
            self.sleeps.append(seconds)
            self.now += seconds

    clock = _FakeClock()
    pacer = RequestPacer(_WD_MAX_RPS, clock=clock, sleep=clock.sleep)
    captured: dict = {}

    with (
        patch("backlogg.recommendations.adapters.wikidata._wd_pacer", pacer),
        patch(
            "backlogg.recommendations.adapters.wikidata.httpx.AsyncClient",
            _fake_client(_results(), captured),
        ),
    ):
        client = WikidataClient()
        await client.resolve_qids("P4947", ["1"])
        await client.resolve_qids("P4947", ["2"])
        await client.fetch_relations(["Q1"])

    # First request is free; the two that follow are spaced by 1/rps.
    assert clock.sleeps == [pytest.approx(1.0 / _WD_MAX_RPS), pytest.approx(1.0 / _WD_MAX_RPS)]
    assert _WD_MAX_RPS <= 1.0
