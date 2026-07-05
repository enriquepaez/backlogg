"""Tests for the test-DB isolation guard defined in tests/conftest.py.

The guard must abort the whole pytest run (via pytest.exit) whenever the
suite could end up touching the main database instead of the test one.
"""

import sys

import pytest
from _pytest.outcomes import Exit

from backlogg.core.config import settings
from tests.conftest import _db_identity, _enforce_test_db_isolation


def test_db_identity_extracts_host_and_dbname():
    host, path = _db_identity(
        "postgresql+asyncpg://user:secret@db.example.com/backlogg_test?sslmode=require"
    )
    assert host == "db.example.com"
    assert path == "/backlogg_test"


def test_guard_aborts_when_test_url_is_empty(monkeypatch):
    monkeypatch.setattr(settings, "TEST_DATABASE_URL", "   ")
    with pytest.raises(Exit):
        _enforce_test_db_isolation()


def test_guard_aborts_when_test_url_equals_main_url(monkeypatch):
    url = "postgresql+asyncpg://user:secret@db.example.com/backlogg"
    monkeypatch.setattr(settings, "DATABASE_URL", url)
    monkeypatch.setattr(settings, "TEST_DATABASE_URL", url)
    with pytest.raises(Exit):
        _enforce_test_db_isolation()


def test_guard_aborts_when_same_db_despite_query_params(monkeypatch):
    """Cosmetic URL differences (query params) must not defeat the guard."""
    monkeypatch.setattr(
        settings, "DATABASE_URL", "postgresql+asyncpg://u:p@host/backlogg?sslmode=require"
    )
    monkeypatch.setattr(settings, "TEST_DATABASE_URL", "postgresql+asyncpg://u:p@host/backlogg")
    with pytest.raises(Exit):
        _enforce_test_db_isolation()


def test_guard_passes_with_distinct_databases(monkeypatch):
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://u:p@host/backlogg")
    monkeypatch.setattr(
        settings, "TEST_DATABASE_URL", "postgresql+asyncpg://u:p@host/backlogg_test"
    )
    # backlogg.core.database is legitimately imported by the running suite;
    # the import-order check only applies at conftest import time.
    monkeypatch.delitem(sys.modules, "backlogg.core.database", raising=False)
    _enforce_test_db_isolation()  # must not raise


def test_guard_aborts_when_database_module_already_imported(monkeypatch):
    """If backlogg.core.database was imported before the override, abort."""
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://u:p@host/backlogg")
    monkeypatch.setattr(
        settings, "TEST_DATABASE_URL", "postgresql+asyncpg://u:p@host/backlogg_test"
    )
    monkeypatch.setitem(sys.modules, "backlogg.core.database", object())
    with pytest.raises(Exit):
        _enforce_test_db_isolation()
