"""Daily progress, streaks and levels, computed from per-day point totals."""

from datetime import date, timedelta

from app.game.scoring import DAILY_GOAL

LEVELS = [
    (0, "Apprentice"),
    (100, "Adventurer"),
    (300, "Knight"),
    (700, "Champion"),
    (1500, "Legend"),
]


def level_for(total: int) -> dict:
    index = 0
    for i, (floor, _) in enumerate(LEVELS):
        if total >= floor:
            index = i
    title = LEVELS[index][1]
    next_floor = LEVELS[index + 1][0] if index + 1 < len(LEVELS) else None
    return {
        "title": title,
        "number": index + 1,
        "next_at": next_floor,
        "points_to_next": None if next_floor is None else next_floor - total,
    }


def streak_days(by_day: dict, today: date) -> int:
    """Consecutive goal days ending today, or yesterday if today isn't done yet."""
    day = today if by_day.get(today.isoformat(), 0) >= DAILY_GOAL else today - timedelta(days=1)
    count = 0
    while by_day.get(day.isoformat(), 0) >= DAILY_GOAL:
        count += 1
        day -= timedelta(days=1)
    return count


def build_game_summary(by_day: dict, today: date, tasks_done_today: int) -> dict:
    points_today = by_day.get(today.isoformat(), 0)
    lifetime = sum(by_day.values())
    history = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        points = by_day.get(day.isoformat(), 0)
        history.append(
            {
                "day": day.isoformat(),
                "weekday": day.strftime("%a"),
                "points": points,
                "goal_met": points >= DAILY_GOAL,
            }
        )
    return {
        "today": today.isoformat(),
        "points_today": points_today,
        "goal": DAILY_GOAL,
        "percent": min(100, round(points_today * 100 / DAILY_GOAL)),
        "goal_met": points_today >= DAILY_GOAL,
        "tasks_done_today": tasks_done_today,
        "streak": streak_days(by_day, today),
        "lifetime_points": lifetime,
        "level": level_for(lifetime),
        "history": history,
    }
