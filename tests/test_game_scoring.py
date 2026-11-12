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


def test_priority_is_raised_by_deadline_pressure_but_never_lowered():
    from app.game.scoring import effective_priority

    eff = lambda base, due, source=None, status="open": effective_priority(base, source, due, TODAY, status)
    # within 2 days or overdue -> High
    assert eff("Low", "2026-10-30") == "High" and eff("Medium", "2026-11-01") == "High"
    assert eff("Low", "2026-10-20") == "High"
    # Low within 5 days -> Medium; Medium stays Medium until 2 days out
    assert eff("Low", "2026-11-04") == "Medium"
    assert eff("Medium", "2026-11-04") == "Medium"
    # far away or undated: unchanged
    assert eff("Low", "2026-11-20") == "Low" and eff("Low", None) == "Low"
    # never lowers
    assert eff("High", "2026-12-25") == "High"


def test_a_chosen_priority_or_a_closed_task_is_never_raised():
    from app.game.scoring import effective_priority

    assert effective_priority("Low", "user", "2026-10-30", TODAY) == "Low"
    assert effective_priority("Low", None, "2026-10-30", TODAY, status="completed") == "Low"
    assert effective_priority("Medium", None, "2026-10-30", TODAY, status="dismissed") == "Medium"


def _at(text, tzname="UTC", now=None):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    from app.game.voice_task import parse_spoken_task

    now = now or datetime(2026, 10, 31, 10, 54, tzinfo=timezone.utc)
    tz = ZoneInfo(tzname)
    return parse_spoken_task(text, now.astimezone(tz).date(), now, tz), tz


def _local(result, tz):
    return result["remind_at"].astimezone(tz).strftime("%H:%M") if result["remind_at"] else None


def test_relative_reminders_become_a_time_and_leave_the_task_wording():
    r, tz = _at("Order in 2 minutes")
    assert (r["text"], _local(r, tz), r["due_on"]) == ("Order", "10:56", "2026-10-31")
    r, tz = _at("Send report in an hour")
    assert _local(r, tz) == "11:54"
    r, tz = _at("Stretch in half an hour")
    assert _local(r, tz) == "11:24"


def test_remind_me_phrase_wins_over_other_times_in_the_sentence():
    r, tz = _at("i need to send a meeting link in 20 minutes. remind me in 5 mins")
    assert r["text"] == "Send a meeting link in 20 minutes"
    assert _local(r, tz) == "10:59"


def test_clock_times_use_the_persons_time_zone():
    r, tz = _at("Call mom at 5pm", "Asia/Kolkata")  # it is 16:24 there
    assert _local(r, tz) == "17:00" and r["text"] == "Call mom"
    r, tz = _at("Pay the bill tomorrow at 9am, high priority", "Asia/Kolkata")
    assert (_local(r, tz), r["due_on"], r["priority"]) == ("09:00", "2026-11-01", "High")


def test_a_time_that_has_already_passed_today_is_not_scheduled():
    r, _ = _at("meeting at 3:30 pm today", "Asia/Kolkata")  # 15:30 < 16:24 local
    assert r["remind_at"] is None
    r, tz = _at("Water the plants at 9am")  # 9am passed (10:54 UTC), no day named -> tomorrow
    assert _local(r, tz) == "09:00" and r["due_on"] == "2026-11-01"


def test_no_time_means_no_reminder_and_bad_clocks_are_ignored():
    assert _at("remind me to order")[0]["remind_at"] is None
    assert _at("buy milk")[0]["remind_at"] is None
    r, _ = _at("Read at 25:00")
    assert r["remind_at"] is None and r["text"] == "Read at 25:00"
