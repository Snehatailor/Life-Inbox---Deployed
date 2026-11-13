"""Load / remove demo data: every feature gets samples, removal is exact and private."""

import importlib
import sys
from contextlib import ExitStack
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

_RELOADED = (
    "app.main", "app.database", "app.auth", "app.config", "app.demo_data",
    "app.integrations.calendar", "app.integrations.google_calendar",
)
PASSWORD = "a long test password"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'demo.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LIFE_INBOX_ENV", "beta")
    monkeypatch.setenv("LIFE_INBOX_SESSION_SECRET", "d" * 40)
    monkeypatch.setenv("LIFE_INBOX_ALLOW_DEV_LOGIN", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for name in _RELOADED:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    with ExitStack() as stack:

        def client(email):
            c = stack.enter_context(TestClient(main.app, base_url="https://testserver"))
            assert c.post("/api/auth/register", json={"email": email, "password": PASSWORD}).status_code == 200
            return c

        yield SimpleNamespace(client=client, db=database)
    database.engine.dispose()
    for name in _RELOADED:
        sys.modules.pop(name, None)


def test_demo_data_covers_every_feature(env):
    c = env.client("alice@example.com")
    assert c.get("/api/demo").json() == {"loaded": False}
    loaded = c.post("/api/demo")
    assert loaded.status_code == 200, loaded.text
    body = loaded.json()
    assert body["loaded"] is True
    assert body["counts"]["items"] == 12

    items = c.get("/api/items").json()
    kinds = {item["item_type"] for item in items}
    assert {"text", "url", "pdf", "image", "voice"} <= kinds
    assert all(item["processing_status"] == "ready" for item in items)

    open_tasks = c.get("/api/tasks?status=open").json()
    urgencies = {task.get("urgency") for task in open_tasks}
    assert {"overdue", "due"} & urgencies
    assert any(task.get("slot_start") for task in open_tasks)
    assert any((task.get("radar") or {}).get("level") == "at_risk" for task in open_tasks)
    assert c.get("/api/tasks?status=backlog").json()

    game = c.get("/api/game/today").json()
    assert game["points_today"] > 0
    assert game["streak"] >= 6
    assert c.get("/api/pet/state").status_code == 200
    shop = c.get("/api/shop")
    assert shop.status_code == 200
    assert "dog" in str(shop.json())
    assert c.get("/api/pet/state").json().get("active_pet", c.get("/api/pet/state").json()) is not None
    assert c.get("/api/calendar/busy").json()
    assert c.get("/api/analyze/latest").status_code == 200
    topics = c.get("/api/topics").json()
    assert any(topic["name"] == "Home projects (demo)" for topic in topics)


def test_loading_twice_is_refused(env):
    c = env.client("alice@example.com")
    assert c.post("/api/demo").status_code == 200
    again = c.post("/api/demo")
    assert again.status_code == 409
    assert "Remove it first" in again.json()["detail"]


def test_remove_deletes_only_demo_rows(env):
    c = env.client("alice@example.com")
    mine = c.post("/api/items", json={"raw_text": "MY_REAL_NOTE pay rent tomorrow"}).json()
    c.post("/api/demo")
    assert len(c.get("/api/items").json()) == 13
    removed = c.delete("/api/demo")
    assert removed.status_code == 200
    assert removed.json() == {"loaded": False}
    remaining = c.get("/api/items").json()
    assert [item["id"] for item in remaining] == [mine["id"]]
    assert c.get("/api/game/today").json()["streak"] == 0
    assert not any(t["name"] == "Home projects (demo)" for t in c.get("/api/topics").json())
    assert c.get("/api/demo").json() == {"loaded": False}
    # Can load again after removing.
    assert c.post("/api/demo").status_code == 200


def test_demo_data_is_private(env):
    alice = env.client("alice@example.com")
    alice.post("/api/demo")
    bob = env.client("bob@example.com")
    assert bob.get("/api/items").json() == []
    assert bob.get("/api/demo").json() == {"loaded": False}
    assert bob.delete("/api/demo").json() == {"loaded": False}
    assert len(alice.get("/api/items").json()) == 12


def test_demo_requires_sign_in(env):
    env.client("alice@example.com")
    from fastapi.testclient import TestClient as TC
    main = sys.modules["app.main"]
    with TC(main.app, base_url="https://testserver") as anonymous:
        assert anonymous.post("/api/demo").status_code == 401
