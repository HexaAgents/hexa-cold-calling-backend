from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


SAMPLE_TODO = {
    "id": "todo-1",
    "title": "Call back lead",
    "description": None,
    "assigned_to_id": None,
    "assigned_to_name": None,
    "assigned_by_id": "test-user-id",
    "assigned_by_name": "Test",
    "due_date": "2026-01-10",
    "is_done": False,
    "created_at": "2026-01-01T10:00:00",
    "updated_at": None,
}


def _result(data, count=None):
    result = MagicMock()
    result.data = data
    result.count = count
    return result


def _set_get_todo(mock_supabase, row):
    mock_supabase.table.return_value \
        .select.return_value \
        .eq.return_value \
        .execute.return_value = _result([row] if row else [])


@pytest.fixture
def ishaan_client(mock_supabase):
    """Client authenticated as the super user who may tick off any task."""
    from app.main import app
    from app.dependencies import get_supabase, get_current_user

    app.dependency_overrides[get_supabase] = lambda: mock_supabase
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "ishaan-user-id",
        "email": "ishaan@hexaagents.com",
        "full_name": "Ishaan Makkar",
    }

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


class TestCreateTodo:
    def test_create_with_title_only(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .insert.return_value \
            .execute.return_value = _result([SAMPLE_TODO])

        resp = client.post("/todos", json={"title": "Just a title"})
        assert resp.status_code == 201

        inserted = mock_supabase.table.return_value.insert.call_args[0][0]
        assert inserted["title"] == "Just a title"
        assert inserted["description"] is None
        assert inserted["assigned_to_id"] is None
        assert inserted["due_date"] is None
        # Creator stamped from the authenticated user (first name only).
        assert inserted["assigned_by_id"] == "test-user-id"
        assert inserted["assigned_by_name"] == "Test"

    def test_create_with_all_fields(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .insert.return_value \
            .execute.return_value = _result([SAMPLE_TODO])

        resp = client.post(
            "/todos",
            json={
                "title": "Prepare deck",
                "description": "Internal-only detail",
                "assigned_to_id": "u-2",
                "assigned_to_name": "Srijan",
                "due_date": "2026-02-01",
            },
        )
        assert resp.status_code == 201

        inserted = mock_supabase.table.return_value.insert.call_args_list[0][0][0]
        assert inserted["description"] == "Internal-only detail"
        assert inserted["assigned_to_id"] == "u-2"
        assert inserted["assigned_to_name"] == "Srijan"
        assert inserted["due_date"] == "2026-02-01"
        assignee_rows = mock_supabase.table.return_value.insert.call_args_list[1][0][0]
        assert assignee_rows == [{"todo_id": "todo-1", "user_id": "u-2", "first_name": "Srijan"}]

    def test_create_without_description_but_with_assignee(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .insert.return_value \
            .execute.return_value = _result([SAMPLE_TODO])

        resp = client.post(
            "/todos",
            json={"title": "Quick task", "assigned_to_id": "u-3", "assigned_to_name": "Mann"},
        )
        assert resp.status_code == 201
        inserted = mock_supabase.table.return_value.insert.call_args_list[0][0][0]
        assert inserted["description"] is None
        assert inserted["assigned_to_name"] == "Mann"
        assignee_rows = mock_supabase.table.return_value.insert.call_args_list[1][0][0]
        assert assignee_rows == [{"todo_id": "todo-1", "user_id": "u-3", "first_name": "Mann"}]

    def test_create_with_multiple_assignees(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .insert.return_value \
            .execute.return_value = _result([SAMPLE_TODO])

        resp = client.post(
            "/todos",
            json={
                "title": "Shared task",
                "assignees": [
                    {"id": "u-1", "first_name": "Ishaan"},
                    {"id": "u-2", "first_name": "Srijan"},
                ],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["assignees"] == [
            {"id": "u-1", "first_name": "Ishaan"},
            {"id": "u-2", "first_name": "Srijan"},
        ]
        inserted = mock_supabase.table.return_value.insert.call_args_list[0][0][0]
        assert inserted["assigned_to_id"] == "u-1"
        assignee_rows = mock_supabase.table.return_value.insert.call_args_list[1][0][0]
        assert assignee_rows == [
            {"todo_id": "todo-1", "user_id": "u-1", "first_name": "Ishaan"},
            {"todo_id": "todo-1", "user_id": "u-2", "first_name": "Srijan"},
        ]

    def test_create_dedupes_repeated_assignees_by_id(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .insert.return_value \
            .execute.return_value = _result([SAMPLE_TODO])

        resp = client.post(
            "/todos",
            json={
                "title": "Deduped task",
                "assignees": [
                    {"id": "u-1", "first_name": "Ishaan"},
                    {"id": "u-1", "first_name": "Ishaan"},
                ],
            },
        )

        assert resp.status_code == 201
        assert resp.json()["assignees"] == [{"id": "u-1", "first_name": "Ishaan"}]
        assignee_rows = mock_supabase.table.return_value.insert.call_args_list[1][0][0]
        assert assignee_rows == [{"todo_id": "todo-1", "user_id": "u-1", "first_name": "Ishaan"}]

    @patch("app.routers.todos.email_service.send_direct_email")
    def test_create_notifies_new_assignees_by_email(self, mock_send_email, client, mock_supabase):
        mock_supabase.table.return_value \
            .insert.return_value \
            .execute.return_value = _result([{**SAMPLE_TODO, "id": "todo-1", "title": "Email Srijan"}])
        mock_supabase.rpc.return_value.execute.return_value = _result([
            {"id": "u-2", "email": "assignee@example.com", "raw_user_meta_data": {"full_name": "Assignee Person"}},
        ])
        # Shared sender resolved by Gmail address from user_gmail_tokens.
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .maybe_single.return_value \
            .execute.return_value = _result({"user_id": "sender-1", "gmail_address": "admin@hexaagents.com"})

        resp = client.post(
            "/todos",
            json={
                "title": "Email Srijan",
                "assignees": [{"id": "u-2", "first_name": "Assignee"}],
            },
        )

        assert resp.status_code == 201
        mock_send_email.assert_called_once()
        args = mock_send_email.call_args[0]
        # Sent FROM the shared notification sender, not the actor.
        assert args[1] == "sender-1"
        assert args[2] == "assignee@example.com"
        assert "Email Srijan" in args[3]
        assert "/todo-list/todo-1" in args[4]

    @patch("app.routers.todos.email_service.send_direct_email")
    def test_self_assignment_still_notifies(self, mock_send_email, client, mock_supabase):
        # The assigner (test-user-id) assigns the task to themselves.
        mock_supabase.table.return_value \
            .insert.return_value \
            .execute.return_value = _result([{**SAMPLE_TODO, "id": "todo-1", "title": "My own task"}])
        mock_supabase.rpc.return_value.execute.return_value = _result([
            {"id": "test-user-id", "email": "test@hexaagents.com", "raw_user_meta_data": {"full_name": "Test User"}},
        ])
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .maybe_single.return_value \
            .execute.return_value = _result({"user_id": "sender-1", "gmail_address": "admin@hexaagents.com"})

        resp = client.post(
            "/todos",
            json={
                "title": "My own task",
                "assignees": [{"id": "test-user-id", "first_name": "Test"}],
            },
        )

        assert resp.status_code == 201
        mock_send_email.assert_called_once()
        args = mock_send_email.call_args[0]
        assert args[1] == "sender-1"
        assert args[2] == "test@hexaagents.com"


class TestListTodos:
    def test_list_orders_open_tasks_first_then_due_date_nulls_last(self, client, mock_supabase):
        no_due = {**SAMPLE_TODO, "id": "todo-2", "due_date": None}
        mock_supabase.table.return_value \
            .select.return_value \
            .order.return_value \
            .order.return_value \
            .order.return_value \
            .execute.return_value = _result([SAMPLE_TODO, no_due])

        resp = client.get("/todos")
        assert resp.status_code == 200
        assert len(resp.json()) == 2
        # Ordering is delegated to Postgres: open tasks first, then closest due dates.
        mock_supabase.table.return_value.select.return_value.order.assert_any_call(
            "is_done", desc=False
        )
        mock_supabase.table.return_value.select.return_value.order.return_value.order.assert_any_call(
            "due_date", desc=False, nullsfirst=False
        )


class TestGetTodo:
    def test_get_returns_description(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {**SAMPLE_TODO, "description": "the detail"})
        resp = client.get("/todos/todo-1")
        assert resp.status_code == 200
        assert resp.json()["description"] == "the detail"

    def test_get_not_found(self, client, mock_supabase):
        _set_get_todo(mock_supabase, None)
        resp = client.get("/todos/missing")
        assert resp.status_code == 404


class TestPermissions:
    def test_assigner_can_update(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {**SAMPLE_TODO, "assigned_by_id": "test-user-id"})
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([{**SAMPLE_TODO, "title": "Renamed"}])

        resp = client.patch("/todos/todo-1", json={"title": "Renamed"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "Renamed"

    def test_non_assigner_cannot_update(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {**SAMPLE_TODO, "assigned_by_id": "someone-else"})
        resp = client.patch("/todos/todo-1", json={"title": "Hijack"})
        assert resp.status_code == 403

    def test_assigner_can_delete(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {**SAMPLE_TODO, "assigned_by_id": "test-user-id"})
        mock_supabase.table.return_value \
            .delete.return_value \
            .eq.return_value \
            .execute.return_value = _result([SAMPLE_TODO])

        resp = client.delete("/todos/todo-1")
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Task deleted"

    def test_non_assigner_cannot_delete(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {**SAMPLE_TODO, "assigned_by_id": "someone-else"})
        resp = client.delete("/todos/todo-1")
        assert resp.status_code == 403

    def test_update_not_found(self, client, mock_supabase):
        _set_get_todo(mock_supabase, None)
        resp = client.patch("/todos/missing", json={"title": "X"})
        assert resp.status_code == 404

    def test_reassign_sets_new_assignee(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {**SAMPLE_TODO, "assigned_by_id": "test-user-id"})
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([{**SAMPLE_TODO, "assigned_to_id": "u-9", "assigned_to_name": "Aurideep"}])

        resp = client.patch("/todos/todo-1", json={"assigned_to_id": "u-9", "assigned_to_name": "Aurideep"})
        assert resp.status_code == 200
        updated = mock_supabase.table.return_value.update.call_args[0][0]
        assert updated["assigned_to_id"] == "u-9"
        assert updated["assigned_to_name"] == "Aurideep"

    @patch("app.routers.todos.email_service.send_direct_email")
    def test_reassign_notifies_only_new_assignees(self, mock_send_email, client, mock_supabase):
        _set_get_todo(mock_supabase, {
            **SAMPLE_TODO,
            "assigned_by_id": "test-user-id",
            "assigned_to_id": "u-1",
            "assigned_to_name": "Ishaan",
        })
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([{**SAMPLE_TODO, "title": "Shared follow-up"}])
        mock_supabase.rpc.return_value.execute.return_value = _result([
            {"id": "u-1", "email": "ishaan@example.com", "raw_user_meta_data": {"full_name": "Ishaan Shah"}},
            {"id": "u-2", "email": "newbie@example.com", "raw_user_meta_data": {"full_name": "New Assignee"}},
        ])
        # Shared sender resolved by Gmail address from user_gmail_tokens.
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .maybe_single.return_value \
            .execute.return_value = _result({"user_id": "sender-1", "gmail_address": "admin@hexaagents.com"})

        resp = client.patch(
            "/todos/todo-1",
            json={
                "assignees": [
                    {"id": "u-1", "first_name": "Ishaan"},
                    {"id": "u-2", "first_name": "Newbie"},
                ],
            },
        )

        assert resp.status_code == 200
        mock_send_email.assert_called_once()
        args = mock_send_email.call_args[0]
        # Always sent FROM the shared notification sender, regardless of actor.
        assert args[1] == "sender-1"
        # TO the newly added assignee only (not the pre-existing one).
        assert args[2] == "newbie@example.com"
        assert "ishaan@example.com" not in args

    def test_unassign_clears_assignee(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {**SAMPLE_TODO, "assigned_by_id": "test-user-id", "assigned_to_id": "u-9"})
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([{**SAMPLE_TODO, "assigned_to_id": None, "assigned_to_name": None}])

        resp = client.patch("/todos/todo-1", json={"unassign": True})
        assert resp.status_code == 200
        updated = mock_supabase.table.return_value.update.call_args[0][0]
        assert updated["assigned_to_id"] is None
        assert updated["assigned_to_name"] is None
        assert "unassign" not in updated

    def test_mark_done(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {**SAMPLE_TODO, "assigned_by_id": "test-user-id"})
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([{**SAMPLE_TODO, "is_done": True}])

        resp = client.patch("/todos/todo-1", json={"is_done": True})
        assert resp.status_code == 200
        assert resp.json()["is_done"] is True
        updated = mock_supabase.table.return_value.update.call_args[0][0]
        assert updated["is_done"] is True

    def test_assignee_can_mark_done(self, client, mock_supabase):
        # Assigned by someone else; the current user is only the assignee.
        # The assignee may tick the task off, not just the creator.
        _set_get_todo(mock_supabase, {
            **SAMPLE_TODO,
            "assigned_by_id": "someone-else",
            "assigned_to_id": "test-user-id",
        })
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([{**SAMPLE_TODO, "is_done": True}])

        resp = client.patch("/todos/todo-1", json={"is_done": True})
        assert resp.status_code == 200
        assert resp.json()["is_done"] is True
        updated = mock_supabase.table.return_value.update.call_args[0][0]
        assert updated["is_done"] is True

    def test_non_assignee_cannot_mark_done(self, client, mock_supabase):
        # Neither the creator nor an assignee may tick the task off.
        _set_get_todo(mock_supabase, {
            **SAMPLE_TODO,
            "assigned_by_id": "someone-else",
            "assigned_to_id": "another-person",
        })

        resp = client.patch("/todos/todo-1", json={"is_done": True})
        assert resp.status_code == 403
        mock_supabase.table.return_value.update.assert_not_called()

    def test_super_user_can_mark_anyones_task_done(self, ishaan_client, mock_supabase):
        # Ishaan is neither the creator nor an assignee of this task.
        _set_get_todo(mock_supabase, {
            **SAMPLE_TODO,
            "assigned_by_id": "someone-else",
            "assigned_to_id": "another-person",
        })
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([{**SAMPLE_TODO, "is_done": True}])

        resp = ishaan_client.patch("/todos/todo-1", json={"is_done": True})
        assert resp.status_code == 200
        assert resp.json()["is_done"] is True
        updated = mock_supabase.table.return_value.update.call_args[0][0]
        assert updated["is_done"] is True

    def test_assignee_can_edit_their_task(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {
            **SAMPLE_TODO,
            "assigned_by_id": "someone-else",
            "assigned_to_id": "test-user-id",
        })
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([{**SAMPLE_TODO, "title": "Assigned rename"}])

        resp = client.patch("/todos/todo-1", json={"title": "Assigned rename"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "Assigned rename"
        updated = mock_supabase.table.return_value.update.call_args[0][0]
        assert updated["title"] == "Assigned rename"

    def test_multi_assignee_can_edit_even_when_not_legacy_first_assignee(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {
            **SAMPLE_TODO,
            "assigned_by_id": "someone-else",
            "assigned_to_id": "u-first",
            "assigned_to_name": "Ishaan",
        })
        mock_supabase.table.return_value \
            .select.return_value \
            .in_.return_value \
            .execute.return_value = _result([
                {"todo_id": "todo-1", "user_id": "u-first", "first_name": "Ishaan"},
                {"todo_id": "todo-1", "user_id": "test-user-id", "first_name": "Test"},
            ])
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([{**SAMPLE_TODO, "title": "Shared rename"}])

        resp = client.patch("/todos/todo-1", json={"title": "Shared rename"})

        assert resp.status_code == 200
        assert resp.json()["title"] == "Shared rename"
        updated = mock_supabase.table.return_value.update.call_args[0][0]
        assert updated["title"] == "Shared rename"

    def test_assignee_can_unassign_their_task(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {
            **SAMPLE_TODO,
            "assigned_by_id": "someone-else",
            "assigned_to_id": "test-user-id",
        })
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([{**SAMPLE_TODO, "assigned_to_id": None, "assigned_to_name": None}])

        resp = client.patch("/todos/todo-1", json={"unassign": True})
        assert resp.status_code == 200
        updated = mock_supabase.table.return_value.update.call_args[0][0]
        assert updated["assigned_to_id"] is None


class TestEstimateDueDate:
    @patch("app.routers.todos.settings.openai_api_key", "sk-test")
    @patch("app.routers.todos.due_date_estimator.estimate_due_date", return_value="2026-06-16")
    def test_returns_recommended_due_date(self, mock_estimate, client, mock_supabase):
        resp = client.post(
            "/todos/estimate-due-date",
            json={"title": "Call back the lead", "description": "Before the demo"},
        )
        assert resp.status_code == 200
        assert resp.json() == {"due_date": "2026-06-16"}
        # Title and description are forwarded to the estimator.
        args = mock_estimate.call_args
        assert args.args[1] == "Call back the lead"
        assert args.args[2] == "Before the demo"

    @patch("app.routers.todos.settings.openai_api_key", "")
    def test_unconfigured_key_returns_503(self, client, mock_supabase):
        resp = client.post("/todos/estimate-due-date", json={"title": "Anything"})
        assert resp.status_code == 503

    @patch("app.routers.todos.settings.openai_api_key", "sk-test")
    @patch("app.routers.todos.due_date_estimator.estimate_due_date", return_value=None)
    def test_estimator_failure_returns_502(self, mock_estimate, client, mock_supabase):
        resp = client.post("/todos/estimate-due-date", json={"title": "Anything"})
        assert resp.status_code == 502

    def test_empty_title_rejected(self, client, mock_supabase):
        resp = client.post("/todos/estimate-due-date", json={"title": ""})
        assert resp.status_code == 422


class TestRecurrence:
    RECURRING = {
        **SAMPLE_TODO,
        "recurrence_interval": 1,
        "recurrence_unit": "week",
        "recurrence_spawned": False,
    }

    def test_create_with_recurrence_persists_rule(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .insert.return_value \
            .execute.return_value = _result([self.RECURRING])

        resp = client.post(
            "/todos",
            json={"title": "Weekly report", "recurrence_interval": 1, "recurrence_unit": "week"},
        )
        assert resp.status_code == 201
        assert resp.json()["recurrence_interval"] == 1
        assert resp.json()["recurrence_unit"] == "week"

        inserted = mock_supabase.table.return_value.insert.call_args_list[0][0][0]
        assert inserted["recurrence_interval"] == 1
        assert inserted["recurrence_unit"] == "week"

    def test_create_rejects_interval_without_unit(self, client, mock_supabase):
        resp = client.post("/todos", json={"title": "Broken", "recurrence_interval": 2})
        assert resp.status_code == 422

    def test_create_rejects_unit_without_interval(self, client, mock_supabase):
        resp = client.post("/todos", json={"title": "Broken", "recurrence_unit": "day"})
        assert resp.status_code == 422

    def test_create_rejects_bad_interval_and_unit(self, client, mock_supabase):
        for body in (
            {"title": "Bad", "recurrence_interval": 0, "recurrence_unit": "day"},
            {"title": "Bad", "recurrence_interval": 400, "recurrence_unit": "day"},
            {"title": "Bad", "recurrence_interval": 1, "recurrence_unit": "year"},
        ):
            resp = client.post("/todos", json=body)
            assert resp.status_code == 422, f"{body} should be rejected"

    def test_completing_recurring_task_spawns_next_occurrence(self, client, mock_supabase):
        _set_get_todo(mock_supabase, self.RECURRING)
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([{**self.RECURRING, "is_done": True}])
        mock_supabase.table.return_value \
            .insert.return_value \
            .execute.return_value = _result([{**self.RECURRING, "id": "todo-next"}])

        resp = client.patch("/todos/todo-1", json={"is_done": True})
        assert resp.status_code == 200
        assert resp.json()["is_done"] is True

        inserted = mock_supabase.table.return_value.insert.call_args_list[0][0][0]
        assert inserted["title"] == self.RECURRING["title"]
        assert inserted["recurrence_interval"] == 1
        assert inserted["recurrence_unit"] == "week"
        # Next occurrence starts open with an advanced due date.
        assert "is_done" not in inserted or not inserted["is_done"]
        assert inserted["due_date"] > self.RECURRING["due_date"]
        # The completed row is flagged so it can never spawn twice.
        update_payloads = [
            call[0][0] for call in mock_supabase.table.return_value.update.call_args_list
        ]
        assert {"recurrence_spawned": True} in update_payloads

    def test_already_spawned_row_does_not_respawn(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {**self.RECURRING, "recurrence_spawned": True})
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([
                {**self.RECURRING, "is_done": True, "recurrence_spawned": True}
            ])

        resp = client.patch("/todos/todo-1", json={"is_done": True})
        assert resp.status_code == 200
        mock_supabase.table.return_value.insert.assert_not_called()

    def test_completing_non_recurring_task_spawns_nothing(self, client, mock_supabase):
        _set_get_todo(mock_supabase, SAMPLE_TODO)
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([{**SAMPLE_TODO, "is_done": True}])

        resp = client.patch("/todos/todo-1", json={"is_done": True})
        assert resp.status_code == 200
        mock_supabase.table.return_value.insert.assert_not_called()

    def test_unticking_recurring_task_spawns_nothing(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {**self.RECURRING, "is_done": True})
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([self.RECURRING])

        resp = client.patch("/todos/todo-1", json={"is_done": False})
        assert resp.status_code == 200
        mock_supabase.table.return_value.insert.assert_not_called()

    def test_patch_can_change_recurrence_rule(self, client, mock_supabase):
        _set_get_todo(mock_supabase, self.RECURRING)
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([
                {**self.RECURRING, "recurrence_interval": 2, "recurrence_unit": "month"}
            ])

        resp = client.patch(
            "/todos/todo-1", json={"recurrence_interval": 2, "recurrence_unit": "month"}
        )
        assert resp.status_code == 200
        updated = mock_supabase.table.return_value.update.call_args[0][0]
        assert updated["recurrence_interval"] == 2
        assert updated["recurrence_unit"] == "month"

    def test_patch_can_clear_recurrence(self, client, mock_supabase):
        _set_get_todo(mock_supabase, self.RECURRING)
        mock_supabase.table.return_value \
            .update.return_value \
            .eq.return_value \
            .execute.return_value = _result([
                {**self.RECURRING, "recurrence_interval": None, "recurrence_unit": None}
            ])

        resp = client.patch(
            "/todos/todo-1", json={"recurrence_interval": None, "recurrence_unit": None}
        )
        assert resp.status_code == 200
        updated = mock_supabase.table.return_value.update.call_args[0][0]
        assert updated["recurrence_interval"] is None
        assert updated["recurrence_unit"] is None

    def test_patch_rejects_partial_recurrence(self, client, mock_supabase):
        _set_get_todo(mock_supabase, self.RECURRING)
        resp = client.patch("/todos/todo-1", json={"recurrence_interval": 2})
        assert resp.status_code == 422


class TestAssignees:
    def test_list_assignees_returns_first_names(self, client, mock_supabase):
        mock_supabase.rpc.return_value.execute.return_value = _result([
            {"id": "u-1", "email": "ishaan@hexaagents.com", "raw_user_meta_data": {"full_name": "Ishaan Gupta"}},
            {"id": "u-2", "email": "srijan@hexaagents.com", "raw_user_meta_data": {"full_name": "Srijan Tandon"}},
        ])

        resp = client.get("/todos/assignees")
        assert resp.status_code == 200
        body = resp.json()
        assert body[0] == {"id": "u-1", "first_name": "Ishaan"}
        assert body[1]["first_name"] == "Srijan"
