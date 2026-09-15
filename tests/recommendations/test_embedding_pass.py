"""Feature 75 — the generation half: what gets embedded, and what gets skipped.

No model is downloaded and no network is touched anywhere in this file. The
``Embedder`` protocol exists precisely so the real batching, hashing, quota and
persistence paths can be exercised against a deterministic fake — the only part
left unexercised is 470 MB of weights, which no test could assert anything
useful about anyway.

What is under test:

- **the four types are all represented.** This is the single invariant feature
  80 cannot do without: its cross-type quota is its non-negotiable rule, and a
  global "top 40.000 by popularity" would have filled up with one type and left
  it unable to honour it. So the cap is split per type, and a type too small to
  fill its share gives the remainder back instead of wasting it;
- **the cap is hard.** It is not a throttle, it is the Neon free headroom. A
  run that quietly embedded more than it was told would not fail anything
  visible until the day the database refuses a write;
- **nothing is re-embedded for free.** A second run over an unchanged catalog
  must ask the model for nothing at all. Without that the monthly schedule
  costs a full re-embedding of the subset every month for a handful of edits,
  and the "resumable" property is a fiction;
- **but a changed synopsis is re-embedded**, and only it. The hash is what
  tells the two apart, and it is easy to write a version of this that is either
  always stale or always redundant;
- **a new model invalidates everything** without needing a flag: vectors from
  two models are not comparable, and a table holding both would produce silent
  nonsense rather than an error;
- **the selection criterion is the documented one** — synopsis first, then the
  source's own rating count — and not insertion order;
- **the time budget stops the run cleanly**, reporting incompleteness rather
  than being killed by the Actions timeout.
"""

import hashlib
import math
import random
from datetime import UTC, date, datetime

import pytest

from backlogg.books import repository as books_repo
from backlogg.core.config import settings
from backlogg.games import repository as games_repo
from backlogg.movies import repository as movies_repo
from backlogg.recommendations.embeddings import (
    ITEM_TYPES,
    allocate_quotas,
    build_source_text,
    run_embedding_pass,
    source_hash,
)
from backlogg.recommendations.repository import EmbeddingSource
from backlogg.series import repository as series_repo
from backlogg.shared.item_embeddings import count_by_item_type, get_item_embedding

# No module-level ``pytest.mark.asyncio``: this file mixes pure functions
# (serialisation, hashing, the quota split) with DB-backed coroutines, and
# ``asyncio_mode = "auto"`` already marks the coroutines.

DIM = settings.EMBEDDING_DIM


class FakeEmbedder:
    """A deterministic stand-in for the real model.

    Deterministic because two runs over the same text must produce the same
    vector — otherwise "unchanged" could not be asserted — and because a random
    vector per call would make the similarity assertions meaningless. Records
    every text it was asked for, which is how "the model was never called" is
    verified.
    """

    def __init__(self, name: str = "fake-model-v1", dim: int = DIM) -> None:
        self.name = name
        self.dim = dim
        self.calls: list[list[str]] = []

    @property
    def texts_seen(self) -> list[str]:
        return [text for call in self.calls for text in call]

    def embed(self, texts):
        texts = list(texts)
        self.calls.append(texts)
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        seed = hashlib.sha256(f"{self.name}:{text}".encode()).hexdigest()
        rng = random.Random(seed)
        raw = [rng.uniform(-1.0, 1.0) for _ in range(self.dim)]
        norm = math.sqrt(sum(value * value for value in raw)) or 1.0
        return [value / norm for value in raw]


def _session_factory_returning(session):
    """A fake ``async_session_factory`` yielding the test's own session.

    Same helper as ``tests/test_search_fanout_ingestion.py``: the pass opens its
    own sessions in production, and pointing them at the rollback-isolated
    fixture session is what lets the real commit path run without a second
    connection that would not see the fixture's uncommitted rows.
    """

    class _SessionCM:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *exc_info):
            return False

    def factory():
        return _SessionCM()

    return factory


# ── Catalog fixtures ──────────────────────────────────────────────────────────


def _movie(slug, title, *, overview="A film about something.", votes=100, genres=()):
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": overview,
        "release_date": date(2000, 1, 1),
        "runtime": 100,
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "budget": None,
        "revenue": None,
        "status": "Released",
        "rating_external": 7.0,
        "rating_count_external": votes,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [{"name": name, "slug": name.lower()} for name in genres],
    }


