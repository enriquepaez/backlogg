from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.search.repository import SearchRepository


class SearchService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = SearchRepository(session)

    async def search(
        self,
        q: str,
        item_type: str | None = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], int]:
        """Search the catalog and return (results, total)."""
        return await self._repo.search(q=q, item_type=item_type, page=page, limit=limit)
