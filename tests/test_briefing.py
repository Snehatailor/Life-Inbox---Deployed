from datetime import date

from app.game.briefing import build_briefing, greeting

TODAY = date(2026, 11, 2)
SUMMARY = {"points_today": 70, "goal": 100, "goal_met": False, "streak": 2}


def _task(text, days_left, points=20):
    return {"text": text, "days_left": days_left, "points_value": points}


def test_greeting_by_hour():
    assert greeting(8) == "Good morning." and greeting(14) == "Good afternoon." and greeting(21) == "Good evening."


def test_full_briefing_mentions_overdue_due_next_and_points():
    tasks = [_task("Renew passport", -2, 30), _task("Book dentist", 0, 20), _task("Plan trip", 3, 10),
             _task("Send report", 1, 30)]
    result = build_briefing(tasks, SUMMARY, TODAY, 9)
    text = result["text"]
    assert text.startswith("Good morning.")
    assert "1 task overdue: Renew passport." in text
    assert "1 task due today: Book dentist." in text
    assert "Next up is Send report, tomorrow." in text
    assert "70 of 100 points, 30 to go" in text
    assert "Finishing Renew passport is worth 30 points." in text
    assert "Your streak is 2 days." in text
    assert (result["overdue"], result["due_today"], result["upcoming"]) == (1, 1, 2)


def test_nothing_due_and_goal_met():
    result = build_briefing([_task("Later", 5)], {**SUMMARY, "points_today": 120, "goal_met": True, "streak": 1}, TODAY, 20)
    assert "Nothing is due today." in result["text"]
    assert "Next up is Later, in 5 days." in result["text"]
    assert "already hit your 100 point goal today with 120" in result["text"]
    assert "Your streak is 1 day." in result["text"]


def test_long_lists_are_trimmed_and_empty_is_graceful():
    many = [_task(f"Task number {i}", 0) for i in range(6)]
    text = build_briefing(many, SUMMARY, TODAY, 9)["text"]
    assert "6 tasks due today: Task number 0, Task number 1, Task number 2, and 3 more." in text
    empty = build_briefing([], {**SUMMARY, "streak": 0}, TODAY, 9)["text"]
    assert empty.startswith("Good morning. Nothing is due today.") and "streak" not in empty


def test_long_task_names_are_shortened():
    text = build_briefing([_task("x" * 200, 0)], SUMMARY, TODAY, 9)["text"]
    assert "x" * 200 not in text and "…" in text
