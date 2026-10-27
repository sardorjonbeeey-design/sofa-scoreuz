import asyncio

import pytest

from app.storage.database import Database, StorageError
from app.storage.store import (
    AddFavoriteResult,
    MemoryPreferenceStore,
    SqlPreferenceStore,
)


def sqlite_url(path) -> str:
    return f"sqlite+aiosqlite:///{path}"


@pytest.fixture(params=["memory", "sql"])
async def store(request, tmp_path):
    """Every behavioural test runs against both implementations."""
    if request.param == "memory":
        instance = MemoryPreferenceStore("uz")
    else:
        instance = SqlPreferenceStore(
            Database(sqlite_url(tmp_path / "test.db")),
            "uz",
        )

    yield instance

    await instance.close()


# --- users and language ------------------------------------------------


async def test_unknown_user_has_no_language_or_favorites(store):
    assert await store.get_language(1) is None
    assert await store.list_favorites(1) == []


async def test_language_is_saved_and_updated(store):
    await store.set_language(1, "ru")
    assert await store.get_language(1) == "ru"

    await store.set_language(1, "en")
    assert await store.get_language(1) == "en"


async def test_unsupported_language_falls_back_to_default(store):
    await store.set_language(1, "xx")
    assert await store.get_language(1) == "uz"


async def test_users_are_isolated(store):
    await store.set_language(1, "ru")
    await store.set_language(2, "en")
    await store.add_favorite(1, 10, "Barcelona", limit=3)

    assert await store.get_language(1) == "ru"
    assert await store.get_language(2) == "en"
    assert await store.list_favorites(2) == []


# --- favorites -----------------------------------------------------------


async def test_add_and_list_favorites_in_insertion_order(store):
    assert (
        await store.add_favorite(1, 10, "Barcelona", limit=3)
        is AddFavoriteResult.ADDED
    )
    await store.add_favorite(1, 20, "Liverpool", limit=3)

    favorites = await store.list_favorites(1)

    assert [(f.team_id, f.team_name) for f in favorites] == [
        (10, "Barcelona"),
        (20, "Liverpool"),
    ]


async def test_one_club_and_one_national_team_have_separate_single_slots(store):
    assert await store.add_favorite(
        12, 1, "Arsenal", limit=2, team_type="club"
    ) is AddFavoriteResult.ADDED
    assert await store.add_favorite(
        12, 2, "Liverpool", limit=2, team_type="club"
    ) is AddFavoriteResult.LIMIT_REACHED
    assert await store.add_favorite(
        12, 3, "Uzbekistan", limit=2, team_type="national"
    ) is AddFavoriteResult.ADDED
    assert await store.add_favorite(
        12, 4, "France", limit=2, team_type="national"
    ) is AddFavoriteResult.LIMIT_REACHED

    favorites = await store.list_favorites(12)
    assert [(f.team_id, f.team_type) for f in favorites] == [
        (1, "club"), (3, "national")
    ]


async def test_duplicate_add_is_idempotent(store):
    await store.add_favorite(1, 10, "Barcelona", limit=3)

    result = await store.add_favorite(1, 10, "Barcelona", limit=3)

    assert result is AddFavoriteResult.DUPLICATE
    assert len(await store.list_favorites(1)) == 1


async def test_limit_is_enforced_from_the_given_value(store):
    for team_id in (1, 2, 3):
        assert (
            await store.add_favorite(7, team_id, f"T{team_id}", limit=3)
            is AddFavoriteResult.ADDED
        )

    assert (
        await store.add_favorite(7, 4, "T4", limit=3)
        is AddFavoriteResult.LIMIT_REACHED
    )
    assert len(await store.list_favorites(7)) == 3


async def test_limit_is_not_hardcoded_to_three(store):
    for team_id in range(1, 6):
        result = await store.add_favorite(
            7, team_id, f"T{team_id}", limit=5
        )
        assert result is AddFavoriteResult.ADDED

    assert (
        await store.add_favorite(7, 6, "T6", limit=5)
        is AddFavoriteResult.LIMIT_REACHED
    )


async def test_duplicate_is_reported_even_when_at_the_limit(store):
    for team_id in (1, 2, 3):
        await store.add_favorite(7, team_id, f"T{team_id}", limit=3)

    assert (
        await store.add_favorite(7, 2, "T2", limit=3)
        is AddFavoriteResult.DUPLICATE
    )


