from __future__ import annotations

import json
from unittest.mock import patch

from app.scoring import todo_estimator
from app.scoring.todo_estimator import (
    MAX_DESCRIPTION_CHARS,
    MAX_EXAMPLES,
    MAX_HOURS,
    MAX_TITLE_CHARS,
    MIN_HOURS,
    build_user_message,
    estimate_todo_hours,
    format_calibration_examples,
    _parse_hours,
)


class TestParseHours:
    def test_valid_range(self):
        assert _parse_hours('{"hours_min": 2, "hours_max": 4}') == (2.0, 4.0)

    def test_decimals_rounded_to_one_place(self):
        assert _parse_hours('{"hours_min": 0.333, "hours_max": 1.666}') == (0.3, 1.7)

    def test_swaps_inverted_range(self):
        assert _parse_hours('{"hours_min": 5, "hours_max": 2}') == (2.0, 5.0)

    def test_clamps_to_floor(self):
        assert _parse_hours('{"hours_min": 0, "hours_max": 0.1}') == (MIN_HOURS, MIN_HOURS)

    def test_clamps_to_ceiling(self):
        assert _parse_hours('{"hours_min": 100, "hours_max": 99999}') == (100.0, MAX_HOURS)

    def test_negative_values_clamped(self):
        assert _parse_hours('{"hours_min": -5, "hours_max": -1}') == (MIN_HOURS, MIN_HOURS)

    def test_invalid_json_returns_none(self):
        assert _parse_hours("not json") is None

    def test_missing_fields_returns_none(self):
        assert _parse_hours('{"hours_min": 2}') is None

    def test_non_numeric_returns_none(self):
        assert _parse_hours('{"hours_min": "soon", "hours_max": "later"}') is None


class TestCalibrationExamples:
    def test_formats_examples_with_estimates(self):
        block = format_calibration_examples(
            [
                {
                    "title": "Import June leads",
                    "estimated_hours_min": 1.0,
                    "estimated_hours_max": 2.0,
                    "actual_hours": 1.5,
                }
            ]
        )
        assert '"Import June leads" (estimated 1.0-2.0h) actually took 1.5h' in block

    def test_formats_examples_without_estimates(self):
        block = format_calibration_examples(
            [{"title": "Old task", "actual_hours": 3.0}]
        )
        assert '"Old task" actually took 3.0h' in block

    def test_caps_example_count(self):
        # Token-usage safeguard: at most MAX_EXAMPLES examples in the prompt.
        examples = [
            {"title": f"Task {i}", "actual_hours": 1.0} for i in range(50)
        ]
        block = format_calibration_examples(examples)
        assert block.count("actually took") == MAX_EXAMPLES

    def test_truncates_long_titles(self):
        # Token-usage safeguard: huge titles cannot inflate the prompt.
        block = format_calibration_examples(
            [{"title": "x" * 10_000, "actual_hours": 1.0}]
        )
        assert "x" * (MAX_TITLE_CHARS + 1) not in block
        assert "x" * MAX_TITLE_CHARS in block

    def test_skips_rows_without_title_or_actual(self):
        assert format_calibration_examples([{"title": "", "actual_hours": 1}]) == ""
        assert format_calibration_examples([{"title": "T", "actual_hours": None}]) == ""

    def test_empty_examples_yield_empty_block(self):
        assert format_calibration_examples([]) == ""


class TestBuildUserMessage:
    def test_includes_title_and_description(self):
        msg = build_user_message("Fix import bug", "Dedupe rows", [])
        assert "Task: Fix import bug" in msg
        assert "Description: Dedupe rows" in msg

    def test_truncates_description(self):
        # Token-usage safeguard: descriptions are bounded.
        msg = build_user_message("T", "d" * 50_000, [])
        assert "d" * (MAX_DESCRIPTION_CHARS + 1) not in msg

    def test_omits_empty_description_and_examples(self):
        msg = build_user_message("T", None, [])
        assert "Description:" not in msg
        assert "Past tasks" not in msg

    def test_includes_calibration_block(self):
        msg = build_user_message("T", None, [{"title": "Old", "actual_hours": 2}])
        assert "Past tasks completed by this team:" in msg


class TestEstimateTodoHours:
    @patch("app.scoring.todo_estimator._call_openai")
    def test_returns_parsed_estimate(self, mock_call):
        mock_call.return_value = json.dumps({"hours_min": 1.5, "hours_max": 3})

        result = estimate_todo_hours("key", "Write follow-up emails")

        assert result == {"hours_min": 1.5, "hours_max": 3.0}
        assert mock_call.call_count == 1

    @patch("app.scoring.todo_estimator._call_openai")
    def test_makes_exactly_one_call(self, mock_call):
        # Token-usage safeguard: one request per invocation, no loops.
        mock_call.return_value = json.dumps({"hours_min": 1, "hours_max": 2})

        estimate_todo_hours("key", "Task")

        assert mock_call.call_count == 1

    @patch("app.scoring.todo_estimator._call_openai")
    def test_api_failure_returns_none_without_extra_calls(self, mock_call):
        mock_call.return_value = None

        assert estimate_todo_hours("key", "Task") is None
        assert mock_call.call_count == 1

    @patch("app.scoring.todo_estimator._call_openai")
    def test_unparseable_response_returns_none_without_retry(self, mock_call):
        # Token-usage safeguard: bad output is not "fixed" with more calls.
        mock_call.return_value = "absolutely not json"

        assert estimate_todo_hours("key", "Task") is None
        assert mock_call.call_count == 1

    @patch("app.scoring.todo_estimator._call_openai")
    def test_passes_system_prompt_and_examples(self, mock_call):
        mock_call.return_value = json.dumps({"hours_min": 1, "hours_max": 2})

        estimate_todo_hours(
            "key", "Task", "Desc", [{"title": "Old", "actual_hours": 2}], model="gpt-4o-mini"
        )

        args = mock_call.call_args.args
        assert args[0] == "key"
        assert args[1] == "gpt-4o-mini"
        messages = args[2]
        assert messages[0]["content"] == todo_estimator.ESTIMATE_SYSTEM_PROMPT
        assert "Old" in messages[1]["content"]
