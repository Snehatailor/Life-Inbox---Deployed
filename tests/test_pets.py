"""Coin shop, pets, saved slots and pet reminders."""

from datetime import datetime, timedelta, timezone

from app.game.reminders import build_reminders, reminder_phase, validate_slot
from app.game.shop import PETS, pet_by_id, spendable_balance

from tests.test_api import client  # noqa: F401  (fixture)
from tests.test_isolation import _login, app_env  # noqa: F401  (fixture + helper)

NOW = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)


def _slot(start_min, length=45):
    start = NOW + timedelta(minutes=start_min)
    return start, start + timedelta(minutes=length)


def test_catalog_is_sane():
    assert pet_by_id("cat")["price"] == 0
    assert len({p["id"] for p in PETS}) == len(PETS) and all(p["emoji"] for p in PETS)
    assert [p["price"] for p in PETS] == sorted(p["price"] for p in PETS)


def test_spendable_balance_is_floored_and_does_not_touch_earned():
    assert spendable_balance(130, 40) == 90
    assert spendable_balance(10, 40) == 0  # coins were revoked after a purchase


def test_reminder_phases():
    s, e = _slot(30)
    assert reminder_phase(s, e, NOW) == "later"
    s, e = _slot(8)
    assert reminder_phase(s, e, NOW) == "soon"
    s, e = _slot(-10, 45)
    assert reminder_phase(s, e, NOW) == "now"
    s, e = _slot(-90, 45)  # ended 45 min ago
    assert reminder_phase(s, e, NOW) == "missed"
    s, e = _slot(-400, 45)
    assert reminder_phase(s, e, NOW) is None
    s, e = _slot(60 * 30)
    assert reminder_phase(s, e, NOW) is None  # more than a day away


def test_build_reminders_sorts_and_skips_closed_or_unslotted_tasks():
    def task(i, status, start_min):
        s, e = _slot(start_min)
        return {"id": i, "text": f"t{i}", "priority": "High", "status": status,
                "slot_start": s.isoformat(), "slot_end": e.isoformat()}

    tasks = [task(1, "open", 40), task(2, "open", 5), task(3, "completed", 5),
             {"id": 4, "text": "no slot", "priority": "Low", "status": "open", "slot_start": None, "slot_end": None}]
    result = build_reminders(tasks, NOW)
    assert [r["task_id"] for r in result] == [2, 1]
    assert result[0]["phase"] == "soon" and result[0]["label"] == "in 5 min"
    assert result[1]["label"] == "in 40 min"


def test_slot_validation():
    s, e = _slot(0, 30)
    validate_slot(s, e)
    for bad in [(e, s), (s, s + timedelta(hours=9))]:
        try:
            validate_slot(*bad)
        except ValueError:
            continue
        raise AssertionError("expected a ValueError")
    try:
        validate_slot(datetime(2026, 1, 1, 9), datetime(2026, 1, 1, 10))
    except ValueError:
        pass
    else:
        raise AssertionError("naive times must be rejected")


def _earn(client, coins):
    while coins > 0:
        task = client.post("/api/tasks/quick", json={"sentence": "Do a thing today, high priority"}).json()
        client.post(f"/api/tasks/{task['id']}/complete")
        coins -= 30


def test_shop_flow_buy_select_and_insufficient_funds(client):
    shop = client.get("/api/shop").json()
    assert shop["balance"] == 0 and shop["active_pet"] == "cat"
    owned = {i["id"] for i in shop["items"] if i["owned"]}
    assert owned == {"cat"}

    assert client.post("/api/shop/buy", json={"item_id": "dog"}).status_code == 402  # 40 coins needed
    assert client.post("/api/shop/buy", json={"item_id": "nope"}).status_code == 404
    assert client.post("/api/pet/select", json={"pet_id": "dog"}).status_code == 400  # not owned yet

    _earn(client, 60)
    assert client.get("/api/shop").json()["balance"] == 60
    bought = client.post("/api/shop/buy", json={"item_id": "dog"}).json()
    assert bought["balance"] == 20 and bought["spent"] == 40 and bought["earned"] == 60
    assert client.post("/api/shop/buy", json={"item_id": "dog"}).status_code == 409  # already owned

    # spending never lowers daily progress or the level
    assert client.get("/api/game/today").json()["points_today"] == 60

    selected = client.post("/api/pet/select", json={"pet_id": "dog"}).json()
    assert selected["active_pet"] == "dog"
    assert [i["id"] for i in selected["items"] if i["active"]] == ["dog"]
    assert client.post("/api/pet/select", json={"pet_id": "cat"}).json()["active_pet"] == "cat"  # starter is always owned


def test_a_new_pet_starts_with_its_own_name(client):
    _earn(client, 60)
    client.post("/api/shop/buy", json={"item_id": "dog"})
    client.patch("/api/pet/settings", json={"name": "Luna"})
    assert client.get("/api/pet/state").json()["pet"]["name"] == "Luna"
    client.post("/api/pet/select", json={"pet_id": "dog"})
    assert client.get("/api/pet/state").json()["pet"]["name"] == "Biscuit"  # not "Luna"
    client.post("/api/pet/select", json={"pet_id": "dog"})  # choosing the same pet keeps its name
    client.patch("/api/pet/settings", json={"name": "Rex"})
    client.post("/api/pet/select", json={"pet_id": "dog"})
    assert client.get("/api/pet/state").json()["pet"]["name"] == "Rex"


