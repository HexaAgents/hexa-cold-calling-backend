from __future__ import annotations

from unittest.mock import MagicMock


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

        inserted = mock_supabase.table.return_value.insert.call_args[0][0]
        assert inserted["description"] == "Internal-only detail"
        assert inserted["assigned_to_id"] == "u-2"
        assert inserted["assigned_to_name"] == "Srijan"
        assert inserted["due_date"] == "2026-02-01"

    def test_create_without_description_but_with_assignee(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .insert.return_value \
            .execute.return_value = _result([SAMPLE_TODO])

        resp = client.post(
            "/todos",
            json={"title": "Quick task", "assigned_to_id": "u-3", "assigned_to_name": "Mann"},
        )
        assert resp.status_code == 201
        inserted = mock_supabase.table.return_value.insert.call_args[0][0]
        assert inserted["description"] is None
        assert inserted["assigned_to_name"] == "Mann"


class TestListTodos:
    def test_list_orders_by_due_date_nulls_last(self, client, mock_supabase):
        no_due = {**SAMPLE_TODO, "id": "todo-2", "due_date": None}
        mock_supabase.table.return_value \
            .select.return_value \
            .order.return_value \
            .order.return_value \
            .execute.return_value = _result([SAMPLE_TODO, no_due])

        resp = client.get("/todos")
        assert resp.status_code == 200
        assert len(resp.json()) == 2
        # Ordering is delegated to Postgres: closest due dates first, nulls last.
        mock_supabase.table.return_value.select.return_value.order.assert_any_call(
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
        # Assigned by someone else, but the current user is the assignee.
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

    def test_assignee_cannot_edit_other_fields(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {
            **SAMPLE_TODO,
            "assigned_by_id": "someone-else",
            "assigned_to_id": "test-user-id",
        })
        resp = client.patch("/todos/todo-1", json={"title": "Sneaky rename"})
        assert resp.status_code == 403

    def test_assignee_cannot_unassign(self, client, mock_supabase):
        _set_get_todo(mock_supabase, {
            **SAMPLE_TODO,
            "assigned_by_id": "someone-else",
            "assigned_to_id": "test-user-id",
        })
        resp = client.patch("/todos/todo-1", json={"unassign": True})
        assert resp.status_code == 403


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
