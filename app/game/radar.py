"""Procrastination Radar: how likely an open task is to slip. Pure rules, no database.

Every point in a score comes with a plain-language reason, so the badge can
always say why it is that colour. Nothing here calls a model.
"""

from datetime import date, datetime, timezone
from typing import Iterable, Optional

from app.game.reminders import parse_utc
from app.game.scoring import days_left

WATCH_AT = 40
AT_RISK_AT = 70
SNOOZE_POINTS = 10
SNOOZE_CAP = 30
HISTORY_DAYS = 30
HISTORY_MIN_SAMPLES = 3
CROWD_WINDOW_DAYS = 3
NO_SLOT_DAYS = 3
NO_SLOT_POINTS = 10
SCHEDULED_POINTS = -15
RESCUE_BONUS = 10


def deadline_points(left: Optional[int]) -> int:
    if left is None:
        return 0
    if left < 0:
        return 40
    if left == 0:
        return 35
    if left == 1:
        return 30
    if left == 2:
        return 25
    if left <= 4:
        return 20
    if left <= 7:
        return 10
    return 0


def _deadline_reason(left: int) -> str:
    if left < 0:
        n = -left
        return f"{n} day{'s' if n != 1 else ''} overdue"
    if left == 0:
        return "Due today"
    return f"Due in {left} day{'s' if left != 1 else ''}"


def history_points(average_days_late: Optional[float]) -> int:
    if average_days_late is None or average_days_late <= 0:
        return 0
    if average_days_late >= 2:
        return 20
    if average_days_late >= 1:
        return 12
    return 5


def crowd_points(others: int) -> int:
    if others >= 4:
        return 15
    if others == 3:
        return 10
    if others == 2:
        return 5
    return 0


def level_for(score: int) -> str:
    if score >= AT_RISK_AT:
        return "at_risk"
    if score >= WATCH_AT:
        return "watch"
    return "on_track"


def lateness_by_domain(
    finished: Iterable[tuple[str, Optional[str], Optional[date]]], today: date
) -> dict[str, float]:
    """Average days late per domain, from tasks finished in the last 30 days.

    `finished` holds (domain, due_on, completed_on). Early finishes count as
    negative lateness. A domain needs 3 finished tasks with a deadline before
    it counts, so one bad day does not label a person.
    """
    samples: dict[str, list[int]] = {}
    for domain, due_on, completed_on in finished:
        if completed_on is None or (today - completed_on).days > HISTORY_DAYS:
            continue
        left = days_left(due_on, completed_on)
        if left is None:
            continue
        samples.setdefault(domain, []).append(-left)
    return {
        domain: sum(values) / len(values)
        for domain, values in samples.items()
        if len(values) >= HISTORY_MIN_SAMPLES
    }


def _has_upcoming_slot(task: dict, now: datetime) -> bool:
    end = parse_utc(task.get("slot_end")) or parse_utc(task.get("slot_start"))
    return end is not None and end >= now


def _crowding(task: dict, open_tasks: Iterable[dict]) -> int:
    due = task.get("due_on")
    if not due:
        return 0
    count = 0
    for other in open_tasks:
        if other.get("id") == task.get("id") or other.get("priority") != "High":
            continue
        gap = days_left(other.get("due_on"), date.fromisoformat(due[:10]))
        if gap is not None and abs(gap) <= CROWD_WINDOW_DAYS:
            count += 1
    return count


def assess(
    task: dict,
    *,
    snoozes: int,
    domain_lateness: dict[str, float],
    open_tasks: list[dict],
    today: date,
    now: Optional[datetime] = None,
) -> dict:
    """Score one open task. Returns score, level, reasons and the rescue score.

    The rescue score leaves out snoozes, so snoozing a task on purpose to
    turn it red never earns the rescue bonus.
    """
    now = now or datetime.now(timezone.utc)
    reasons: list[dict] = []

    def add(points: int, text: str) -> None:
        if points:
            reasons.append({"points": points, "text": text})

    left = days_left(task.get("due_on"), today)
    if left is not None:
        add(deadline_points(left), _deadline_reason(left))

    snooze_points = min(snoozes * SNOOZE_POINTS, SNOOZE_CAP)
    if snoozes:
        add(snooze_points, f"Snoozed {snoozes} time{'s' if snoozes != 1 else ''}")

    domain = task.get("domain") or "Unsorted"
    late = domain_lateness.get(domain)
    if history_points(late):
        add(
            history_points(late),
            f"Your {domain} tasks finish {late:.1f} days late on average",
        )

    others = _crowding(task, open_tasks)
    add(crowd_points(others), f"{others} other High tasks due around then")

    scheduled = _has_upcoming_slot(task, now)
    needs_time = (
        task.get("priority") == "High" and left is not None and 0 <= left <= NO_SLOT_DAYS
    )
    if needs_time and not scheduled:
        add(NO_SLOT_POINTS, "High priority with no time booked")
    if scheduled:
        add(SCHEDULED_POINTS, "Time slot booked")

    score = max(0, min(100, sum(r["points"] for r in reasons)))
    # The rescue score is the risk as if nothing had been snoozed or booked:
    # snoozing on purpose cannot earn the bonus, and "Start 10 min" cannot lose it.
    rescue_score = min(
        100,
        deadline_points(left)
        + history_points(late)
        + crowd_points(others)
        + (NO_SLOT_POINTS if needs_time else 0),
    )
    return {
        "score": score,
        "level": level_for(score),
        "reasons": reasons,
        "rescue_score": rescue_score,
    }


def rescue_bonus(rescue_score: int) -> int:
    """Extra coins for finishing a task the radar had marked at risk."""
    return RESCUE_BONUS if rescue_score >= AT_RISK_AT else 0
