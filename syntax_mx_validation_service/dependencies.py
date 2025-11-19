from sqlalchemy.ext.asyncio import AsyncSession
from database import async_session  # import from the new database module

async def get_async_session() -> AsyncSession:
    async with async_session() as session:
        yield session