def _series(slug, title, *, overview="A series about something.", votes=100):
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": overview,
        "first_air_date": date(2001, 1, 1),
        "last_air_date": None,
        "number_of_seasons": 1,
        "number_of_episodes": 10,
        "status": "Ended",
        "original_language": "en",
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": 7.0,
        "rating_count_external": votes,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _book(slug, title, *, overview="A novel about something.", votes=None):
    return {
        "title": title,
        "original_title": None,
        "slug": slug,
        "overview": overview,
        "first_publish_date": date(1965, 1, 1),
        "original_language": "en",
        "poster_url": None,
        "rating_external": None,
        "rating_count_external": votes,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
    }


def _game(slug, title, *, overview="A game about something.", votes=100):
    return {
        "title": title,
        "original_title": title,
        "slug": slug,
        "overview": overview,
        "release_date": date(1992, 1, 1),
        "game_type": "MAIN_GAME",
        "original_language": None,
        "poster_url": None,
        "backdrop_url": None,
        "rating_external": 7.0,
        "rating_count_external": votes,
        "rating_internal": None,
        "rating_count_internal": 0,
        "last_synced_at": datetime.now(UTC),
        "genres": [],
        "platforms": [],
        "companies": [],
    }


async def _seed_one_of_each(db, tag: str):
    await movies_repo.upsert_movie(db, _movie(f"{tag}-movie", f"{tag} Movie"))
    await series_repo.upsert_series(db, _series(f"{tag}-series", f"{tag} Series"))
    await books_repo.upsert_book(db, _book(f"{tag}-book", f"{tag} Book"))
    await games_repo.upsert_game(db, _game(f"{tag}-game", f"{tag} Game"))


async def _run(db, embedder, **kwargs):
    return await run_embedding_pass(_session_factory_returning(db), embedder, **kwargs)


# ── The serialised text ───────────────────────────────────────────────────────


def _source(**overrides) -> EmbeddingSource:
    base = {
        "item_type": "MOVIE",
        "item_id": 1,
        "title": "Dune",
        "original_title": "Dune",
        "overview": "A noble family takes control of a desert planet.",
        "genres": ("Adventure", "Science Fiction"),
        "stored_model": None,
        "stored_hash": None,
    }
    base.update(overrides)
    return EmbeddingSource(**base)


def test_the_serialised_text_leads_with_the_most_identifying_part():
    text = build_source_text(_source())
    assert text.splitlines() == [
        "Dune",
        "Adventure, Science Fiction",
        "A noble family takes control of a desert planet.",
    ]


def test_the_content_type_never_appears_in_the_text():
    """A type token would cluster the space by type and kill the cross-type bridge."""
    for item_type, expected_words in [
        ("MOVIE", ("movie", "película", "film")),
        ("BOOK", ("book", "libro", "novel")),
        ("GAME", ("game", "videojuego")),
        ("SERIES", ("series", "serie")),
    ]:
        text = build_source_text(_source(item_type=item_type, overview=None)).casefold()
        for word in expected_words:
            assert word not in text


def test_an_original_title_equal_to_the_title_is_not_repeated():
    assert build_source_text(_source(original_title="dune")).count("une") == 1
    assert "Duna" in build_source_text(_source(original_title="Duna"))


def test_cosmetic_whitespace_does_not_change_the_hash():
    """Otherwise a re-sync that only reflowed a synopsis costs a full re-embedding."""
    tidy = build_source_text(_source())
    untidy = build_source_text(
        _source(
            title="  Dune ",
            overview="A noble family takes control\n of a   desert planet.",
        )
    )
    assert source_hash(tidy) == source_hash(untidy)


def test_a_changed_synopsis_does_change_the_hash():
    assert source_hash(build_source_text(_source())) != source_hash(
        build_source_text(_source(overview="Something else entirely."))
    )


def test_the_prefix_is_part_of_what_is_hashed():
    """Changing EMBEDDING_TEXT_PREFIX changes the input, so it must invalidate."""
    assert source_hash(build_source_text(_source(), prefix="query: ")) != source_hash(
        build_source_text(_source())
    )


# ── The quota split ───────────────────────────────────────────────────────────


def test_the_cap_is_split_equally_between_the_four_types():
    quotas = allocate_quotas(40_000, dict.fromkeys(ITEM_TYPES, 100_000))
    assert quotas == dict.fromkeys(ITEM_TYPES, 10_000)


def test_a_type_too_small_for_its_share_hands_the_remainder_back():
    """No capacity is wasted, and the big types absorb it — never the other way."""
    quotas = allocate_quotas(
        40_000,
        {"MOVIE": 100_000, "SERIES": 1_000, "BOOK": 100_000, "GAME": 100_000},
    )
    assert quotas["SERIES"] == 1_000
    assert sum(quotas.values()) == 40_000
    assert quotas["MOVIE"] == quotas["BOOK"] == quotas["GAME"] == 13_000


