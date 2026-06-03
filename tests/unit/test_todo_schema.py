"""Tests for the To-Do schemas.

Only the task title is required to create a task; everything else (description,
assignee, due date) is optional. TodoUpdate distinguishes an explicit "unassign"
from leaving the assignee unchanged.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.todo import TodoCreate, TodoUpdate, TodoOut


class TestTodoCreate:
    def test_title_only(self):
        todo = TodoCreate(title="Follow up with lead")
        assert todo.title == "Follow up with lead"
        assert todo.description is None
        assert todo.assigned_to_id is None
        assert todo.assigned_to_name is None
        assert todo.assignees is None
        assert todo.due_date is None

    def test_all_fields(self):
        todo = TodoCreate(
            title="Prep deck",
            description="Detail",
            assigned_to_id="u-1",
            assigned_to_name="Ishaan",
            due_date="2026-03-01",
        )
        assert todo.description == "Detail"
        assert todo.assigned_to_name == "Ishaan"

    def test_multiple_assignees(self):
        todo = TodoCreate(
            title="Shared task",
            assignees=[
                {"id": "u-1", "first_name": "Ishaan"},
                {"id": "u-2", "first_name": "Srijan"},
            ],
        )
        assert [a.first_name for a in todo.assignees] == ["Ishaan", "Srijan"]

    def test_title_required(self):
        with pytest.raises(ValidationError):
            TodoCreate()


class TestTodoUpdate:
    def test_all_optional(self):
        update = TodoUpdate()
        assert update.model_dump(exclude_unset=True) == {}

    def test_unassign_flag_defaults_false(self):
        assert TodoUpdate().unassign is False

    def test_partial_update_tracks_provided_fields(self):
        update = TodoUpdate(is_done=True)
        provided = update.model_dump(exclude_unset=True)
        assert provided == {"is_done": True}


class TestTodoOut:
    def test_minimal_row(self):
        out = TodoOut(id="t-1", title="Task", assigned_by_id="u-1")
        assert out.is_done is False
        assert out.assigned_to_name is None
        assert out.assignees == []