async def test_remove_favorite_and_free_the_slot(store):
    for team_id in (1, 2, 3):
        await store.add_favorite(7, team_id, f"T{team_id}", limit=3)

    assert await store.remove_favorite(7, 2) is True
    assert [f.team_id for f in await store.list_favorites(7)] == [1, 3]

    assert (
        await store.add_favorite(7, 4, "T4", limit=3)
        is AddFavoriteResult.ADDED
    )


async def test_remove_is_idempotent(store):
    await store.add_favorite(7, 1, "T1", limit=3)

    assert await store.remove_favorite(7, 1) is True
    assert await store.remove_favorite(7, 1) is False
    assert await store.remove_favorite(999, 1) is False


async def test_long_team_names_are_truncated_to_the_column_size(store):
    await store.add_favorite(1, 10, "X" * 400, limit=3)

    (favorite,) = await store.list_favorites(1)

    assert len(favorite.team_name) == 150


# --- SQL-specific behaviour --------------------------------------------------


async def test_data_survives_a_restart(tmp_path):
    """A new store/engine on the same database sees earlier writes."""
    url = sqlite_url(tmp_path / "persist.db")

    first = SqlPreferenceStore(Database(url), "uz")
    await first.set_language(5, "ru")
    await first.add_favorite(5, 10, "Barcelona", limit=3)
    await first.add_favorite(5, 20, "Bayern Munich", limit=3)
    await first.close()

    second = SqlPreferenceStore(Database(url), "uz")

    assert await second.get_language(5) == "ru"
    assert [
        (f.team_id, f.team_name)
        for f in await second.list_favorites(5)
    ] == [(10, "Barcelona"), (20, "Bayern Munich")]

    await second.close()


async def test_schema_init_does_not_destroy_existing_data(tmp_path):
    url = sqlite_url(tmp_path / "keep.db")

    first = SqlPreferenceStore(Database(url), "uz")
    await first.add_favorite(1, 10, "Barcelona", limit=3)
    await first.close()

    # Re-running initialisation (as every startup does) is harmless.
    database = Database(url)
    await database.ensure_schema()
    await database.ensure_schema()
    await database.dispose()

    again = SqlPreferenceStore(Database(url), "uz")
    assert len(await again.list_favorites(1)) == 1
    await again.close()


async def test_concurrent_adds_never_exceed_the_limit(tmp_path):
    sql = SqlPreferenceStore(
        Database(sqlite_url(tmp_path / "race.db")), "uz"
    )

    results = await asyncio.gather(
        *(sql.add_favorite(1, team_id, f"T{team_id}", limit=3)
          for team_id in range(1, 11))
    )

    assert results.count(AddFavoriteResult.ADDED) == 3
    assert len(await sql.list_favorites(1)) == 3

    await sql.close()


async def test_concurrent_identical_adds_store_one_row(tmp_path):
    sql = SqlPreferenceStore(
        Database(sqlite_url(tmp_path / "dup.db")), "uz"
    )

    results = await asyncio.gather(
        *(sql.add_favorite(1, 10, "Barcelona", limit=3)
          for _ in range(8))
    )

    assert results.count(AddFavoriteResult.ADDED) == 1
    assert results.count(AddFavoriteResult.DUPLICATE) == 7

    await sql.close()


async def test_concurrent_first_use_of_a_new_user_does_not_fail(tmp_path):
    sql = SqlPreferenceStore(
        Database(sqlite_url(tmp_path / "new.db")), "uz"
    )

    await asyncio.gather(
        *(sql.set_language(77, "ru") for _ in range(8))
    )

    assert await sql.get_language(77) == "ru"

    await sql.close()


async def test_unreachable_database_raises_storage_error(tmp_path):
    missing = tmp_path / "no-such-dir" / "db.sqlite"
    sql = SqlPreferenceStore(Database(sqlite_url(missing)), "uz")

    with pytest.raises(StorageError):
        await sql.set_language(1, "ru")

    with pytest.raises(StorageError):
        await sql.add_favorite(1, 10, "Barcelona", limit=3)

    with pytest.raises(StorageError):
        await sql.list_favorites(1)

    await sql.close()


async def test_database_recovers_when_it_becomes_available(tmp_path):
    folder = tmp_path / "later"
    sql = SqlPreferenceStore(
        Database(sqlite_url(folder / "db.sqlite")), "uz"
    )

    with pytest.raises(StorageError):
        await sql.set_language(1, "ru")

    folder.mkdir()  # the database "comes back"

    await sql.set_language(1, "ru")
    assert await sql.get_language(1) == "ru"

    await sql.close()
