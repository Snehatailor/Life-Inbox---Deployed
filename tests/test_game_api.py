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
    assert "0 of 100 points, 100 to go" in body["text"]
