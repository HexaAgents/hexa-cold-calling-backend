"""Tests for the LLM due-date recommendation helper.

Pin down the token-usage and safety bounds: one call with bounded inputs,
strict JSON parsing, and date clamping so a confused model can never return
a past or absurdly distant due date.
"""
from __future__ import annotations

import json
from datetime import date
from unittest.mock import patch

from app.scoring.due_date_estimator import (
    MAX_DESCRIPTION_CHARS,
    MAX_TITLE_CHARS,
    build_user_message,
    estimate_due_date,
)

TODAY = date(2026, 6, 12)  # a Friday


def _estimate(raw_response, title="Call back the lead", description=None):
    with patch("app.scoring.due_date_estimator._call_openai", return_value=raw_response) as mock_call:
        result = estimate_due_date("sk-test", title, description, today=TODAY)
    return result, mock_call


class TestEstimateDueDate:
    def test_returns_recommended_date(self):
        result, mock_call = _estimate(json.dumps({"due_date": "2026-06-16"}))
        assert result == "2026-06-16"
        mock_call.assert_called_once()

    def test_past_date_clamped_to_tomorrow(self):
        result, _ = _estimate(json.dumps({"due_date": "2026-06-01"}))
        assert result == "2026-06-13"

    def test_today_clamped_to_tomorrow(self):
        result, _ = _estimate(json.dumps({"due_date": "2026-06-12"}))
        assert result == "2026-06-13"

    def test_far_future_clamped_to_one_year(self):
        result, _ = _estimate(json.dumps({"due_date": "2099-01-01"}))
        assert result == "2027-06-12"

    def test_api_failure_returns_none(self):
        result, _ = _estimate(None)
        assert result is None

    def test_bad_json_returns_none(self):
        result, _ = _estimate("not json at all")
        assert result is None

    def test_missing_key_returns_none(self):
        result, _ = _estimate(json.dumps({"date": "2026-06-16"}))
        assert result is None

    def test_unparseable_date_returns_none(self):
        result, _ = _estimate(json.dumps({"due_date": "next Tuesday"}))
        assert result is None


class TestBuildUserMessage:
    def test_includes_today_and_weekday(self):
        msg = build_user_message("Call lead", None, TODAY)
        assert "Friday" in msg
        assert "2026-06-12" in msg

    def test_omits_empty_description(self):
        msg = build_user_message("Call lead", "   ", TODAY)
        assert "Description:" not in msg

    def test_truncates_title_and_description(self):
        msg = build_user_message("t" * 500, "d" * 2000, TODAY)
        assert "t" * MAX_TITLE_CHARS in msg
        assert "t" * (MAX_TITLE_CHARS + 1) not in msg
        assert "d" * MAX_DESCRIPTION_CHARS in msg
        assert "d" * (MAX_DESCRIPTION_CHARS + 1) not in msg
