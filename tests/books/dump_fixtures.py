"""Access to the recorded Open Library dump fragment (feature 87).

The fragment lives in ``tests/books/fixtures/openlibrary_dump/`` and every line
in it is a **verbatim** line of a real monthly dump (2026-08-31), plus the
``search.json`` docs of the same works.  See the ``README.md`` next to the
files for provenance and for what each record is there to prove.

This helper is not a test module: it only locates and reads the fixture so the
two test modules that consume it do not each grow their own copy of the
plumbing.
"""

import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "openlibrary_dump"

# The five works the fragment is built around, and what each one is there for.
WORK_LOVE_HYPOTHESIS = "OL24178205W"  # English, ddc + lcc -> literature/fiction
WORK_CANT_HURT_ME = "OL18108064W"  # English, no ddc, multi-class lcc
WORK_SUMMER_TRILOGY = "OL17508740W"  # English, neither ddc nor lcc
WORK_PSICOLOGIA_OSCURA = "OL24456878W"  # Spanish stream
WORK_ULTRAMARATHON = "OL8960135W"  # whitelisted (19) but under the English floor

TARGET_WORKS = (
    WORK_LOVE_HYPOTHESIS,
    WORK_CANT_HURT_ME,
    WORK_SUMMER_TRILOGY,
    WORK_PSICOLOGIA_OSCURA,
    WORK_ULTRAMARATHON,
)


def read_lines(name: str) -> list[str]:
    """All lines of one fixture file, newline stripped."""
    return (FIXTURE_DIR / name).read_text(encoding="utf-8").splitlines()


def reading_log_lines() -> list[str]:
    return read_lines("reading_log.tsv")


def edition_lines() -> list[str]:
    return read_lines("editions.tsv")


def work_lines() -> list[str]:
    return read_lines("works.tsv")


def author_lines() -> list[str]:
    return read_lines("authors.tsv")


def search_docs() -> dict[str, dict]:
    """``search.json`` docs of the target works, keyed by work id."""
    return json.loads((FIXTURE_DIR / "search_docs.json").read_text(encoding="utf-8"))


def line_with(lines: list[str], needle: str) -> str:
    """The single fixture line containing *needle* (fails loudly if not unique)."""
    matches = [line for line in lines if needle in line]
    assert len(matches) == 1, f"expected exactly one line with {needle!r}, got {len(matches)}"
    return matches[0]
