from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import Base, engine
from app.routers import admin, auth, requests


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once on startup. In a real deployment this is where Alembic would
    run instead — create_all is here to keep the project runnable in one step."""
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Access Portal",
    description="Self-service access requests replacing an email-and-SharePoint process.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(requests.router)
app.include_router(admin.router)


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}
