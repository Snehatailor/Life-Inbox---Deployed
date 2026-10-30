from datetime import date

from app.game.scoring import (
    days_left,
    days_left_label,
    default_due_offset,
    points_for,
    urgency,
)

TODAY = date(2026, 10, 30)


def test_points_by_priority_on_due_day():
    assert points_for("High", "2026-10-30", TODAY) == 30
    assert points_for("Medium", "2026-10-30", TODAY) == 20
    assert points_for("Low", None, TODAY) == 10


def test_early_bonus_and_overdue_half():
    assert points_for("Medium", "2026-11-02", TODAY) == 25
    assert points_for("High", "2026-10-28", TODAY) == 15


def test_days_left_and_labels():
    assert days_left("2026-11-02", TODAY) == 3
    assert days_left_label("2026-10-31", TODAY) == "1 day left"
    assert days_left_label("2026-10-30", TODAY) == "Due today"
    assert days_left_label("2026-10-27", TODAY) == "3 days overdue"
    assert days_left_label(None, TODAY) is None


def test_urgency_levels():
    assert urgency("2026-10-29", TODAY) == "overdue"
    assert urgency("2026-10-30", TODAY) == "due"
    assert urgency("2026-11-01", TODAY) == "soon"
    assert urgency("2026-11-10", TODAY) == "safe"
    assert urgency(None, TODAY) == "none"


def test_default_due_offsets():
    assert default_due_offset("High") < default_due_offset("Medium") < default_due_offset("Low")


def test_summary_streak_and_levels():
    from app.game.progress import build_game_summary, level_for

    by_day = {"2026-10-28": 100, "2026-10-29": 120, "2026-10-30": 40}
    summary = build_game_summary(by_day, TODAY, 2)
    assert summary["points_today"] == 40
    assert summary["percent"] == 40
    assert summary["streak"] == 2  # today not done yet, yesterday counts
    assert summary["lifetime_points"] == 260
    assert summary["level"]["title"] == "Adventurer"
    assert len(summary["history"]) == 7
    assert level_for(5000)["next_at"] is None


def test_parse_spoken_task():
    from app.game.voice_task import parse_spoken_task

    r = parse_spoken_task("Call the dentist on Friday, high priority", today=date(2026, 10, 30))
    assert r["text"] == "Call the dentist"
    assert r["priority"] == "High"
    assert r["due_on"] == "2026-11-06"

    r = parse_spoken_task("remind me to buy milk tomorrow", today=date(2026, 10, 30))
    assert r["text"] == "Buy milk"
    assert r["priority"] == "Medium" and r["due_on"] == "2026-10-31"

    r = parse_spoken_task("water the plants, low priority, in 3 days", today=date(2026, 10, 30))
    assert (r["priority"], r["due_on"], r["text"]) == ("Low", "2026-11-02", "Water the plants")

    r = parse_spoken_task("think about holidays")
    assert r["due_on"] is None and r["priority"] == "Medium"


def test_google_link_and_ics_escaping():
    from app.game.gcal import build_ics, google_event_url

    url = google_event_url("[High] Pay rent", "2026-11-05", "From Life Inbox")
    assert "dates=20261105%2F20261106" in url and url.startswith("https://calendar.google.com/")
    ics = build_ics([{"id": 1, "due_on": "2026-11-05", "priority": "High", "text": "a, b; c", "points_value": 30},
                     {"id": 2, "due_on": None, "priority": "Low", "text": "skip", "points_value": 10}])
    assert r"a\, b\; c" in ics and "skip" not in ics and ics.count("BEGIN:VEVENT") == 1
