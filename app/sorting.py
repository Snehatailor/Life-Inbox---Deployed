"""Sort inbox items by data format and by life domain.

Both are derived from what is already stored, so they improve as extraction
fills in text. Only a person's own domain correction is persisted.
"""

import re
from pathlib import PurePosixPath
from typing import Optional

DOMAINS = [
    "Work", "Finance", "Health", "Study", "Home", "Travel", "Shopping", "Social",
]
UNSORTED = "Unsorted"

FORMAT_LABELS = {
    "pdf": "PDF",
    "image": "Image",
    "audio": "Audio",
    "link": "Link",
    "note": "Note",
    "spreadsheet": "Spreadsheet",
    "data": "Data",
    "textfile": "Text file",
    "other": "Other",
}

_SPREADSHEET_EXT = {".csv", ".tsv", ".xls", ".xlsx", ".ods"}
_DATA_EXT = {".json", ".xml", ".yaml", ".yml"}
TEXT_FILE_EXT = {".txt", ".md", ".log", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml"}

_KEYWORDS = {
    "Work": ["meeting", "client", "project", "deadline", "report", "team", "manager", "invoice",
             "recruiter", "interview", "roadmap", "sprint", "presentation", "proposal", "office", "colleague"],
    "Finance": ["bill", "tax", "insurance", "bank", "loan", "salary", "budget", "payment", "refund",
                "reimbursement", "invoice", "statement", "mortgage", "invest", "credit", "rent", "expense"],
    "Health": ["doctor", "dentist", "medicine", "prescription", "gym", "workout", "diet", "therapy",
               "appointment", "hospital", "vaccine", "checkup", "sleep", "symptom", "health"],
    "Study": ["lecture", "course", "exam", "homework", "assignment", "thesis", "research", "paper",
              "study", "tutorial", "learn", "textbook", "lesson", "university", "article", "read"],
    "Home": ["repair", "plumber", "furniture", "cleaning", "garden", "landlord", "lease",
             "apartment", "kitchen", "laundry", "groceries", "household", "electricity"],
    "Travel": ["flight", "hotel", "passport", "visa", "itinerary", "booking", "trip", "airport",
               "luggage", "vacation", "train", "travel", "holiday"],
    "Shopping": ["buy", "order", "amazon", "cart", "discount", "delivery", "purchase", "gift",
                 "pick up", "sale", "wishlist"],
    "Social": ["birthday", "party", "dinner", "friend", "wedding", "family", "call mom", "reunion",
               "invite", "catch up", "weekend plans"],
}


def detect_format(
    item_type: str,
    original_filename: Optional[str] = None,
    mime_type: Optional[str] = None,
) -> str:
    if item_type == "pdf":
        return "pdf"
    if item_type == "image":
        return "image"
    if item_type == "voice":
        return "audio"
    if item_type == "url":
        return "link"
    ext = PurePosixPath((original_filename or "").lower()).suffix
    mime = (mime_type or "").lower()
    if ext in _SPREADSHEET_EXT or mime in {"text/csv", "text/tab-separated-values"}:
        return "spreadsheet"
    if ext in _DATA_EXT or mime in {"application/json", "application/xml"}:
        return "data"
    if original_filename:
        return "textfile"
    return "note" if item_type == "text" else "other"


def detect_domain(*texts: Optional[str]) -> tuple[str, str]:
    """Return (domain, confidence). Weak evidence stays Unsorted."""
    haystack = " ".join(t for t in texts if t)[:6000].lower()
    if not haystack.strip():
        return UNSORTED, "none"
    scores = {}
    for domain, words in _KEYWORDS.items():
        hits = sum(
            1 for word in words
            if re.search(r"\b" + re.escape(word), haystack)
        )
        if hits:
            scores[domain] = hits
    if not scores:
        return UNSORTED, "none"
    best = max(scores.values())
    # A tie is a guess, so a person should look at it.
    winners = [d for d, n in scores.items() if n == best]
    if len(winners) > 1 and best < 3:
        return UNSORTED, "low"
    domain = winners[0] if len(winners) == 1 else sorted(winners)[0]
    return domain, "high" if best >= 2 else "medium"