def test_pet_state_reports_pet_name_settings_and_reminders(client):
    state = client.get("/api/pet/state").json()
    assert state["pet"]["emoji"] == "🐱" and state["pet"]["name"] == "Mochi"
    assert state["in_page"] is False and state["reminders"] == []

    renamed = client.patch("/api/pet/settings", json={"name": "  Luna  ", "in_page": True}).json()
    assert renamed["pet"]["name"] == "Luna" and renamed["in_page"] is True
    assert client.patch("/api/pet/settings", json={"name": ""}).json()["pet"]["name"] == "Mochi"

    task = client.post("/api/tasks/quick", json={"sentence": "Call the bank today"}).json()
    start = datetime.now(timezone.utc) + timedelta(minutes=5)
    saved = client.post(f"/api/tasks/{task['id']}/slot", json={
        "start": start.isoformat(), "end": (start + timedelta(minutes=30)).isoformat()}).json()
    assert saved["slot_start"] and saved["slot_end"]

    reminders = client.get("/api/pet/state").json()["reminders"]
    assert [(r["task_id"], r["phase"]) for r in reminders] == [(task["id"], "soon")]
    assert client.get("/api/pet/state").json()["due_today"] == []  # it has a slot, so it isn't "unscheduled"

    # completing the task ends its reminders
    client.post(f"/api/tasks/{task['id']}/complete")
    assert client.get("/api/pet/state").json()["reminders"] == []


def test_slot_endpoints_validate_and_can_clear(client):
    task = client.post("/api/tasks/quick", json={"sentence": "Write report"}).json()
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    ok = {"start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat()}
    assert client.post(f"/api/tasks/{task['id']}/slot", json=ok).status_code == 200
    assert client.post(f"/api/tasks/{task['id']}/slot",
                       json={"start": ok["end"], "end": ok["start"]}).status_code == 400
    assert client.post(f"/api/tasks/{task['id']}/slot",
                       json={"start": "2026-11-02T10:00:00", "end": "2026-11-02T11:00:00"}).status_code == 400  # no zone
    cleared = client.delete(f"/api/tasks/{task['id']}/slot").json()
    assert cleared["slot_start"] is None
    assert client.post("/api/tasks/9999/slot", json=ok).status_code == 404


def test_each_person_has_their_own_wallet_and_pet(app_env):
    ana, ben = app_env.make_client(), app_env.make_client()
    _login(ana, "ana@example.com")
    _login(ben, "ben@example.com")
    _earn(ana, 60)
    assert ana.post("/api/shop/buy", json={"item_id": "dog"}).status_code == 200
    ana.post("/api/pet/select", json={"pet_id": "dog"})

    assert ben.get("/api/shop").json()["balance"] == 0
    assert ben.get("/api/shop").json()["active_pet"] == "cat"
    assert ben.post("/api/pet/select", json={"pet_id": "dog"}).status_code == 400  # Ana's purchase isn't Ben's
    assert ben.get("/api/pet/state").json()["pet"]["id"] == "cat"


def test_remind_later_moves_the_slot_and_keeps_its_length(client):
    task = client.post("/api/tasks/quick", json={"sentence": "Send the meeting link in 20 minutes"}).json()
    first = datetime.fromisoformat(task["slot_start"])
    length = datetime.fromisoformat(task["slot_end"]) - first

    later = client.post(f"/api/tasks/{task['id']}/remind-later", json={"minutes": 5}).json()
    start = datetime.fromisoformat(later["slot_start"])
    assert 4 <= (start - datetime.now(timezone.utc)).total_seconds() / 60 <= 5.1
    assert datetime.fromisoformat(later["slot_end"]) - start == length  # same length as before
    assert later["slot_set_at"]

    # it was just snoozed, so the pet waits for the time instead of a pointless heads-up
    reminders = client.get("/api/pet/state").json()["reminders"]
    assert [(r["task_id"], r["lead_minutes"]) for r in reminders] == [(task["id"], 5)]


def test_remind_later_works_on_a_task_with_no_slot_and_validates(client):
    task = client.post("/api/tasks/quick", json={"sentence": "Order lunch"}).json()
    assert task["slot_start"] is None
    later = client.post(f"/api/tasks/{task['id']}/remind-later", json={}).json()  # default 5 minutes
    assert later["slot_start"] is not None

    assert client.post(f"/api/tasks/{task['id']}/remind-later", json={"minutes": 0}).status_code == 422
    assert client.post(f"/api/tasks/{task['id']}/remind-later", json={"minutes": 999}).status_code == 422
    assert client.post("/api/tasks/9999/remind-later", json={"minutes": 5}).status_code == 404
    client.post(f"/api/tasks/{task['id']}/complete")
    assert client.post(f"/api/tasks/{task['id']}/remind-later", json={"minutes": 5}).status_code == 400
