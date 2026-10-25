import logging

import pytest

from app.storage.database import (
    DatabaseConfigError,
    StorageError,
    prepare_engine_args,
)
from app.storage.factory import DatabaseRequiredError, create_store
from app.storage.store import MemoryPreferenceStore, SqlPreferenceStore
from tests.conftest import make_settings


async def test_missing_database_url_uses_memory_and_warns(caplog):
    caplog.set_level(logging.WARNING)

    store = await create_store(make_settings(database_url=None))

    assert isinstance(store, MemoryPreferenceStore)
    assert "LOST on restart" in caplog.text

    # Local development works without any credentials.
    await store.set_language(1, "en")
    assert await store.get_language(1) == "en"


async def test_require_database_refuses_to_start_without_url():
    with pytest.raises(DatabaseRequiredError):
        await create_store(
            make_settings(database_url=None, require_database=True)
        )


async def test_configured_database_uses_sql_store(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'f.db'}"

    store = await create_store(make_settings(database_url=url))

    assert isinstance(store, SqlPreferenceStore)
    await store.set_language(1, "ru")
    assert await store.get_language(1) == "ru"
    await store.close()


async def test_unreachable_database_does_not_stop_startup(
    tmp_path, caplog
):
    caplog.set_level(logging.ERROR)
    url = f"sqlite+aiosqlite:///{tmp_path / 'missing' / 'f.db'}"

    store = await create_store(make_settings(database_url=url))

    assert isinstance(store, SqlPreferenceStore)
    assert "unreachable" in caplog.text

    # ...but writes fail loudly instead of pretending to succeed.
    with pytest.raises(StorageError):
        await store.set_language(1, "ru")

    await store.close()


async def test_invalid_url_fails_fast_without_leaking_it(caplog):
    caplog.set_level(logging.ERROR)
    bad = "postgresql://user:SuperSecret@host:notaport/db"

    with pytest.raises(DatabaseConfigError) as raised:
        await create_store(make_settings(database_url=bad))

    assert "SuperSecret" not in str(raised.value)
    assert "SuperSecret" not in caplog.text


# --- URL handling -------------------------------------------------------


def test_postgres_scheme_is_converted_to_asyncpg():
    for scheme in ("postgres", "postgresql"):
        url, _ = prepare_engine_args(f"{scheme}://u:p@host:5432/db")
        assert url.drivername == "postgresql+asyncpg"


def test_sslmode_is_translated_for_asyncpg():
    url, args = prepare_engine_args(
        "postgresql://u:p@host/db?sslmode=require"
    )

    assert args["ssl"] == "require"
    assert "sslmode" not in url.query


def test_pgbouncer_safe_settings_and_timeouts_for_postgres():
    _, args = prepare_engine_args("postgres://u:p@host/db")

    assert args["statement_cache_size"] == 0
    assert args["timeout"] > 0 and args["command_timeout"] > 0


def test_sqlite_urls_are_untouched():
    url, args = prepare_engine_args("sqlite+aiosqlite:///x.db")

    assert str(url) == "sqlite+aiosqlite:///x.db"
    assert args == {}


def test_garbage_url_error_never_contains_the_input():
    with pytest.raises(DatabaseConfigError) as raised:
        prepare_engine_args("this is not a url with password hunter2")

    assert "hunter2" not in str(raised.value)
