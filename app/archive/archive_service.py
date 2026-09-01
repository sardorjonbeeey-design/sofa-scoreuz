class ArchiveService:

    async def archive_fixture(self, fixture) -> None:
        raise NotImplementedError

    async def get_archived_fixture(self, fixture_id: int):
        raise NotImplementedError