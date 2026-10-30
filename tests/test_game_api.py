"""Task Quest API: points, bin, quick-add, task drag, domain correction."""

from datetime import timedelta

from app.attention.dates import today_in_configured_tz

from tests.test_api import client  # noqa: F401  (fixture)


def _quick(client, sentence):
    response = client.post("/api/tasks/quick", json={"sentence": sentence})
    assert response.status_code == 200, response.text
    return response.json()


def _iso(days):
    return (today_in_configured_tz() + timedelta(days=days)).isoformat()


def test_quick_task_parses_priority_and_date(client):
    task = _quick(client, "Submit the report in 3 days, high priority")
    assert task["text"] == "Submit the report"
    assert task["priority"] == "High"
    assert task["due_on"] == _iso(3)
    assert task["days_left"] == 3 and task["urgency"] == "safe"
    assert task["points_value"] == 30


def test_points_awarded_once_and_revoked_on_reopen(client):
    task = _quick(client, "Pay rent today, medium priority")
    done = client.post(f"/api/tasks/{task['id']}/complete").json()
    assert done["points_awarded"] == 20
    assert client.get("/api/game/today").json()["points_today"] == 20

    client.post(f"/api/tasks/{task['id']}/reopen")
    assert client.get("/api/game/today").json()["points_today"] == 0

    client.post(f"/api/tasks/{task['id']}/complete")
    assert client.get("/api/game/today").json()["points_today"] == 20


def test_early_bonus_and_overdue_half(client):
    early = _quick(client, f"Early one {_iso(3)} high priority")
    late = _quick(client, f"Late one {_iso(-2)} high priority")
    assert client.post(f"/api/tasks/{early['id']}/complete").json()["points_awarded"] == 35
    assert client.post(f"/api/tasks/{late['id']}/complete").json()["points_awarded"] == 15


def test_goal_met_after_100_points(client):
    for _ in range(4):
        task = _quick(client, "Do a thing today, high priority")
        client.post(f"/api/tasks/{task['id']}/complete")
    summary = client.get("/api/game/today").json()
    assert summary["points_today"] == 120
    assert summary["goal_met"] and summary["percent"] == 100
    assert summary["streak"] == 1


def test_bin_keeps_points_and_moves_to_backlog(client):
    task = _quick(client, "File taxes today, high priority")
    assert client.post(f"/api/tasks/{task['id']}/bin").status_code == 409  # still open

    client.post(f"/api/tasks/{task['id']}/complete")
    binned = client.post(f"/api/tasks/{task['id']}/bin").json()
    assert binned["binned_at"] and binned["points_awarded"] == 30
    assert client.get("/api/tasks?status=completed").json() == []
    assert [t["id"] for t in client.get("/api/tasks?status=backlog").json()] == [task["id"]]
    assert client.get("/api/game/today").json()["points_today"] == 30

    restored = client.post(f"/api/tasks/{task['id']}/restore").json()
    assert restored["binned_at"] is None
    assert len(client.get("/api/tasks?status=completed").json()) == 1


