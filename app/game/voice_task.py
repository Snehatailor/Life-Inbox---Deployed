"""Turn a spoken or typed sentence into task fields (text, priority, date)."""

import re
from datetime import date
from typing import Optional

from app.attention.dates import parse_timing_phrase

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


def parse_spoken_task(sentence: str, today: Optional[date] = None) -> dict:
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

    text = _LEAD_IN.sub("", text)
    text = re.sub(r"\s+([,.;])", r"\1", " ".join(text.split())).strip(" ,.;-")
    if text:
        text = text[0].upper() + text[1:]
    return {
        "text": text,
        "priority": priority or "Medium",
        "priority_spoken": priority is not None,
        "due_on": due_on,
        "due_confidence": confidence,
    }
