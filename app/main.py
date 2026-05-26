"""OTS Approval Helping Agent — FastAPI application entry point."""

from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.db.session import engine
from app.db.models import Base  # noqa: F401 — register models
from app.events.bus import event_bus


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables (MVP convenience — replace with Alembic migrations in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await event_bus.start()
    yield
    # Shutdown
    await event_bus.stop()


app = FastAPI(title="OTS Approval Helping Agent", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "OTS-AHA"}