def test_patch_task_priority_and_deadline(client):
    task = _quick(client, "Plan trip")
    response = client.patch(
        f"/api/tasks/{task['id']}", json={"priority": "High", "due_on": _iso(2)}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["priority"] == "High" and body["points_value"] == 30
    assert body["days_left"] == 2 and body["timing_confirmed"] is True

    assert client.patch(f"/api/tasks/{task['id']}", json={"due_on": "tomorrow"}).status_code == 422
    client.post(f"/api/tasks/{task['id']}/complete")
    assert client.patch(f"/api/tasks/{task['id']}", json={"priority": "Low"}).status_code == 400


def test_tasks_are_isolated_in_game_summary_and_ics(client):
    task = _quick(client, "Call dentist tomorrow")
    ics = client.get("/api/calendar/export.ics")
    assert ics.status_code == 200 and "Call dentist" in ics.text
    assert task["google_event_url"].startswith("https://calendar.google.com/")


def test_text_file_drop_and_domain_correction(client):
    response = client.post(
        "/api/items/textfile",
        files={"file": ("budget.csv", b"month,amount\nrent,1200\nbill,80\n", "text/csv")},
    )
    assert response.status_code == 200
    item = response.json()
    assert item["file_format"] == "spreadsheet" and item["domain"] == "Finance"

    moved = client.patch(f"/api/items/{item['id']}/domain", json={"domain": "Work"}).json()
    assert moved["domain"] == "Work" and moved["domain_source"] == "user"
    assert client.get(f"/api/items/{item['id']}").json()["domain"] == "Work"

    cleared = client.patch(f"/api/items/{item['id']}/domain", json={"domain": None}).json()
    assert cleared["domain"] == "Finance" and cleared["domain_source"] == "auto"

    assert client.patch(f"/api/items/{item['id']}/domain", json={"domain": "Nope"}).status_code == 400


def test_unsupported_and_empty_text_files_are_rejected(client):
    bad = client.post("/api/items/textfile", files={"file": ("a.docx", b"x", "application/octet-stream")})
    assert bad.status_code == 415
    empty = client.post("/api/items/textfile", files={"file": ("a.txt", b"  \n", "text/plain")})
    assert empty.status_code == 400


def _high_task(client, days):
    return _quick(client, f"Prepare slides {_iso(days)} high priority")


def test_slots_without_calendar_use_working_hours(client):
    task = _high_task(client, 3)
    result = client.get(f"/api/tasks/{task['id']}/slots?minutes=45").json()
    assert result["calendar_loaded"] is False
    assert 1 <= len(result["slots"]) <= 3
    assert result["slots"][0]["google_url"].startswith("https://calendar.google.com/")
    assert client.get(f"/api/tasks/{task['id']}/slots?minutes=5").status_code == 422
    assert client.get("/api/tasks/9999/slots").status_code == 404


def test_imported_busy_blocks_are_avoided_and_clearable(client):
    task = _high_task(client, 2)
    first_day = client.get(f"/api/tasks/{task['id']}/slots?minutes=60").json()["slots"][0]
    start = first_day["start"]
    stamp = start[:19].replace("-", "").replace(":", "")
    ics = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\n"
        f"DTSTART:{stamp}Z\r\nDTEND:{stamp[:9]}{int(stamp[9:11]) + 2:02d}{stamp[11:]}Z\r\n"
        "SUMMARY:Planning\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
    )
    imported = client.post(
        "/api/calendar/busy/import", files={"file": ("cal.ics", ics.encode(), "text/calendar")}
    )
    assert imported.status_code == 200 and imported.json()["imported"] == 1
    assert client.get("/api/calendar/busy").json()["count"] == 1

    after = client.get(f"/api/tasks/{task['id']}/slots?minutes=60").json()
    assert after["calendar_loaded"] is True
    assert after["slots"][0]["start"] != start

    assert client.delete("/api/calendar/busy").status_code == 204
    assert client.get("/api/calendar/busy").json()["count"] == 0


def test_bad_calendar_files_are_rejected(client):
    bad = client.post("/api/calendar/busy/import", files={"file": ("x.ics", b"hello", "text/calendar")})
    assert bad.status_code == 400


def test_briefing_endpoint_reads_real_tasks(client):
    _quick(client, "Pay rent today, high priority")
    _quick(client, f"Write report {_iso(-1)}")
    body = client.get("/api/game/briefing").json()
    assert body["due_today"] == 1 and body["overdue"] == 1
    assert "Pay rent" in body["text"] and "Write report" in body["text"]
    assert "0 of 100 coins, 100 to go" in body["text"]


def test_tasks_get_a_domain_that_a_person_can_override(client):
    task = _quick(client, "Call the dentist tomorrow")
    assert task["domain"] == "Health" and task["domain_source"] == "auto"

    moved = client.patch(f"/api/tasks/{task['id']}", json={"domain": "Work"}).json()
    assert moved["domain"] == "Work" and moved["domain_source"] == "user"
    cleared = client.patch(f"/api/tasks/{task['id']}", json={"domain": None}).json()
    assert cleared["domain"] == "Health" and cleared["domain_source"] == "auto"
    assert client.patch(f"/api/tasks/{task['id']}", json={"domain": "Nope"}).status_code == 400


def test_edit_task_text_and_priority_together(client):
    task = _quick(client, "Draft  the   memo")
    body = client.patch(
        f"/api/tasks/{task['id']}", json={"text": "  Send the final memo ", "priority": "High"}
    ).json()
    assert body["text"] == "Send the final memo" and body["priority"] == "High"
    assert client.patch(f"/api/tasks/{task['id']}", json={"text": ""}).status_code == 422


