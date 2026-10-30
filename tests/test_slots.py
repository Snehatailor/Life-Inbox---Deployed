from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.game.slots import parse_ics_busy, suggest_slots

UTC = ZoneInfo("UTC")
# Monday 2026-11-02, 08:00 UTC
NOW = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)


def _dt(day, hour, minute=0):
    return datetime(2026, 11, day, hour, minute, tzinfo=timezone.utc)


def test_first_free_slot_is_at_work_start_when_calendar_empty():
    slots = suggest_slots([], 45, date(2026, 11, 6), NOW, UTC)
    assert [s["day"] for s in slots] == ["2026-11-02", "2026-11-03", "2026-11-04"]
    assert slots[0]["label"] == "Mon Nov 2 · 09:00–09:45"


def test_meeting_pushes_slot_after_it():
    busy = [(_dt(2, 9), _dt(2, 11, 20))]
    slot = suggest_slots(busy, 60, date(2026, 11, 2), NOW, UTC)[0]
    assert slot["label"].endswith("11:30–12:30")  # rounded up to a quarter hour


def test_gap_between_meetings_is_used_when_long_enough():
    busy = [(_dt(2, 9), _dt(2, 10)), (_dt(2, 11), _dt(2, 12))]
    assert suggest_slots(busy, 60, date(2026, 11, 2), NOW, UTC)[0]["label"].endswith("10:00–11:00")
    # 90 minutes does not fit the gap, so it goes after the second meeting
    assert suggest_slots(busy, 90, date(2026, 11, 2), NOW, UTC)[0]["label"].endswith("12:00–13:30")


def test_no_slot_when_day_is_full_and_deadline_is_today():
    busy = [(_dt(2, 9), _dt(2, 18))]
    assert suggest_slots(busy, 30, date(2026, 11, 2), NOW, UTC) == []


def test_never_suggests_past_the_deadline_or_on_weekends():
    friday = datetime(2026, 11, 6, 8, 0, tzinfo=timezone.utc)
    slots = suggest_slots([], 45, date(2026, 11, 9), friday, UTC)
    assert [s["day"] for s in slots] == ["2026-11-06", "2026-11-09"]


def test_today_starts_after_now_not_before():
    late = datetime(2026, 11, 2, 14, 7, tzinfo=timezone.utc)
    assert suggest_slots([], 30, date(2026, 11, 2), late, UTC)[0]["label"].endswith("14:15–14:45")


def test_ics_parsing_ignores_all_day_and_transparent_events():
    ics = "\r\n".join([
        "BEGIN:VCALENDAR",
        "BEGIN:VEVENT", "DTSTART:20261102T100000Z", "DTEND:20261102T110000Z", "SUMMARY:Standup", "END:VEVENT",
        "BEGIN:VEVENT", "DTSTART;VALUE=DATE:20261103", "DTEND;VALUE=DATE:20261104", "SUMMARY:Deadline", "END:VEVENT",
        "BEGIN:VEVENT", "DTSTART:20261102T130000Z", "DTEND:20261102T140000Z", "TRANSP:TRANSPARENT", "END:VEVENT",
        "BEGIN:VEVENT", "DTSTART;TZID=America/New_York:20261102T090000", "DURATION:PT30M",
        "SUMMARY:Long", " Name", "END:VEVENT",
        "END:VCALENDAR",
    ])
    blocks = parse_ics_busy(ics, UTC)
    assert len(blocks) == 2
    assert blocks[0]["summary"] == "Standup"
    assert blocks[1]["summary"] == "LongName"
    assert blocks[1]["starts_at"].startswith("2026-11-02T14:00:00")  # 09:00 NY = 14:00 UTC
