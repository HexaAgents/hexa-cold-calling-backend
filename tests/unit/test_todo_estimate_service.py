from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import todo_estimate_service


def _make_todo(status: str | None = "pending") -> dict:
    return {
        "id": "todo-1",
        "title": "Prepare call list",
        "description": "Filter Texas contacts",
        "estimate_status": status,
    }


class TestGenerateEstimate:
    @patch("app.services.todo_estimate_service.settings")
    @patch("app.services.todo_estimate_service.todo_estimator.estimate_todo_hours")
    @patch("app.services.todo_estimate_service.todo_repo")
    def test_writes_estimate_on_success(self, mock_repo, mock_estimate, mock_settings):
        mock_settings.openai_api_key = "key"
        mock_settings.openai_model = "gpt-4o-mini"
        mock_repo.get_todo.return_value = _make_todo()
        mock_repo.get_calibration_examples.return_value = []
        mock_estimate.return_value = {"hours_min": 1.0, "hours_max": 2.5}
        db = MagicMock()

        todo_estimate_service.generate_estimate(db, "todo-1")

        mock_repo.set_estimate.assert_called_once_with(
            db,
            "todo-1",
            {
                "estimated_hours_min": 1.0,
                "estimated_hours_max": 2.5,
                "estimate_status": "done",
            },
        )
        assert mock_estimate.call_count == 1

    @patch("app.services.todo_estimate_service.settings")
    @patch("app.services.todo_estimate_service.todo_estimator.estimate_todo_hours")
    @patch("app.services.todo_estimate_service.todo_repo")
    def test_noop_unless_pending(self, mock_repo, mock_estimate, mock_settings):
        # Token-usage safeguard: only 'pending' todos are ever estimated.
        mock_settings.openai_api_key = "key"
        db = MagicMock()

        for status in ("done", "failed", None):
            mock_repo.get_todo.return_value = _make_todo(status)
            todo_estimate_service.generate_estimate(db, "todo-1")

        mock_estimate.assert_not_called()
        mock_repo.set_estimate.assert_not_called()

    @patch("app.services.todo_estimate_service.settings")
    @patch("app.services.todo_estimate_service.todo_estimator.estimate_todo_hours")
    @patch("app.services.todo_estimate_service.todo_repo")
    def test_double_invocation_spends_one_call(self, mock_repo, mock_estimate, mock_settings):
        # Token-usage safeguard: a duplicate background task is a no-op
        # because the first run moved the status off 'pending'.
        mock_settings.openai_api_key = "key"
        mock_settings.openai_model = "gpt-4o-mini"
        todo = _make_todo()
        mock_repo.get_todo.return_value = todo
        mock_repo.get_calibration_examples.return_value = []
        mock_estimate.return_value = {"hours_min": 1.0, "hours_max": 2.0}

        def mark_done(db, todo_id, fields):
            todo["estimate_status"] = fields["estimate_status"]

        mock_repo.set_estimate.side_effect = mark_done
        db = MagicMock()

        todo_estimate_service.generate_estimate(db, "todo-1")
        todo_estimate_service.generate_estimate(db, "todo-1")

        assert mock_estimate.call_count == 1

    @patch("app.services.todo_estimate_service.settings")
    @patch("app.services.todo_estimate_service.todo_estimator.estimate_todo_hours")
    @patch("app.services.todo_estimate_service.todo_repo")
    def test_failure_is_terminal(self, mock_repo, mock_estimate, mock_settings):
        # Token-usage safeguard: a failed estimate is marked 'failed' and a
        # re-invocation makes no further OpenAI calls.
        mock_settings.openai_api_key = "key"
        mock_settings.openai_model = "gpt-4o-mini"
        todo = _make_todo()
        mock_repo.get_todo.return_value = todo
        mock_repo.get_calibration_examples.return_value = []
        mock_estimate.return_value = None

        def mark(db, todo_id, fields):
            todo["estimate_status"] = fields["estimate_status"]

        mock_repo.set_estimate.side_effect = mark
        db = MagicMock()

        todo_estimate_service.generate_estimate(db, "todo-1")
        assert todo["estimate_status"] == "failed"

        todo_estimate_service.generate_estimate(db, "todo-1")
        assert mock_estimate.call_count == 1

    @patch("app.services.todo_estimate_service.settings")
    @patch("app.services.todo_estimate_service.todo_estimator.estimate_todo_hours")
    @patch("app.services.todo_estimate_service.todo_repo")
    def test_missing_api_key_fails_without_calling(self, mock_repo, mock_estimate, mock_settings):
        mock_settings.openai_api_key = ""
        mock_repo.get_todo.return_value = _make_todo()
        db = MagicMock()

        todo_estimate_service.generate_estimate(db, "todo-1")

        mock_estimate.assert_not_called()
        mock_repo.set_estimate.assert_called_once_with(
            db, "todo-1", {"estimate_status": "failed"}
        )

    @patch("app.services.todo_estimate_service.settings")
    @patch("app.services.todo_estimate_service.todo_estimator.estimate_todo_hours")
    @patch("app.services.todo_estimate_service.todo_repo")
    def test_missing_todo_is_noop(self, mock_repo, mock_estimate, mock_settings):
        mock_settings.openai_api_key = "key"
        mock_repo.get_todo.return_value = None
        db = MagicMock()

        todo_estimate_service.generate_estimate(db, "missing")

        mock_estimate.assert_not_called()
        mock_repo.set_estimate.assert_not_called()

    @patch("app.services.todo_estimate_service.settings")
    @patch("app.services.todo_estimate_service.todo_estimator.estimate_todo_hours")
    @patch("app.services.todo_estimate_service.todo_repo")
    def test_unexpected_exception_marks_failed_and_never_raises(
        self, mock_repo, mock_estimate, mock_settings
    ):
        mock_settings.openai_api_key = "key"
        mock_settings.openai_model = "gpt-4o-mini"
        mock_repo.get_todo.return_value = _make_todo()
        mock_repo.get_calibration_examples.side_effect = RuntimeError("db down")
        db = MagicMock()

        todo_estimate_service.generate_estimate(db, "todo-1")  # must not raise

        mock_estimate.assert_not_called()
        mock_repo.set_estimate.assert_called_once_with(
            db, "todo-1", {"estimate_status": "failed"}
        )

    @patch("app.services.todo_estimate_service.settings")
    @patch("app.services.todo_estimate_service.todo_estimator.estimate_todo_hours")
    @patch("app.services.todo_estimate_service.todo_repo")
    def test_passes_calibration_examples(self, mock_repo, mock_estimate, mock_settings):
        mock_settings.openai_api_key = "key"
        mock_settings.openai_model = "gpt-4o-mini"
        mock_repo.get_todo.return_value = _make_todo()
        examples = [{"title": "Old", "actual_hours": 2}]
        mock_repo.get_calibration_examples.return_value = examples
        mock_estimate.return_value = {"hours_min": 1.0, "hours_max": 2.0}
        db = MagicMock()

        todo_estimate_service.generate_estimate(db, "todo-1")

        assert mock_estimate.call_args.kwargs["examples"] == examples
