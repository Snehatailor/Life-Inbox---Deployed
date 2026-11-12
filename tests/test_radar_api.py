"""Procrastination Radar through the API: snooze history, badges, rescue bonus, privacy."""

from datetime import datetime, timedelta, timezone

from app.attention.dates import today_in_configured_tz

from tests.test_api import client  # noqa: F401  (fixture)
from tests.test_isolation import _login, app_env  # noqa: F401  (fixture + helper)


def _iso(days):
    return (today_in_configured_tz() + timedelta(days=days)).isoformat()


def _quick(client, sentence, domain=None):
    response = client.post("/api/tasks/quick", json={"sentence": sentence})
    assert response.status_code == 200, response.text
    task = response.json()
    if domain:
        task = client.patch(f"/api/tasks/{task['id']}", json={"domain": domain}).json()
    return task


def _open(client, task_id):
    return next(t for t in client.get("/api/tasks").json() if t["id"] == task_id)


def _reasons(task):
    return [r["text"] for r in task["radar"]["reasons"]]


def _make_study_late_history(client):
    """Three Study tasks finished three days after their deadline."""
    for n in range(3):
        task = _quick(client, f"Revise chapter {n} {_iso(-3)} medium priority", "Study")
        assert client.post(f"/api/tasks/{task['id']}/complete").status_code == 200


def test_open_tasks_get_a_radar_and_done_tasks_do_not(client):
    far = _quick(client, f"Python end term {_iso(17)} high priority")
    listed = _open(client, far["id"])
    assert listed["radar"]["level"] == "on_track" and listed["radar"]["score"] == 0

    client.post(f"/api/tasks/{far['id']}/complete")
    done = client.get("/api/tasks", params={"status": "completed"}).json()
    assert done and all(t["radar"] is None for t in done)


def test_snoozes_are_remembered_and_undo_takes_one_back(client):
    task = _quick(client, f"GitHub submission {_iso(3)} medium priority")
    assert _open(client, task["id"])["radar"]["score"] == 20

    client.post(f"/api/tasks/{task['id']}/snooze", json={"until": _iso(1)})
    client.post(f"/api/tasks/{task['id']}/snooze", json={"until": _iso(2)})
    after = _open(client, task["id"])
    assert "Snoozed 2 times" in _reasons(after) and after["radar"]["score"] == 40
    assert after["radar"]["level"] == "watch"

    # Undo / "Wake up now" on the same day removes the latest snooze.
    client.post(f"/api/tasks/{task['id']}/snooze", json={"until": _iso(0)})
    assert "Snoozed 1 time" in _reasons(_open(client, task["id"]))


def test_remind_later_counts_as_a_snooze(client):
    task = _quick(client, f"Call the bank {_iso(5)} low priority")
    assert client.post(f"/api/tasks/{task['id']}/remind-later", json={"minutes": 5}).status_code == 200
    radar = _open(client, task["id"])["radar"]
    assert "Snoozed 1 time" in [r["text"] for r in radar["reasons"]]
    # The slot it just set counts as booked time.
    assert "Time slot booked" in [r["text"] for r in radar["reasons"]]


def test_rescue_bonus_is_paid_once_and_taken_back_on_reopen(client):
    _make_study_late_history(client)
    target = _quick(client, "Python end term today high priority", "Study")
    for n in range(4):
        _quick(client, f"Other deadline {n} today high priority")

    radar = _open(client, target["id"])["radar"]
    assert radar["level"] == "at_risk"
    assert "Your Study tasks finish 3.0 days late on average" in [r["text"] for r in radar["reasons"]]
    before = client.get("/api/game/today").json()["points_today"]

    done = client.post(f"/api/tasks/{target['id']}/complete").json()
    assert done["rescue_bonus"] == 10 and done["points_awarded"] == 30 + 10
    assert client.get("/api/game/today").json()["points_today"] == before + 40

    client.post(f"/api/tasks/{target['id']}/reopen")
    assert client.get("/api/game/today").json()["points_today"] == before


def test_start_10_min_then_finishing_still_earns_the_rescue_bonus(client):
    _make_study_late_history(client)
    target = _quick(client, "Python end term today high priority", "Study")
    for n in range(4):
        _quick(client, f"Other deadline {n} today high priority")
    start = datetime.now(timezone.utc)
    client.post(f"/api/tasks/{target['id']}/slot", json={
        "start": start.isoformat(), "end": (start + timedelta(minutes=10)).isoformat(),
    })
    radar = _open(client, target["id"])["radar"]
    assert "Time slot booked" in [r["text"] for r in radar["reasons"]]
    assert radar["level"] == "watch" and radar["rescue_score"] >= 70

    done = client.post(f"/api/tasks/{target['id']}/complete").json()
    assert done["rescue_bonus"] == 10


def test_snoozing_a_task_red_on_purpose_earns_no_bonus(client):
    _make_study_late_history(client)
    task = _quick(client, f"Essay draft {_iso(3)} high priority", "Study")
    for _ in range(3):
        client.post(f"/api/tasks/{task['id']}/snooze", json={"until": _iso(1)})
    radar = _open(client, task["id"])["radar"]
    assert radar["level"] == "at_risk" and radar["rescue_score"] < 70

    done = client.post(f"/api/tasks/{task['id']}/complete").json()
    assert done["rescue_bonus"] == 0 and done["points_awarded"] == 35  # 30 + early bonus


def test_pet_state_names_the_riskiest_task(client):
    assert client.get("/api/pet/state").json()["at_risk"] is None
    _make_study_late_history(client)
    target = _quick(client, "Python end term today high priority", "Study")
    for n in range(4):
        _quick(client, f"Other deadline {n} today high priority")
    at_risk = client.get("/api/pet/state").json()["at_risk"]
    assert at_risk["task_id"] == target["id"] and at_risk["score"] >= 70
    assert at_risk["reasons"][0] == "Due today"


def test_history_and_snoozes_stay_with_their_owner(app_env):
    ana = app_env.make_client()
    ben = app_env.make_client()
    _login(ana, "ana@example.com")
    _login(ben, "ben@example.com")

    _make_study_late_history(ana)
    ana_task = _quick(ana, f"Ana essay {_iso(3)} medium priority", "Study")
    ben_task = _quick(ben, f"Ben essay {_iso(3)} medium priority", "Study")

    # Ana's late Study history shows on her task only.
    assert any("Study tasks finish" in r for r in _reasons(_open(ana, ana_task["id"])))
    assert not any("Study tasks finish" in r for r in _reasons(_open(ben, ben_task["id"])))

    # Ben cannot snooze Ana's task, so her snooze count cannot be changed by him.
    assert ben.post(f"/api/tasks/{ana_task['id']}/snooze", json={"until": _iso(1)}).status_code == 404
    assert not any(r.startswith("Snoozed") for r in _reasons(_open(ana, ana_task["id"])))

    # Ben's own red tasks never reach Ana's pet.
    at_risk = ana.get("/api/pet/state").json()["at_risk"]
    assert at_risk is None or at_risk["task_id"] != ben_task["id"]
