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


# ---------- Weekly stats card ----------

def _points(db, owner_id: int, day, points: int) -> None:
    with db.SessionLocal() as session:
        session.add(
            db.PointEventRecord(
                owner_user_id=owner_id,
                task_id=None,
                points=points,
                day=day.isoformat(),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        session.commit()


def test_empty_week_stats_are_zero(env):
    stats = env.client.get("/api/review/week").json()["stats"]
    assert stats["done_by_priority"] == {"High": 0, "Medium": 0, "Low": 0}
    assert len(stats["week_days"]) == 7
    assert stats["goal_days"] == 0
    assert stats["best_day"] is None
    assert stats["streak"] == 0
    assert stats["habits_kept"] == 0
    assert stats["points_this_week"] == 0


def test_seeded_week_gives_exact_stats(env):
    from app.attention.dates import today_in_configured_tz

    client, db = env.client, env.db
    owner = db.get_or_create_default_owner_id()
    today = today_in_configured_tz()
    _points(db, owner, today - timedelta(days=1), 120)
    _points(db, owner, today - timedelta(days=2), 100)
    _points(db, owner, today - timedelta(days=3), 80)
    _points(db, owner, today - timedelta(days=9), 500)   # outside the 7 days

    created = {}
    for text, priority in [("Ship report", "High"), ("Buy milk", "Medium"), ("Tidy desk", "Low"), ("Revise DSA", "Medium")]:
        task = client.post("/api/tasks/quick", json={"sentence": text}).json()
        client.patch(f"/api/tasks/{task['id']}", json={"priority": priority, "due_on": today.isoformat()})
        created[text] = task["id"]
    client.patch(f"/api/tasks/{created['Revise DSA']}", json={"repeat_rule": "daily"})
    for task_id in created.values():
        assert client.post(f"/api/tasks/{task_id}/complete").status_code == 200

    review = client.get("/api/review/week").json()
    stats = review["stats"]
    assert stats["done_by_priority"] == {"High": 1, "Medium": 2, "Low": 1}
    assert stats["habits_kept"] == 1
    # Today: 30 + 20 + 10 + 20 = 80 points (goal not met).
    by_day = {entry["day"]: entry for entry in stats["week_days"]}
    assert by_day[today.isoformat()]["points"] == 80
    assert stats["goal_days"] == 2
    assert stats["best_day"]["day"] == (today - timedelta(days=1)).isoformat()
    assert stats["best_day"]["points"] == 120
    assert stats["streak"] == 2
    assert stats["points_this_week"] == 120 + 100 + 80 + 80
    # Same numbers as the daily ring.
    game = client.get("/api/game/today").json()
    assert game["streak"] == stats["streak"]
    assert game["history"] == stats["week_days"]
    assert "daily goal on 2 of the last 7 days" in review["summary"]
    assert "1 habit" in review["summary"]


def test_completed_at_decides_the_week(env):
    client, db = env.client, env.db
    task = client.post("/api/tasks/quick", json={"sentence": "Old task"}).json()
    client.post(f"/api/tasks/{task['id']}/complete")
    with db.SessionLocal() as session:
        row = session.get(db.TaskRecord, task["id"])
        row.completed_at = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        row.updated_at = datetime.now(timezone.utc).isoformat()   # edited today
        session.commit()
    review = client.get("/api/review/week").json()
    assert review["completed_tasks"] == []
    assert sum(review["stats"]["done_by_priority"].values()) == 0


def test_other_users_points_never_appear(env):
    from app.attention.dates import today_in_configured_tz

    db = env.db
    other = db.ensure_user(email="someone-else@example.com", display_name="Other", auth_provider="password")
    _points(db, other["id"], today_in_configured_tz(), 999)
    stats = env.client.get("/api/review/week").json()["stats"]
    assert stats["points_this_week"] == 0
    assert stats["goal_days"] == 0
