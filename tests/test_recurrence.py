"""Recurring tasks: next-date rules, one copy per completion, isolation, migration."""

import importlib
import sys
from contextlib import ExitStack
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from app.game.recurrence import describe, next_due, normalize_rule
from tests.test_migrations import alembic_config

# Wednesday 11 Nov 2026 is used as "today" in the date-rule tests.
WED = date(2026, 11, 11)
THU, FRI, SAT, SUN = (WED + timedelta(days=n) for n in (1, 2, 3, 4))
MON = date(2026, 11, 16)


# ---------- pure date rules ----------

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("daily", "daily"),
        (" Weekdays ", "weekdays"),
        ("WEEKLY", "weekly"),
        ("days:fri,mon,wed", "days:mon,wed,fri"),
        ("days:mon,mon,wed", "days:mon,wed"),
        ("days:mon,tue,wed,thu,fri", "weekdays"),
        ("days:mon,tue,wed,thu,fri,sat,sun", "daily"),
        ("none", None),
        ("", None),
        (None, None),
    ],
)
def test_normalize_rule(raw, expected):
    assert normalize_rule(raw) == expected


@pytest.mark.parametrize("bad", ["monthly", "days:", "days:funday", "days:mon,xyz", "x" * 80])
def test_invalid_rules_are_rejected(bad):
    with pytest.raises(ValueError):
        normalize_rule(bad)


def test_daily_goes_to_the_next_day():
    assert next_due("daily", WED, WED) == THU


def test_weekdays_skip_the_weekend():
    assert next_due("weekdays", FRI, FRI) == MON
    assert next_due("weekdays", THU, THU) == FRI


def test_weekly_is_seven_days_after_the_due_date():
    assert next_due("weekly", WED, WED) == WED + timedelta(days=7)


def test_chosen_days():
    rule = "days:mon,wed,fri"
    assert next_due(rule, MON, MON) == MON + timedelta(days=2)   # Mon 16 -> Wed 18
    assert next_due(rule, WED, WED) == FRI                       # Wed 11 -> Fri 13
    assert next_due(rule, FRI, FRI) == MON                       # Fri 13 -> Mon 16


def test_month_end_and_leap_year():
    assert next_due("daily", date(2027, 1, 31), date(2027, 1, 31)) == date(2027, 2, 1)
    assert next_due("daily", date(2028, 2, 28), date(2028, 2, 28)) == date(2028, 2, 29)
    assert next_due("weekdays", date(2027, 12, 31), date(2027, 12, 31)) == date(2028, 1, 3)


def test_no_previous_due_date_counts_from_today():
    assert next_due("daily", None, WED) == THU
    assert next_due("weekly", None, WED) == WED + timedelta(days=7)
    assert next_due("days:sat", None, WED) == SAT


def test_late_completion_skips_dates_already_past():
    # Due last Monday, finished on Wednesday: the next one is Friday, not Wednesday.
    last_monday = date(2026, 11, 9)
    assert next_due("days:mon,wed,fri", last_monday, WED) == FRI
    assert next_due("daily", last_monday, WED) == THU
    # Weekly keeps its weekday: Monday 9th -> Monday 16th.
    assert next_due("weekly", last_monday, WED) == MON


def test_early_completion_keeps_the_schedule():
    # Due Friday, finished on Wednesday: the next one follows Friday.
    assert next_due("days:mon,wed,fri", FRI, WED) == MON


def test_describe():
    assert describe("daily") == "Every day"
    assert describe("weekdays") == "Weekdays"
    assert describe("weekly") == "Every week"
    assert describe("days:mon,wed,fri") == "Mon, Wed, Fri"
    assert describe(None) is None
    assert describe("bogus") is None


# ---------- API ----------

