"""Turn a spoken or typed sentence into task fields (text, priority, date)."""

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.attention.dates import parse_timing_phrase

REMINDER_MINUTES = 15  # how long a quick reminder's slot lasts

_PRIORITY_PATTERNS = [
    ("High", re.compile(r"\b(?:(?:high|top)[\s-]+priority|priority\s+high|urgent(?:ly)?|asap|important)\b", re.I)),
    ("Low", re.compile(r"\b(?:low[\s-]+priority|priority\s+low|whenever|no\s+rush|not\s+urgent)\b", re.I)),
    ("Medium", re.compile(r"\b(?:(?:medium|normal)[\s-]+priority|priority\s+medium)\b", re.I)),
]

_WEEKDAYS = r"(?:mon|tues?|wed(?:nes)?|thu(?:rs?)?|fri|sat(?:ur)?|sun)(?:day)?"
_DATE_PATTERN = re.compile(
    r"\b(?:(?:by|on|before|until|due)\s+)?("
    r"today|tonight|tomorrow|this\s+weekend|"
    r"(?:next\s+)?" + _WEEKDAYS + r"|"
    r"in\s+\d+\s+days?|"
    r"\d{4}-\d{2}-\d{2}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:,?\s+\d{4})?"
    r")\b",
    re.I,
)
_LEAD_IN = re.compile(r"^\s*(?:please\s+)?(?:remind me to|i need to|i have to|i should|add a task to|add task|task:)\s+", re.I)


# "in 20 min", "in 2 hours", "in an hour", "in half an hour"
_RELATIVE = re.compile(
    r"\b(?:in|after)\s+(?:(\d+(?:\.\d+)?)|(an?|half\s+an?))\s*(minutes?|mins?|m|hours?|hrs?|h)\b",
    re.I,
)
# "at 5pm", "at 17:30", "at 9", "@ 6:15 am"
_CLOCK = re.compile(r"\b(?:at|@)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?(?![\w:])", re.I)


def _relative_minutes(match: "re.Match") -> int:
    number, word, unit = match.group(1), (match.group(2) or "").lower(), match.group(3).lower()
    amount = float(number) if number else (0.5 if word.startswith("half") else 1.0)
    return max(1, round(amount * (60 if unit.startswith("h") else 1)))


def _clock_time(match: "re.Match", on_day: date, tz: ZoneInfo, now: datetime, day_given: bool) -> Optional[datetime]:
    hour, minute, meridiem = int(match.group(1)), int(match.group(2) or 0), (match.group(3) or "").lower().replace(".", "")
    if minute > 59 or hour > 24 or (meridiem and not 1 <= hour <= 12):
        return None
    if meridiem == "pm" and hour != 12:
        hour += 12
    elif meridiem == "am" and hour == 12:
        hour = 0
    candidates = [hour] if (meridiem or hour > 12 or hour == 0) else [hour, hour + 12 if hour < 12 else hour]
    moments = [datetime.combine(on_day, time(h % 24, minute), tzinfo=tz) for h in candidates]
    future = [m for m in moments if m > now.astimezone(tz)]
    if future:
        return min(future)
    # every candidate today has passed: with no day named, mean tomorrow
    return None if day_given else moments[0] + timedelta(days=1)


def _find_reminder_time(text: str, now: datetime, tz: ZoneInfo, day: Optional[date]):
    """The reminder moment and the span of text that named it.

    "remind me in 5 mins" wins over any other time in the sentence."""
    options = []
    for match in _RELATIVE.finditer(text):
        options.append((match, now.astimezone(timezone.utc) + timedelta(minutes=_relative_minutes(match))))
    local_today = now.astimezone(tz).date()
    for match in _CLOCK.finditer(text):
        moment = _clock_time(match, day or local_today, tz, now, day is not None)
        if moment is not None:
            options.append((match, moment))
    if not options:
        return None
    def asked_for(option):
        start = option[0].start()
        return "remind" in text[max(0, start - 18):start].lower()
    chosen = next((o for o in options if asked_for(o)), min(options, key=lambda o: o[0].start()))
    match, moment = chosen
    start = match.start()
    lead = re.search(r"remind(?:\s+me)?\s*$", text[:start], re.I)
    if lead:
        start = lead.start()
    return moment, (start, match.end())


def parse_spoken_task(
    sentence: str,
    today: Optional[date] = None,
    now: Optional[datetime] = None,
    tz: Optional[ZoneInfo] = None,
) -> dict:
    text = " ".join((sentence or "").split())
    priority = None
    for name, pattern in _PRIORITY_PATTERNS:
        if pattern.search(text):
            priority = name
            text = pattern.sub(" ", text)
            break

    due_on = None
    confidence = None
    match = _DATE_PATTERN.search(text)
    if match:
        phrase = match.group(1).replace("tonight", "today")
        parsed = parse_timing_phrase(phrase, reference=today)
        if parsed.normalized_iso:
            due_on = parsed.normalized_iso
            confidence = parsed.confidence
            text = text[: match.start()] + " " + text[match.end():]

    remind_at = None
    if now is not None and tz is not None:
        day = date.fromisoformat(due_on) if due_on else None
        found = _find_reminder_time(text, now, tz, day)
        if found:
            remind_at, (start, end) = found
            text = text[:start] + " " + text[end:]
            if due_on is None:
                due_on = remind_at.astimezone(tz).date().isoformat()
                confidence = "high"

    text = _LEAD_IN.sub("", text)
    text = re.sub(r"\s+([,.;])", r"\1", " ".join(text.split())).strip(" ,.;-")
    text = re.sub(r"^(?:and|then)\s+", "", text, flags=re.I)
    if text:
        text = text[0].upper() + text[1:]
    return {
        "text": text,
        "priority": priority or "Medium",
        "priority_spoken": priority is not None,
        "due_on": due_on,
        "due_confidence": confidence,
        "remind_at": remind_at,
    }
