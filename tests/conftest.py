import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_db
from app.main import app


@pytest.fixture()
def client(tmp_path):
    """Each test gets its own SQLite file and its own session factory.

    The DB dependency is swapped with `app.dependency_overrides` — this is
    FastAPI's built-in test seam and the reason `get_db` is a dependency rather
    than a module-level import. Nothing else in the app changes.

    Note: TestClient is used *without* a `with` block on purpose, so the
    lifespan handler (which creates tables on the configured Postgres URL) does
    not run. The schema is created explicitly below instead.
    """
    url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = create_engine(url, connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


def auth_header(client, email: str, password: str) -> dict[str, str]:
    """Helper: log in and return a bearer header."""
    resp = client.post("/auth/token", data={"username": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}
