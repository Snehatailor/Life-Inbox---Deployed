"""Procrastination Radar: pure scoring rules."""

from datetime import date, datetime, timedelta, timezone

from app.game.radar import (
    assess,
    crowd_points,
    deadline_points,
    history_points,
    lateness_by_domain,
    level_for,
    rescue_bonus,
)

TODAY = date(2026, 11, 4)
NOW = datetime(2026, 11, 4, 9, 0, tzinfo=timezone.utc)


def _day(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


def _task(**fields):
    base = {"id": 1, "text": "Python end term", "priority": "High", "domain": "Study",
            "due_on": _day(3), "slot_start": None, "slot_end": None}
    base.update(fields)
    return base


def _assess(task, snoozes=0, lateness=None, open_tasks=None):
    return assess(task, snoozes=snoozes, domain_lateness=lateness or {},
                  open_tasks=open_tasks or [task], today=TODAY, now=NOW)


def test_deadline_points_rise_as_the_day_nears():
    assert [deadline_points(d) for d in (None, 10, 7, 4, 3, 2, 1, 0, -1)] == [
        0, 0, 10, 20, 20, 25, 30, 35, 40,
    ]


def test_level_boundaries():
    assert [level_for(s) for s in (0, 39, 40, 69, 70, 100)] == [
        "on_track", "on_track", "watch", "watch", "at_risk", "at_risk",
    ]


def test_small_helpers():
    assert [history_points(v) for v in (None, -1, 0, 0.5, 1, 1.5, 2, 5)] == [0, 0, 0, 5, 12, 12, 20, 20]
    assert [crowd_points(n) for n in (0, 1, 2, 3, 4, 9)] == [0, 0, 5, 10, 15, 15]
    assert rescue_bonus(69) == 0 and rescue_bonus(70) == 10


def test_the_worked_example_is_at_risk_and_every_point_has_a_reason():
    task = _task()
    crowd = [task] + [_task(id=i, text=f"Other {i}", due_on=_day(2)) for i in range(2, 6)]
    result = _assess(task, snoozes=2, lateness={"Study": 1.5}, open_tasks=crowd)
    assert result["score"] == 77 and result["level"] == "at_risk"
    assert sum(r["points"] for r in result["reasons"]) == 77
    texts = [r["text"] for r in result["reasons"]]
    assert texts == [
        "Due in 3 days",
        "Snoozed 2 times",
        "Your Study tasks finish 1.5 days late on average",
        "4 other High tasks due around then",
        "High priority with no time booked",
    ]
    # Snoozes never count toward the rescue bonus.
    assert result["rescue_score"] == 57


def test_new_person_with_far_deadline_is_on_track():
    result = _assess(_task(due_on=_day(17)))
    assert result == {"score": 0, "level": "on_track", "reasons": [], "rescue_score": 0}


def test_no_deadline_stays_green_even_with_snoozes():
    result = _assess(_task(due_on=None), snoozes=1)
    assert result["level"] == "on_track" and result["score"] == 10


def test_a_booked_slot_lowers_the_score_and_removes_the_no_time_reason():
    slot_start = (NOW + timedelta(hours=1)).isoformat()
    slot_end = (NOW + timedelta(hours=2)).isoformat()
    result = _assess(_task(due_on=_day(0), slot_start=slot_start, slot_end=slot_end))
    assert result["score"] == 35 - 15
    assert [r["text"] for r in result["reasons"]] == ["Due today", "Time slot booked"]
    # Starting work must not cost the rescue bonus: booking is ignored there.
    assert result["rescue_score"] == 35 + 10


def test_a_past_slot_does_not_count_as_scheduled():
    old = (NOW - timedelta(days=1)).isoformat()
    result = _assess(_task(due_on=_day(0), slot_start=old, slot_end=old))
    assert result["score"] == 35 + 10


def test_snoozes_are_capped_and_score_never_passes_100():
    result = _assess(_task(due_on=_day(-3)), snoozes=9, lateness={"Study": 4},
                     open_tasks=[_task(id=i, due_on=_day(-2)) for i in range(1, 7)])
    assert result["score"] == 100
    assert next(r for r in result["reasons"] if r["text"].startswith("Snoozed"))["points"] == 30


def test_crowding_only_counts_other_high_tasks_near_the_deadline():
    task = _task(due_on=_day(5))
    others = [
        _task(id=2, due_on=_day(8)),                    # 3 days after: counts
        _task(id=3, due_on=_day(2)),                    # 3 days before: counts
        _task(id=4, due_on=_day(9)),                    # 4 days away: no
        _task(id=5, due_on=_day(5), priority="Low"),    # not High: no
        _task(id=6, due_on=None),                       # no date: no
    ]
    result = _assess(task, open_tasks=[task, *others])
    assert {"points": 5, "text": "2 other High tasks due around then"} in result["reasons"]


def test_lateness_needs_three_recent_samples_per_domain():
    finished = [
        ("Study", _day(-10), TODAY - timedelta(days=8)),   # 2 days late
        ("Study", _day(-5), TODAY - timedelta(days=4)),    # 1 day late
        ("Study", _day(-3), TODAY - timedelta(days=3)),    # on time
        ("Home", _day(-2), TODAY),                         # only two Home samples
        ("Home", _day(-1), TODAY),
        ("Work", None, TODAY),                             # no deadline: ignored
        ("Work", _day(-60), TODAY - timedelta(days=40)),   # too old
    ]
    assert lateness_by_domain(finished, TODAY) == {"Study": 1.0}
