import os
from dotenv import load_dotenv
from fastapi import FastAPI, Depends
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from models.models import Base
from controller import router

# Load environment variables from .env file
load_dotenv()

# Configuration
DATABASE_URL = os.getenv("DATABASE_URL")
APP_PORT = int(os.getenv("APP_PORT", 8000))

# Database engine and session
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

# FastAPI app instance
app = FastAPI(title="Syntax MX Validation Service")

# Dependency provider for AsyncSession
async def get_db_session() -> AsyncSession:
    async with async_session() as session:
        yield session

# Automatically inject DB session into all routes in the router
for route in router.routes:
    if isinstance(route, APIRoute):
        route.dependant.dependencies.append(Depends(get_db_session))

# Register router
app.include_router(router)

# Create tables on startup
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        #await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

# Run the app
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=APP_PORT, reload=True)
