"""Recurring to-do tasks.

A recurring task behaves like a normal task until it is completed. At that
moment the backend spawns the next occurrence: a fresh open copy of the task
(same title, description, assignees, and recurrence rule) with the due date
advanced by the recurrence interval. The completed row stays in the Complete
section as a historical record.

Each row can spawn at most one successor (guarded by recurrence_spawned), so
toggling a task done/undone repeatedly never creates duplicates.
"""
from __future__ import annotations

import calendar
import logging
from datetime import date, timedelta

from supabase import Client

from app.repositories import todo_repo

logger = logging.getLogger(__name__)


def _add_months(d: date, months: int) -> date:
    """Calendar-aware month addition, clamping the day (Jan 31 + 1mo = Feb 28)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _advance(d: date, interval: int, unit: str) -> date:
    if unit == "day":
        return d + timedelta(days=interval)
    if unit == "week":
        return d + timedelta(weeks=interval)
    if unit == "month":
        return _add_months(d, interval)
    raise ValueError(f"Unknown recurrence unit: {unit}")


def next_due_date(due_date: str | None, interval: int, unit: str, today: date | None = None) -> str:
    """Due date for the next occurrence, as YYYY-MM-DD.

    Advances from the previous due date (or today, for tasks without one). If
    the task was completed late, keeps advancing so the next occurrence never
    starts out already overdue.
    """
    today = today or date.today()
    base = date.fromisoformat(due_date) if due_date else today
    nxt = _advance(base, interval, unit)
    while nxt < today:
        nxt = _advance(nxt, interval, unit)
    return nxt.isoformat()


def spawn_next_occurrence(db: Client, completed: dict) -> dict | None:
    """Create the next occurrence of a just-completed recurring task.

    Returns the new todo row, or None if the task is not recurring or this row
    already spawned its successor.
    """
    interval = completed.get("recurrence_interval")
    unit = completed.get("recurrence_unit")
    if not interval or not unit or completed.get("recurrence_spawned"):
        return None

    data = {
        "title": completed["title"],
        "description": completed.get("description"),
        "assigned_by_id": completed["assigned_by_id"],
        "assigned_by_name": completed.get("assigned_by_name"),
        "due_date": next_due_date(completed.get("due_date"), interval, unit),
        "recurrence_interval": interval,
        "recurrence_unit": unit,
    }
    assignees = [
        {"id": str(a["id"]), "first_name": a["first_name"]}
        for a in completed.get("assignees", [])
    ]
    new_todo = todo_repo.create_todo(db, data, assignees)
    todo_repo.mark_recurrence_spawned(db, completed["id"])
    return new_todo
