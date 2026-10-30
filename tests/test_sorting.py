from app.sorting import UNSORTED, detect_domain, detect_format


def test_format_from_type_filename_and_mime():
    assert detect_format("pdf") == "pdf"
    assert detect_format("voice") == "audio"
    assert detect_format("url") == "link"
    assert detect_format("text") == "note"
    assert detect_format("text", "budget.csv", "text/csv") == "spreadsheet"
    assert detect_format("text", "clinic.json", "application/json") == "data"
    assert detect_format("text", "todo.md", "text/markdown") == "textfile"


def test_domain_keywords_and_confidence():
    assert detect_domain("Flight itinerary and hotel booking") == ("Travel", "high")
    assert detect_domain("pay the rent and the electricity bill")[0] == "Finance"
    assert detect_domain("hello") == (UNSORTED, "none")
    assert detect_domain(None, "") == (UNSORTED, "none")


def test_tie_with_weak_evidence_stays_unsorted():
    domain, confidence = detect_domain("buy a gift for the doctor")
    assert domain == UNSORTED and confidence == "low"
