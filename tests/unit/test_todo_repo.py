from __future__ import annotations

from app.repositories import todo_repo


class TestTodoRepoAssigneeNormalization:
    def test_normalize_uses_explicit_assignee_list_and_mirrors_first_person(self):
        row = {
            "id": "todo-1",
            "assigned_to_id": "legacy-user",
            "assigned_to_name": "Legacy",
            "assignees": [
                {"id": "u-1", "first_name": "Ishaan"},
                {"id": "u-2", "first_name": "Srijan"},
            ],
        }

        normalized = todo_repo._normalize_assignees(row)

        assert normalized["assignees"] == [
            {"id": "u-1", "first_name": "Ishaan"},
            {"id": "u-2", "first_name": "Srijan"},
        ]
        assert normalized["assigned_to_id"] == "u-1"
        assert normalized["assigned_to_name"] == "Ishaan"

    def test_normalize_falls_back_to_legacy_assignee_columns(self):
        row = {
            "id": "todo-1",
            "assigned_to_id": "u-legacy",
            "assigned_to_name": "Mann",
        }

        normalized = todo_repo._normalize_assignees(row)

        assert normalized["assignees"] == [{"id": "u-legacy", "first_name": "Mann"}]
        assert normalized["assigned_to_id"] == "u-legacy"
        assert normalized["assigned_to_name"] == "Mann"

    def test_normalize_handles_unassigned_rows(self):
        row = {
            "id": "todo-1",
            "assigned_to_id": None,
            "assigned_to_name": None,
        }

        normalized = todo_repo._normalize_assignees(row)

        assert normalized["assignees"] == []
        assert normalized["assigned_to_id"] is None
        assert normalized["assigned_to_name"] is None


class TestTodoRepoFirstAssigneeMirror:
    def test_mirror_first_assignee_updates_legacy_columns(self):
        mirrored = todo_repo._mirror_first_assignee(
            {"title": "Shared task"},
            [
                {"id": "u-1", "first_name": "Ishaan"},
                {"id": "u-2", "first_name": "Srijan"},
            ],
        )

        assert mirrored["assigned_to_id"] == "u-1"
        assert mirrored["assigned_to_name"] == "Ishaan"

    def test_mirror_empty_assignee_list_clears_legacy_columns(self):
        mirrored = todo_repo._mirror_first_assignee({"title": "Unassigned"}, [])

        assert mirrored["assigned_to_id"] is None
        assert mirrored["assigned_to_name"] is None

    def test_mirror_none_leaves_data_unchanged_when_assignees_not_provided(self):
        data = {"title": "Keep current assignees"}

        mirrored = todo_repo._mirror_first_assignee(data, None)

        assert mirrored is data
