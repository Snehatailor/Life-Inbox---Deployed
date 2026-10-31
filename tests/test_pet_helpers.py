"""The pet's pure logic (alerts, quips) run under Node, and the /pet page."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_api import client  # noqa: F401  (fixture)

PET_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "pet.js"


def run_node(script: str):
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    result = subprocess.run(
        [node, "-e", f"const h = require({json.dumps(str(PET_JS))}); {script}"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


REMINDER = {"task_id": 7, "text": "Call the bank", "slot_start": "2026-11-02T10:00:00+00:00",
            "phase": "soon", "label": "in 8 min"}


def test_alert_text_per_phase():
    out = run_node(f"""
      const r = {json.dumps(REMINDER)};
      console.log(JSON.stringify([
        h.alertText(r, 'Mochi'),
        h.alertText({{...r, phase: 'now'}}, 'Mochi'),
        h.alertText({{...r, phase: 'missed', label: '25 min ago'}}, 'Mochi'),
        h.alertText({{...r, phase: 'later'}}, 'Mochi'),
        h.alertText({{...r, text: 'x'.repeat(100)}}, 'Mochi').length,
      ]));""")
    assert out[0] == "Mochi: “Call the bank” starts in 8 min."
    assert out[1] == "Mochi: time for “Call the bank” — now!"
    assert out[2] == "Mochi: you missed “Call the bank” (25 min ago). Reschedule it?"
    assert out[3] == ""
    assert out[4] < 100  # long task names are shortened


def test_each_phase_is_announced_once_and_later_is_silent():
    out = run_node(f"""
      const soon = {json.dumps(REMINDER)};
      const now = {{...soon, phase: 'now'}};
      const later = {{...soon, task_id: 8, phase: 'later'}};
      const seen = {{}};
      const first = h.newAlerts([soon, later], seen).map(r => r.task_id);
      seen[h.alertKey(soon)] = 1;
      const second = h.newAlerts([soon, later], seen).map(r => r.task_id);
      const third = h.newAlerts([now, later], seen).map(r => r.phase);   // the next phase is new
      console.log(JSON.stringify({{first, second, third}}));""")
    assert out == {"first": [7], "second": [], "third": ["now"]}


def test_quips_reflect_the_situation_and_sleepy_hours():
    out = run_node("""
      const base = {overdue_count: 0, due_today: [], goal_met: false, goal: 100, points_today: 70, streak: 0};
      const pick = (s, hour, r) => h.pickQuip(s, hour, () => r);
      console.log(JSON.stringify({
        goal: pick(base, 12, 0),
        overdue: pick({...base, overdue_count: 2}, 12, 0),
        done: pick({...base, goal_met: true}, 12, 0),
        streak: pick({...base, streak: 3}, 12, 0.99),
        sleepy: [h.isSleepyHour(23), h.isSleepyHour(3), h.isSleepyHour(6), h.isSleepyHour(14)],
      }));""")
    assert out["goal"] == "30 coins to today's goal."
    assert "2 overdue" in out["overdue"]
    assert "daily goal" in out["done"]
    assert "3-day streak" in out["streak"]
    assert out["sleepy"] == [True, True, False, False]


def test_pet_page_and_assets_are_served(client):
    page = client.get("/pet")
    assert page.status_code == 200 and "/static/pet.js" in page.text and "petRoot" in page.text
    for path in ("/static/pet.js", "/static/pet.css"):
        assert client.get(path).status_code == 200
    home = client.get("/")
    assert "/static/pet.js" in home.text and "/static/pet.css" in home.text and "petLayer" in home.text
