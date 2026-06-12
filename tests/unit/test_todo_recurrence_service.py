"""Tests for recurring to-do logic.

Completing a recurring task spawns exactly one successor with the due date
advanced by the recurrence rule. Late completions never produce an
already-overdue next occurrence, and month math clamps to real calendar days.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from app.services.todo_recurrence_service import next_due_date, spawn_next_occurrence


class TestNextDueDate:
    def test_daily(self):
        assert next_due_date("2026-06-10", 1, "day", today=date(2026, 6, 10)) == "2026-06-11"

    def test_every_n_days(self):
        assert next_due_date("2026-06-10", 3, "day", today=date(2026, 6, 10)) == "2026-06-13"

    def test_weekly(self):
        assert next_due_date("2026-06-12", 1, "week", today=date(2026, 6, 12)) == "2026-06-19"

    def test_biweekly(self):
        assert next_due_date("2026-06-12", 2, "week", today=date(2026, 6, 12)) == "2026-06-26"

    def test_monthly(self):
        assert next_due_date("2026-06-15", 1, "month", today=date(2026, 6, 15)) == "2026-07-15"

    def test_monthly_clamps_to_shorter_month(self):
        # Jan 31 + 1 month lands on Feb 28 (2026 is not a leap year).
        assert next_due_date("2026-01-31", 1, "month", today=date(2026, 1, 31)) == "2026-02-28"

    def test_monthly_clamps_to_leap_day(self):
        assert next_due_date("2028-01-31", 1, "month", today=date(2028, 1, 31)) == "2028-02-29"

    def test_year_rollover(self):
        assert next_due_date("2026-12-20", 1, "month", today=date(2026, 12, 20)) == "2027-01-20"

    def test_late_completion_skips_past_occurrences(self):
        # Weekly task due June 1, completed June 12: next is June 15, not June 8.
        assert next_due_date("2026-06-01", 1, "week", today=date(2026, 6, 12)) == "2026-06-15"

    def test_no_due_date_bases_off_today(self):
        assert next_due_date(None, 1, "week", today=date(2026, 6, 12)) == "2026-06-19"

    def test_unknown_unit_rejected(self):
        with pytest.raises(ValueError):
            next_due_date("2026-06-12", 1, "year", today=date(2026, 6, 12))


def _recurring_todo(**overrides) -> dict:
    return {
        "id": "todo-1",
        "title": "Weekly sync prep",
        "description": "Collect updates",
        "assigned_by_id": "u-boss",
        "assigned_by_name": "Boss",
        "due_date": "2026-06-12",
        "is_done": True,
        "recurrence_interval": 1,
        "recurrence_unit": "week",
        "recurrence_spawned": False,
        "assignees": [{"id": "u-1", "first_name": "Ishaan"}],
        **overrides,
    }


@patch("app.services.todo_recurrence_service.todo_repo")
class TestSpawnNextOccurrence:
    def test_spawns_copy_with_advanced_due_date(self, mock_repo):
        db = MagicMock()
        mock_repo.create_todo.return_value = {"id": "todo-2"}

        result = spawn_next_occurrence(db, _recurring_todo())

        assert result == {"id": "todo-2"}
        data, assignees = mock_repo.create_todo.call_args[0][1:]
        assert data["title"] == "Weekly sync prep"
        assert data["description"] == "Collect updates"
        assert data["recurrence_interval"] == 1
        assert data["recurrence_unit"] == "week"
        assert date.fromisoformat(data["due_date"]) > date(2026, 6, 12)
        assert assignees == [{"id": "u-1", "first_name": "Ishaan"}]
        mock_repo.mark_recurrence_spawned.assert_called_once_with(db, "todo-1")

    def test_non_recurring_task_spawns_nothing(self, mock_repo):
        todo = _recurring_todo(recurrence_interval=None, recurrence_unit=None)
        assert spawn_next_occurrence(MagicMock(), todo) is None
        mock_repo.create_todo.assert_not_called()

    def test_already_spawned_row_never_spawns_again(self, mock_repo):
        todo = _recurring_todo(recurrence_spawned=True)
        assert spawn_next_occurrence(MagicMock(), todo) is None
        mock_repo.create_todo.assert_not_called()

    def test_carries_finished_estimate_without_reestimating(self, mock_repo):
        mock_repo.create_todo.return_value = {"id": "todo-2"}
        todo = _recurring_todo(
            estimate_status="done", estimated_hours_min=1.0, estimated_hours_max=2.5
        )

        spawn_next_occurrence(MagicMock(), todo)

        data = mock_repo.create_todo.call_args[0][1]
        assert data["estimate_status"] == "done"
        assert data["estimated_hours_min"] == 1.0
        assert data["estimated_hours_max"] == 2.5

    def test_pending_or_failed_estimate_not_carried(self, mock_repo):
        mock_repo.create_todo.return_value = {"id": "todo-2"}
        todo = _recurring_todo(estimate_status="failed", estimated_hours_min=1.0)

        spawn_next_occurrence(MagicMock(), todo)

        data = mock_repo.create_todo.call_args[0][1]
        assert data["estimate_status"] is None
        assert data["estimated_hours_min"] is None

    def test_actual_hours_not_copied(self, mock_repo):
        mock_repo.create_todo.return_value = {"id": "todo-2"}

        spawn_next_occurrence(MagicMock(), _recurring_todo(actual_hours=3.0))

        data = mock_repo.create_todo.call_args[0][1]
        assert "actual_hours" not in data