def test_delete_moves_open_task_to_backlog_and_restore_reopens_it(client):
    task = _quick(client, "Water plants today")
    deleted = client.post(f"/api/tasks/{task['id']}/delete").json()
    assert deleted["status"] == "dismissed" and deleted["binned_at"]
    assert client.get("/api/tasks?status=open").json() == []
    assert [t["id"] for t in client.get("/api/tasks?status=backlog").json()] == [task["id"]]
    assert client.post(f"/api/tasks/{task['id']}/delete").status_code == 409  # already deleted

    restored = client.post(f"/api/tasks/{task['id']}/restore").json()
    assert restored["status"] == "open" and restored["binned_at"] is None
    assert [t["id"] for t in client.get("/api/tasks?status=open").json()] == [task["id"]]


def test_sections_group_tasks_and_items_by_domain(client):
    _quick(client, "Call the dentist tomorrow")
    done = _quick(client, "Pay the rent bill today")
    client.post(f"/api/tasks/{done['id']}/complete")
    client.post("/api/items", json={"raw_text": "Flight and hotel booking for the trip"})

    sections = {s["domain"]: s for s in client.get("/api/sections").json()["sections"]}
    assert [t["text"] for t in sections["Health"]["tasks"]] == ["Call the dentist"]
    assert sections["Finance"]["tasks"] == [] and sections["Finance"]["done_count"] == 1
    assert sections["Travel"]["item_count"] == 1
    assert list(sections)[-1] == "Unsorted"


def test_done_tasks_show_on_calendar_and_in_search_but_not_in_open_list(client):
    task = _quick(client, "Submit the tax return today, high priority")
    client.post(f"/api/tasks/{task['id']}/complete")

    assert client.get("/api/tasks?status=open").json() == []
    entries = [e for e in client.get("/api/calendar/tasks").json() if e["source"] == "done"]
    assert len(entries) == 1 and entries[0]["text"] == "Submit the tax return"
    assert entries[0]["points"] == 30 and entries[0]["due_on"] == _iso(0)

    found = client.get("/api/find?q=tax").json()
    assert [(t["text"], t["state"]) for t in found["tasks"]] == [("Submit the tax return", "done")]

    client.post(f"/api/tasks/{task['id']}/bin")
    assert [e for e in client.get("/api/calendar/tasks").json() if e["source"] == "done"] == []
    assert client.get("/api/find?q=tax").json()["tasks"][0]["state"] == "done (binned)"
    assert client.get("/api/find?q=").json() == {"tasks": [], "items": []}


def test_deadline_raises_an_automatic_priority_and_points_follow(client):
    near = _quick(client, f"Prepare handout {_iso(2)}")          # no priority given -> Medium
    far = _quick(client, f"Read the manual {_iso(4)}")
    assert (near["base_priority"], near["priority"], near["priority_raised"]) == ("Medium", "High", True)
    assert near["points_value"] == 30
    assert (far["priority"], far["priority_raised"]) == ("Medium", False) and far["points_value"] == 20

    done = client.post(f"/api/tasks/{near['id']}/complete").json()
    assert done["points_awarded"] == 35  # High (30) because it was raised, +5 for finishing early
    # completed tasks keep their level and are not raised again
    assert done["priority_raised"] is False


def test_overdue_tasks_land_in_high(client):
    late = _quick(client, f"Send the form {_iso(-3)}")
    assert late["priority"] == "High" and late["priority_raised"] is True
    assert [t["id"] for t in client.get("/api/tasks?status=open").json() if t["priority"] == "High"] == [late["id"]]


def test_a_priority_you_chose_is_never_raised(client):
    spoken = _quick(client, "Water the plants today, low priority")
    assert (spoken["priority"], spoken["priority_raised"], spoken["priority_source"]) == ("Low", False, "user")

    auto = _quick(client, "Book the room today")
    assert auto["priority"] == "High" and auto["priority_raised"]
    pinned = client.patch(f"/api/tasks/{auto['id']}", json={"priority": "Medium"}).json()
    assert (pinned["priority"], pinned["priority_raised"], pinned["priority_source"]) == ("Medium", False, "user")
    levels = {t["id"]: t["priority"] for t in client.get("/api/tasks?status=open").json()}
    assert levels == {spoken["id"]: "Low", auto["id"]: "Medium"}  # both stay where the person put them