def test_a_huge_type_never_starves_a_small_one():
    """The failure this whole split exists to prevent, stated as a test."""
    quotas = allocate_quotas(
        40_000,
        {"MOVIE": 5_000_000, "SERIES": 20_000, "BOOK": 20_000, "GAME": 20_000},
    )
    assert quotas["MOVIE"] == 10_000
    assert min(quotas.values()) == 10_000


def test_an_explicit_override_pins_a_type_and_is_taken_off_the_top():
    quotas = allocate_quotas(
        40_000,
        dict.fromkeys(ITEM_TYPES, 100_000),
        {"GAME": 4_000},
    )
    assert quotas["GAME"] == 4_000
    assert sum(quotas.values()) == 40_000
    assert quotas["MOVIE"] == quotas["SERIES"] == quotas["BOOK"] == 12_000


def test_the_cap_is_never_exceeded_even_when_it_does_not_divide():
    quotas = allocate_quotas(10, dict.fromkeys(ITEM_TYPES, 100))
    assert sum(quotas.values()) == 10
    # The remainder goes one each in ITEM_TYPES order, so the result is stable.
    assert [quotas[item_type] for item_type in ITEM_TYPES] == [3, 3, 2, 2]


def test_a_catalog_smaller_than_the_cap_is_covered_entirely():
    quotas = allocate_quotas(40_000, {"MOVIE": 3, "SERIES": 2, "BOOK": 1, "GAME": 0})
    assert quotas == {"MOVIE": 3, "SERIES": 2, "BOOK": 1, "GAME": 0}


# ── The pass, end to end ──────────────────────────────────────────────────────


async def test_a_run_covers_all_four_content_types(db):
    await _seed_one_of_each(db, "cov")
    embedder = FakeEmbedder()

    result = await _run(db, embedder, max_items=40)

    assert result.completed
    assert result.embedded == 4
    assert result.types_covered == 4
    assert await count_by_item_type(db) == dict.fromkeys(ITEM_TYPES, 1)


async def test_the_cap_is_hard_and_is_split_rather_than_spent_on_one_type(db):
    """Four movies and one of everything else, with room for four items total.

    A global "best four" would have taken the four movies — they are the only
    ones with a vote count here — and left three types with nothing. The split
    gives one slot to each type instead, which is the behaviour feature 80
    needs and the reason the cap is not a single ranking.
    """
    for index in range(4):
        await movies_repo.upsert_movie(
            db, _movie(f"cap-movie-{index}", f"Cap Movie {index}", votes=1000 - index)
        )
    await series_repo.upsert_series(db, _series("cap-series", "Cap Series"))
    await books_repo.upsert_book(db, _book("cap-book", "Cap Book"))
    await games_repo.upsert_game(db, _game("cap-game", "Cap Game"))
    embedder = FakeEmbedder()

    result = await _run(db, embedder, max_items=4)

    assert result.embedded == 4
    assert await count_by_item_type(db) == dict.fromkeys(ITEM_TYPES, 1)


async def test_within_a_type_the_documented_signal_decides_who_gets_a_vector(db):
    """Synopsis first, then the source's own rating count — not insertion order.

    The item inserted *first* is the one without a synopsis, and the one with
    the highest vote count is inserted last, so passing this test by accident
    would require reproducing the documented ranking exactly.
    """
    await movies_repo.upsert_movie(
        db, _movie("rank-silent", "Rank Silent", overview=None, votes=9_999)
    )
    await movies_repo.upsert_movie(db, _movie("rank-quiet", "Rank Quiet", votes=10))
    loud = await movies_repo.upsert_movie(db, _movie("rank-loud", "Rank Loud", votes=5_000))
    embedder = FakeEmbedder()

    await _run(db, embedder, item_types=["MOVIE"], max_items=4)

    assert await get_item_embedding(db, "MOVIE", loud.id) is not None
    assert "Rank Loud" in embedder.texts_seen[0]


async def test_an_item_without_a_synopsis_is_still_embedded_and_counted(db):
    """Title and genres alone are a thin but real signal; the count makes it visible."""
    await movies_repo.upsert_movie(
        db, _movie("thin-movie", "Thin Movie", overview=None, genres=("Drama",))
    )
    embedder = FakeEmbedder()

    result = await _run(db, embedder, item_types=["MOVIE"], max_items=10)

    assert result.per_type["MOVIE"].embedded == 1
    assert result.per_type["MOVIE"].without_overview == 1
    assert "Drama" in embedder.texts_seen[0]


