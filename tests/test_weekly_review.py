"""Weekly review: counts come from stored rows; a model may only reword them."""

import importlib
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.pdf_fixtures import make_text_pdf

_RELOADED_MODULES = (
    "app.main",
    "app.database",
    "app.auth",
    "app.config",
    "app.integrations.calendar",
    "app.review",
)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'weekly.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for name in _RELOADED_MODULES:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    with TestClient(main.app) as client:
        yield SimpleNamespace(client=client, db=database)
    database.engine.dispose()
    for name in _RELOADED_MODULES:
        sys.modules.pop(name, None)


def _mock_openai(monkeypatch, output_text=None, *, raise_on_create=None):
    import openai

    def create(**_kwargs):
        if raise_on_create is not None:
            raise raise_on_create
        return SimpleNamespace(output_text=output_text)

    monkeypatch.setenv("OPENAI_API_KEY", "configured-for-test")
    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda: SimpleNamespace(responses=SimpleNamespace(create=create)),
    )


def _backdate_item(db, item_id: int, days: int) -> None:
    with db.SessionLocal() as session:
        item = session.get(db.InboxItemRecord, item_id)
        item.created_at = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        session.commit()


def test_empty_week_is_quiet_and_rule_based(env):
    response = env.client.get("/api/review/week")

    assert response.status_code == 200
    review = response.json()
    assert review["captured"] == {"total": 0, "by_type": {}}
    assert review["completed_tasks"] == []
    assert review["untouched_count"] == 0
    assert review["summary_kind"] == "rule_based"
    assert "quiet week" in review["summary"].lower()


def test_week_counts_captures_completed_tasks_and_untouched_items(env):
    client = env.client
    client.post("/api/items", json={"raw_text": "Need to renew passport this week"})
    client.post("/api/items", json={"raw_text": "Remember to call the dentist"})
    pdf = client.post(
        "/api/items/pdf",
        files={"file": ("receipt.pdf", make_text_pdf("Receipt body"), "application/pdf")},
    )
    assert pdf.status_code == 200, pdf.text
    old = client.post("/api/items", json={"raw_text": "Old note from last month"}).json()
    _backdate_item(env.db, old["id"], days=10)

    assert client.post("/api/analyze").status_code == 200
    tasks = client.get("/api/tasks").json()
    assert tasks, "the fallback organizer should create tasks"
    done = client.post(f"/api/tasks/{tasks[0]['id']}/complete").json()

    # Saved after analysis, so it has not been organized yet.
    fresh = client.post("/api/items", json={"raw_text": "Idea: weekend photo walk"}).json()

    review = client.get("/api/review/week").json()

    assert review["captured"]["total"] == 4  # the 10-day-old note is excluded
    assert review["captured"]["by_type"] == {"text": 3, "pdf": 1}
    assert [task["id"] for task in review["completed_tasks"]] == [done["id"]]
    assert review["open_task_count"] == len(tasks) - 1
    untouched_ids = {item["id"] for item in review["untouched_items"]}
    assert fresh["id"] in untouched_ids
    assert old["id"] not in untouched_ids
    assert review["untouched_count"] == len(untouched_ids)
    assert "4 items" in review["summary"]
    assert "1 task" in review["summary"]


def test_model_summary_is_used_and_labelled(env, monkeypatch):
    env.client.post("/api/items", json={"raw_text": "Buy groceries"})
    _mock_openai(monkeypatch, "A calm week with one note saved.")

    review = env.client.get("/api/review/week").json()

    assert review["summary"] == "A calm week with one note saved."
    assert review["summary_kind"] == "model_generated"
    assert review["captured"]["total"] == 1  # numbers still come from the database


@pytest.mark.parametrize(
    "mock_kwargs",
    [{"raise_on_create": RuntimeError("API down")}, {"output_text": "   "}],
)
def test_model_failure_falls_back_to_rule_based_summary(env, monkeypatch, mock_kwargs):
    env.client.post("/api/items", json={"raw_text": "Buy groceries"})
    _mock_openai(monkeypatch, **mock_kwargs)

    response = env.client.get("/api/review/week")

    assert response.status_code == 200
    review = response.json()
    assert review["summary_kind"] == "rule_based"
    assert review["summary"].startswith("You captured 1 item")
