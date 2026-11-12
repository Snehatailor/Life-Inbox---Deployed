"""Things added when the Task Quest branch was merged with accounts/settings:
the desktop-pet on/off switch and the migration that reconciles both chains."""

import importlib
import sys
from pathlib import Path

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from tests.test_migrations import alembic_config, head_revision


_RELOADED = (
    "app.main", "app.database", "app.auth", "app.config", "app.pet_launcher",
    "app.integrations.calendar", "app.integrations.google_calendar",
)


def _app(tmp_path, monkeypatch, environment):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'merge.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LIFE_INBOX_ENV", environment)
    monkeypatch.setenv("LIFE_INBOX_SESSION_SECRET", "m" * 40)
    monkeypatch.setenv("LIFE_INBOX_ALLOW_DEV_LOGIN", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for name in _RELOADED:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    launcher = importlib.import_module("app.pet_launcher")
    monkeypatch.setattr(launcher, "PREFERENCE_FILE", tmp_path / "desktop_pet.json")
    return main, launcher


@pytest.fixture()
def cleanup():
    yield
    database = sys.modules.get("app.database")
    if database is not None:
        database.engine.dispose()
    for name in _RELOADED:
        sys.modules.pop(name, None)


class FakeProcess:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.terminated = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        self.terminated = True


def test_pet_switch_starts_stops_and_remembers(tmp_path, monkeypatch, cleanup):
    main, launcher = _app(tmp_path, monkeypatch, "local")
    exe = tmp_path / "electron.exe"
    exe.write_text("")
    monkeypatch.setattr(launcher, "electron_binary", lambda pet_dir=None: exe)
    started = []

    def fake_popen(*args, **kwargs):
        process = FakeProcess(*args, **kwargs)
        started.append(process)
        return process

    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    with TestClient(main.app) as client:
        status = client.get("/api/desktop-pet").json()
        assert status == {"available": True, "installed": True, "enabled": True, "running": False}

        on = client.put("/api/desktop-pet", json={"enabled": True})
        assert on.status_code == 200
        assert on.json()["running"] is True
        assert len(started) == 1
        assert str(started[0].args[0][0]) == str(exe)

        # Turning it on twice does not start a second pet.
        client.put("/api/desktop-pet", json={"enabled": True})
        assert len(started) == 1

        off = client.put("/api/desktop-pet", json={"enabled": False}).json()
        assert off["enabled"] is False and off["running"] is False
        assert started[0].terminated is True

    assert launcher.pet_enabled(tmp_path / "desktop_pet.json") is False
    # Switched off: the startup hook leaves it off.
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    assert launcher.launch_pet(8000) is False
    assert len(started) == 1


def test_pet_switch_explains_when_not_installed(tmp_path, monkeypatch, cleanup):
    main, launcher = _app(tmp_path, monkeypatch, "local")
    monkeypatch.setattr(launcher, "electron_binary", lambda pet_dir=None: None)
    with TestClient(main.app) as client:
        assert client.get("/api/desktop-pet").json()["installed"] is False
        response = client.put("/api/desktop-pet", json={"enabled": True})
        assert response.status_code == 409
        assert "npm install" in response.json()["detail"]


def test_pet_switch_is_unavailable_on_the_hosted_site(tmp_path, monkeypatch, cleanup):
    main, launcher = _app(tmp_path, monkeypatch, "beta")
    called = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: called.append(a))
    with TestClient(main.app, base_url="https://testserver") as client:
        client.post("/api/auth/register", json={"email": "a@example.com", "password": "long password"})
        assert client.get("/api/desktop-pet").json()["available"] is False
        refused = client.put("/api/desktop-pet", json={"enabled": True})
        assert refused.status_code == 403
    assert called == []


def test_pet_switch_refuses_requests_from_other_computers(tmp_path, monkeypatch, cleanup):
    main, launcher = _app(tmp_path, monkeypatch, "local")
    called = []
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *a, **k: called.append(a))
    with TestClient(main.app, client=("192.168.1.50", 5000)) as client:
        assert client.get("/api/desktop-pet").json()["available"] is False
        assert client.put("/api/desktop-pet", json={"enabled": True}).status_code == 403
    assert called == []


def test_merged_chain_reaches_one_head_with_everything(tmp_path):
    database_path = tmp_path / "fresh.db"
    command.upgrade(alembic_config(database_path), "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    tables = set(inspect(engine).get_table_names())
    user_columns = {c["name"] for c in inspect(engine).get_columns("users")}
    engine.dispose()
    assert revision == head_revision()
    assert {"user_settings", "point_events", "pet_settings", "teams", "task_events"} <= tables
    assert "password_hash" in user_columns


def test_task_quest_database_at_0021_gets_accounts_and_settings(tmp_path):
    """A teammate's database created on the Task Quest branch before the merge."""
    database_path = tmp_path / "teammate.db"
    config = alembic_config(database_path)
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE user_settings"))
        connection.execute(text("ALTER TABLE users DROP COLUMN password_hash"))
        connection.execute(text("UPDATE alembic_version SET version_num = '0021_task_events'"))
    engine.dispose()

    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    tables = set(inspect(engine).get_table_names())
    user_columns = {c["name"] for c in inspect(engine).get_columns("users")}
    engine.dispose()
    assert "user_settings" in tables
    assert "password_hash" in user_columns
