"""SOP task delivery-time catalog.

Encodes the "Task Catalog — VA build time & delivery turnaround" sheet of
`docs/sops/AR_Team_Capacity_Workbook.xlsx` (Sheet 1, the *Delivery time*
column — the client-facing turnaround per task, not the labor/build time).

Used by the SerMastr conversational ``add_asana_task`` action to default a
new task's Asana due date to its SOP delivery turnaround when the teammate
doesn't give an explicit deadline. Tasks whose SOP delivery time is a
recurring cadence or is genuinely undefined (``weekly`` / ``monthly`` /
``varies`` / ``—``) yield no concrete turnaround, so the caller falls back to
asking the teammate to confirm a date (per the owner's rule: "if the task is
not in the SOP, ask to confirm the due date").

Pure module — no I/O. The catalog is a code constant (mirroring how
``recipe_engine`` encodes SOP values); re-sync it if the workbook changes.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

# (task label, SOP "Delivery time" cell) — verbatim from the workbook.
_CATALOG_RAW: list[tuple[str, str]] = [
    ("Guest post", "2 weeks"),
    ("Niche edit", "2 weeks"),
    ("Press release (order)", "2 weeks"),
    ("Citations (per 40-batch)", "10 days"),
    ("Google stack", "3 days"),
    ("G Sites / OffPage Agent", "5 days"),
    ("GSA blast", "3 weeks"),
    ("Money Robot", "3 weeks"),
    ("Xrumer", "3 weeks"),
    ("IFTTT ring", "10 days"),
    ("DAS v2", "3 weeks"),
    ("Respect Mah Authoritay v2", "3 weeks"),
    ("Cloud Stack (Elias)", "5 days"),
    ("Contextual To Text", "3 weeks"),
    ("Contextual To Text Advanced", "3 weeks"),
    ("RD100", "3 weeks"),
    ("Hydra", "45 days"),
    ("DAS v2 w/ RD100", "45 days"),
    ("GBP Blast", "7 days"),
    ("Hyper Local GBP Blast", "7 days"),
    ("GBP Sniper", "7 days"),
    ("Map Embeds", "4 weeks"),
    ("Content page (blog/service/any)", "5 days"),
    ("GBP post (each)", "—"),
    ("Initial GBP optimization", "2 weeks"),
    ("Ongoing GBP posting (weekly batch)", "7 days"),
    ("Agency Assassin setup/tuning (weekly)", "weekly"),
    ("Schema implementation (per page)", "5 days"),
    ("Site build", "varies"),
    ("Client meeting (monthly)", "monthly"),
    ("Asana board management (monthly)", "monthly"),
    ("Monthly reporting (per client)", "monthly"),
]

_UNIT_DAYS = {"day": 1, "week": 7, "month": 30}


def parse_turnaround(text: str) -> Optional[int]:
    """Parse an SOP "Delivery time" cell into a concrete number of days.

    ``"10 days"`` → 10, ``"2 weeks"`` → 14, ``"45 days"`` → 45. Returns
    ``None`` for cadences/undefined turnarounds (``weekly`` / ``monthly`` /
    ``varies`` / ``—`` / blank) — the caller treats those as "no concrete SOP
    delivery time" and asks the teammate for a date.
    """
    if not text:
        return None
    t = text.strip().lower()
    m = re.fullmatch(r"(\d+)\s*(day|week|month)s?", t)
    if m:
        return int(m.group(1)) * _UNIT_DAYS[m.group(2)]
    return None


# label → {"label", "delivery", "days"} (days is None when not concrete).
CATALOG: dict[str, dict] = {
    label: {"label": label, "delivery": delivery, "days": parse_turnaround(delivery)}
    for label, delivery in _CATALOG_RAW
}


def catalog_labels() -> list[str]:
    """Task labels, for the action-param enum the LLM matches against."""
    return [label for label, _ in _CATALOG_RAW]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def lookup(task: str) -> Optional[dict]:
    """Resolve a catalog label (case-insensitive exact match) to its entry."""
    if not task:
        return None
    key = _normalize(task)
    for label, entry in CATALOG.items():
        if _normalize(label) == key:
            return entry
    return None


def due_date_for(task: str, today: date) -> Optional[tuple[date, str, str]]:
    """SOP-default due date for a catalog task.

    Returns ``(due_date, delivery_text, label)`` when the task is in the
    catalog with a *concrete* turnaround, else ``None`` (unknown task, or a
    recurring/undefined turnaround → the caller should ask for a date).
    """
    entry = lookup(task)
    if not entry or entry["days"] is None:
        return None
    return today + timedelta(days=entry["days"]), entry["delivery"], entry["label"]
