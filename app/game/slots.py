"""Busy-time import (.ics) and free-slot suggestions. Pure functions."""

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

WORK_START = 9
WORK_END = 18
STEP_MINUTES = 15
DEFAULT_EVENT_MINUTES = 60


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_when(name_and_params: str, value: str, default_tz: ZoneInfo) -> Optional[datetime]:
    """Aware datetime for a DATE-TIME value; None for all-day or unparseable."""
    params = name_and_params.upper().split(";")[1:]
    if "VALUE=DATE" in params or re.fullmatch(r"\d{8}", value.strip()):
        return None
    match = re.fullmatch(r"(\d{8})T(\d{6})(Z?)", value.strip())
    if not match:
        return None
    naive = datetime.strptime(match.group(1) + match.group(2), "%Y%m%d%H%M%S")
    if match.group(3):
        return naive.replace(tzinfo=timezone.utc)
    tz = default_tz
    for param in name_and_params.split(";")[1:]:
        if param.upper().startswith("TZID="):
            try:
                tz = ZoneInfo(param.split("=", 1)[1])
            except Exception:
                tz = default_tz
    return naive.replace(tzinfo=tz)


def _parse_duration(value: str) -> Optional[timedelta]:
    match = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?", value.strip().upper())
    if not match or not any(match.groups()):
        return None
    days, hours, minutes = (int(g or 0) for g in match.groups())
    return timedelta(days=days, hours=hours, minutes=minutes)


def parse_ics_busy(text: str, default_tz: ZoneInfo) -> list[dict]:
    """Timed, opaque events as {starts_at, ends_at, summary} in UTC.

    All-day and transparent events do not block time. Recurrence rules are
    not expanded: only the first occurrence of a repeating event is read.
    """
    blocks: list[dict] = []
    current: Optional[dict] = None
    for line in _unfold(text):
        upper = line.upper()
        if upper == "BEGIN:VEVENT":
            current = {}
            continue
        if upper == "END:VEVENT":
            if current and current.get("start") and not current.get("free"):
                start = current["start"]
                end = current.get("end")
                if end is None:
                    end = start + (current.get("duration") or timedelta(minutes=DEFAULT_EVENT_MINUTES))
                if end > start:
                    blocks.append(
                        {
                            "starts_at": start.astimezone(timezone.utc).isoformat(),
                            "ends_at": end.astimezone(timezone.utc).isoformat(),
                            "summary": (current.get("summary") or "")[:200] or None,
                        }
                    )
            current = None
            continue
        if current is None or ":" not in line:
            continue
        head, value = line.split(":", 1)
        key = head.split(";", 1)[0].upper()
        if key == "DTSTART":
            current["start"] = _parse_when(head, value, default_tz)
        elif key == "DTEND":
            current["end"] = _parse_when(head, value, default_tz)
        elif key == "DURATION":
            current["duration"] = _parse_duration(value)
        elif key == "SUMMARY":
            current["summary"] = value
        elif key == "TRANSP" and value.strip().upper() == "TRANSPARENT":
            current["free"] = True
    return blocks


def _round_up(moment: datetime, step: int = STEP_MINUTES) -> datetime:
    moment = moment.replace(second=0, microsecond=0)
    extra = (-moment.minute) % step
    return moment + timedelta(minutes=extra)


def suggest_slots(
    busy: list[tuple[datetime, datetime]],
    minutes: int,
    deadline: Optional[date],
    now: datetime,
    tz: ZoneInfo,
    limit: int = 3,
    horizon_days: int = 14,
) -> list[dict]:
    """Up to `limit` slots, at most one per weekday, earliest first.

    Slots end by the deadline day's working hours. A day with no gap long
    enough for the task is skipped.
    """
    now_local = now.astimezone(tz)
    today = now_local.date()
    last_day = today + timedelta(days=horizon_days - 1)
    if deadline is not None:
        last_day = min(last_day, deadline)
    busy_local = sorted(
        ((s.astimezone(tz), e.astimezone(tz)) for s, e in busy), key=lambda pair: pair[0]
    )
    need = timedelta(minutes=minutes)
    slots: list[dict] = []
    day = today
    while day <= last_day and len(slots) < limit:
        if day.weekday() < 5:
            window_start = datetime.combine(day, time(WORK_START), tzinfo=tz)
            window_end = datetime.combine(day, time(WORK_END), tzinfo=tz)
            if day == today:
                window_start = max(window_start, _round_up(now_local))
            cursor = window_start
            for b_start, b_end in busy_local:
                if b_end <= cursor or b_start >= window_end:
                    continue
                if b_start - cursor >= need:
                    break
                cursor = max(cursor, _round_up(b_end))
            if cursor + need <= window_end:
                slots.append(
                    {
                        "start": cursor.isoformat(),
                        "end": (cursor + need).isoformat(),
                        "day": day.isoformat(),
                        "label": f"{cursor.strftime('%a %b')} {cursor.day} · "
                        f"{cursor.strftime('%H:%M')}–{(cursor + need).strftime('%H:%M')}",
                    }
                )
        day += timedelta(days=1)
    return slots