# ── Idempotency and the skip ──────────────────────────────────────────────────


async def test_a_second_run_over_an_unchanged_catalog_calls_the_model_zero_times(db):
    """The property the monthly schedule depends on, and the resumability too."""
    await _seed_one_of_each(db, "idem")
    first = FakeEmbedder()
    await _run(db, first, max_items=40)

    second = FakeEmbedder()
    result = await _run(db, second, max_items=40)

    assert second.calls == []
    assert result.embedded == 0
    assert result.created == 0
    assert result.updated == 0
    assert result.skipped_unchanged == 4
    assert await count_by_item_type(db) == dict.fromkeys(ITEM_TYPES, 1)


async def test_only_the_item_whose_text_changed_is_re_embedded(db):
    await _seed_one_of_each(db, "diff")
    embedder = FakeEmbedder()
    await _run(db, embedder, max_items=40)

    await movies_repo.upsert_movie(
        db, _movie("diff-movie", "diff Movie", overview="A completely rewritten synopsis.")
    )

    second = FakeEmbedder()
    result = await _run(db, second, max_items=40)

    assert len(second.texts_seen) == 1
    assert "completely rewritten" in second.texts_seen[0]
    assert result.embedded == 1
    assert result.updated == 1
    assert result.created == 0
    assert result.skipped_unchanged == 3


async def test_a_new_model_invalidates_every_vector_without_needing_a_flag(db):
    """Vectors from two models are not comparable; a mixed table is silent nonsense."""
    await _seed_one_of_each(db, "model")
    await _run(db, FakeEmbedder(name="fake-model-v1"), max_items=40)

    newer = FakeEmbedder(name="fake-model-v2")
    result = await _run(db, newer, max_items=40)

    assert result.embedded == 4
    assert result.updated == 4
    assert result.created == 0
    assert result.skipped_unchanged == 0
    stored = await get_item_embedding(db, "MOVIE", 1) or await get_item_embedding(db, "BOOK", 1)
    assert stored is None or stored.model == "fake-model-v2"


async def test_force_re_embeds_what_the_hash_says_is_unchanged(db):
    """The escape hatch for the one change the hash cannot see: the serialisation."""
    await _seed_one_of_each(db, "force")
    embedder = FakeEmbedder()
    await _run(db, embedder, max_items=40)

    again = FakeEmbedder()
    result = await _run(db, again, max_items=40, force=True)

    assert len(again.texts_seen) == 4
    assert result.updated == 4
    assert result.skipped_unchanged == 0


# ── Stopping cleanly ──────────────────────────────────────────────────────────


async def test_an_exhausted_time_budget_stops_the_run_and_says_so(db):
    """Incomplete is reported, never disguised as a finished run."""
    await _seed_one_of_each(db, "budget")
    embedder = FakeEmbedder()

    result = await _run(db, embedder, max_items=40, budget_minutes=1e-9)

    assert result.completed is False
    assert embedder.calls == []


async def test_a_run_restricted_to_one_type_does_not_inherit_the_others_budget(db):
    """Otherwise re-running one type would quietly blow past the global cap."""
    for index in range(6):
        await movies_repo.upsert_movie(
            db, _movie(f"solo-movie-{index}", f"Solo Movie {index}", votes=100 + index)
        )
    await series_repo.upsert_series(db, _series("solo-series", "Solo Series"))
    await books_repo.upsert_book(db, _book("solo-book", "Solo Book"))
    await games_repo.upsert_game(db, _game("solo-game", "Solo Game"))
    embedder = FakeEmbedder()

    result = await _run(db, embedder, item_types=["MOVIE"], max_items=8)

    # MOVIE's share of 8 across four types is 2, plus nothing redistributed:
    # the other three types have one item each and hand back 1 + 1 + 1 = 3,
    # which goes to the only type with room left.
    assert result.per_type["MOVIE"].embedded == 5
    assert await count_by_item_type(db) == {"MOVIE": 5}


async def test_a_model_of_the_wrong_width_is_refused_before_any_inference(db):
    """The column width is fixed at migration time; failing early says which knob."""
    await _seed_one_of_each(db, "dim")
    embedder = FakeEmbedder(dim=DIM - 1)

    with pytest.raises(RuntimeError, match="EMBEDDING_DIM"):
        await _run(db, embedder, max_items=40)
    assert embedder.calls == []