_RELOADED = (
    "app.main", "app.database", "app.auth", "app.config",
    "app.integrations.calendar", "app.integrations.google_calendar",
)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'recur.db'}")
    monkeypatch.setenv("LIFE_INBOX_AUTO_CREATE_TABLES", "1")
    monkeypatch.setenv("LIFE_INBOX_UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("LIFE_INBOX_ENV", "beta")
    monkeypatch.setenv("LIFE_INBOX_SESSION_SECRET", "r" * 40)
    monkeypatch.setenv("LIFE_INBOX_ALLOW_DEV_LOGIN", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    for name in _RELOADED:
        sys.modules.pop(name, None)
    main = importlib.import_module("app.main")
    database = importlib.import_module("app.database")
    from app.attention.dates import today_in_configured_tz

    with ExitStack() as stack:

        def client(email):
            c = stack.enter_context(TestClient(main.app, base_url="https://testserver"))
            response = c.post("/api/auth/register", json={"email": email, "password": "long password 1"})
            assert response.status_code == 200
            return c

        yield SimpleNamespace(client=client, db=database, today=today_in_configured_tz())
    database.engine.dispose()
    for name in _RELOADED:
        sys.modules.pop(name, None)


def _task(c, text="Revise DSA", priority="Medium", due=None):
    body = {"sentence": text}
    task = c.post("/api/tasks/quick", json=body).json()
    patch = {"priority": priority}
    if due:
        patch["due_on"] = due
    return c.patch(f"/api/tasks/{task['id']}", json=patch).json()


def _open(c):
    return c.get("/api/tasks?status=open").json()


def test_setting_and_clearing_a_repeat_rule(env):
    c = env.client("alice@example.com")
    task = _task(c)
    saved = c.patch(f"/api/tasks/{task['id']}", json={"repeat_rule": "days:fri,mon,wed"})
    assert saved.status_code == 200
    assert saved.json()["repeat_rule"] == "days:mon,wed,fri"
    assert saved.json()["repeat_label"] == "Mon, Wed, Fri"
    bad = c.patch(f"/api/tasks/{task['id']}", json={"repeat_rule": "monthly"})
    assert bad.status_code == 400
    cleared = c.patch(f"/api/tasks/{task['id']}", json={"repeat_rule": None}).json()
    assert cleared["repeat_rule"] is None and cleared["repeat_label"] is None


def test_completing_creates_exactly_one_next_copy(env):
    c = env.client("alice@example.com")
    today = env.today
    task = _task(c, "Gym", "High", today.isoformat())
    c.patch(f"/api/tasks/{task['id']}", json={"repeat_rule": "daily"})

    done = c.post(f"/api/tasks/{task['id']}/complete")
    assert done.status_code == 200
    body = done.json()
    assert body["points_awarded"] == 30          # points work exactly as before
    assert body["next_task_id"] is not None
    tomorrow = (today + timedelta(days=1)).isoformat()
    assert body["next_due_on"] == tomorrow

    copies = [t for t in _open(c) if t["text"] == "Gym"]
    assert len(copies) == 1
    copy = copies[0]
    assert copy["id"] == body["next_task_id"]
    assert copy["due_on"] == tomorrow
    assert copy["repeat_rule"] == "daily"
    assert copy["base_priority"] == "High"
    assert copy["points_awarded"] is None


def test_reopen_then_complete_reuses_the_copy(env):
    c = env.client("alice@example.com")
    task = _task(c, "Gym", "High", env.today.isoformat())
    c.patch(f"/api/tasks/{task['id']}", json={"repeat_rule": "daily"})
    first = c.post(f"/api/tasks/{task['id']}/complete").json()
    reopened = c.post(f"/api/tasks/{task['id']}/reopen").json()
    assert reopened["points_awarded"] is None    # reopening still takes points back
    second = c.post(f"/api/tasks/{task['id']}/complete").json()
    assert second["next_task_id"] == first["next_task_id"]
    assert len([t for t in _open(c) if t["text"] == "Gym"]) == 1
    assert c.get("/api/game/today").json()["points_today"] == 30


def test_copy_continues_the_series(env):
    c = env.client("alice@example.com")
    task = _task(c, "Stretch", "Low", env.today.isoformat())
    c.patch(f"/api/tasks/{task['id']}", json={"repeat_rule": "daily"})
    copy_id = c.post(f"/api/tasks/{task['id']}/complete").json()["next_task_id"]
    third = c.post(f"/api/tasks/{copy_id}/complete").json()
    assert third["next_task_id"] not in (None, copy_id, task["id"])
    assert len([t for t in _open(c) if t["text"] == "Stretch"]) == 1


def test_no_repeat_creates_nothing(env):
    c = env.client("alice@example.com")
    task = _task(c, "One-off", "Low", env.today.isoformat())
    done = c.post(f"/api/tasks/{task['id']}/complete").json()
    assert done["next_task_id"] is None
    assert done["next_due_on"] is None
    assert not [t for t in _open(c) if t["text"] == "One-off"]


def test_stopping_a_series_keeps_existing_copies(env):
    c = env.client("alice@example.com")
    task = _task(c, "Read", "Low", env.today.isoformat())
    c.patch(f"/api/tasks/{task['id']}", json={"repeat_rule": "daily"})
    copy_id = c.post(f"/api/tasks/{task['id']}/complete").json()["next_task_id"]
    c.patch(f"/api/tasks/{copy_id}", json={"repeat_rule": "none"})
    done = c.post(f"/api/tasks/{copy_id}/complete").json()
    assert done["next_task_id"] is None
    assert c.get(f"/api/tasks?status=completed").status_code == 200
    assert not [t for t in _open(c) if t["text"] == "Read"]


def test_dismissing_does_not_create_a_copy(env):
    c = env.client("alice@example.com")
    task = _task(c, "Skip me", "Low", env.today.isoformat())
    c.patch(f"/api/tasks/{task['id']}", json={"repeat_rule": "daily"})
    c.post(f"/api/tasks/{task['id']}/dismiss")
    assert not [t for t in _open(c) if t["text"] == "Skip me"]


def test_other_users_cannot_set_or_trigger_your_series(env):
    alice = env.client("alice@example.com")
    task = _task(alice, "Alice habit", "Medium", env.today.isoformat())
    bob = env.client("bob@example.com")
    assert bob.patch(f"/api/tasks/{task['id']}", json={"repeat_rule": "daily"}).status_code == 404
    assert bob.post(f"/api/tasks/{task['id']}/complete").status_code == 404
    alice.patch(f"/api/tasks/{task['id']}", json={"repeat_rule": "daily"})
    copy_id = alice.post(f"/api/tasks/{task['id']}/complete").json()["next_task_id"]
    assert bob.get("/api/tasks?status=open").json() == []
    assert bob.post(f"/api/tasks/{copy_id}/complete").status_code == 404
    assert all(t["text"] != "Alice habit" for t in bob.get("/api/tasks?status=all").json())


# ---------- migration ----------

def test_migration_adds_columns_on_empty_and_existing_databases(tmp_path):
    database_path = tmp_path / "recur.db"
    config = alembic_config(database_path)
    command.upgrade(config, "0023_demo_data_marker")
    engine = create_engine(f"sqlite:///{database_path}")
    assert "repeat_rule" not in {c["name"] for c in inspect(engine).get_columns("tasks")}
    engine.dispose()
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    columns = {c["name"] for c in inspect(engine).get_columns("tasks")}
    engine.dispose()
    assert {"repeat_rule", "next_task_id"} <= columns
