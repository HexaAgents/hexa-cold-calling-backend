from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def _mock_repos():
    with (
        patch("app.repositories.call_log_repo.has_call_today") as mock_has_call,
        patch("app.repositories.call_log_repo.create_call_log") as mock_create_log,
        patch("app.repositories.contact_repo.get_contact") as mock_get_contact,
        patch("app.repositories.contact_repo.update_contact") as mock_update_contact,
        patch("app.repositories.settings_repo.get_settings") as mock_get_settings,
    ):
        mock_create_log.return_value = {"id": "log-1"}
        mock_get_settings.return_value = {"sms_call_threshold": 3, "retry_days": 3}
        yield {
            "has_call_today": mock_has_call,
            "create_call_log": mock_create_log,
            "get_contact": mock_get_contact,
            "update_contact": mock_update_contact,
            "get_settings": mock_get_settings,
        }


def _contact(occasion_count=0, sms_sent=False):
    return {
        "id": "contact-1",
        "call_occasion_count": occasion_count,
        "sms_sent": sms_sent,
    }


def _call_log_call(db, mocks, outcome="no_answer", callback_date=None):
    from app.services.call_service import log_call

    return log_call(
        db=db,
        contact_id="contact-1",
        user_id="user-1",
        call_method="browser",
        phone_number_called="+1234567890",
        outcome=outcome,
        callback_date=callback_date,
    )


class TestLogCall:
    def test_log_call_new_occasion(self, _mock_repos):
        _mock_repos["has_call_today"].return_value = False
        _mock_repos["get_contact"].return_value = _contact(occasion_count=2)
        db = MagicMock()

        result = _call_log_call(db, _mock_repos)

        assert result["is_new_occasion"] is True
        assert result["occasion_count"] == 3
        update_data = _mock_repos["update_contact"].call_args[0][2]
        assert update_data["call_occasion_count"] == 3

    def test_log_call_same_day_not_new(self, _mock_repos):
        _mock_repos["has_call_today"].return_value = True
        _mock_repos["get_contact"].return_value = _contact(occasion_count=2)
        db = MagicMock()

        result = _call_log_call(db, _mock_repos)

        assert result["is_new_occasion"] is False
        assert result["occasion_count"] == 2
        update_data = _mock_repos["update_contact"].call_args[0][2]
        assert "call_occasion_count" not in update_data

    def test_log_call_sms_prompt_at_threshold(self, _mock_repos):
        _mock_repos["has_call_today"].return_value = False
        _mock_repos["get_contact"].return_value = _contact(occasion_count=2)
        _mock_repos["get_settings"].return_value = {"sms_call_threshold": 3, "retry_days": 3}
        db = MagicMock()

        result = _call_log_call(db, _mock_repos)

        assert result["sms_prompt_needed"] is True

    def test_log_call_sms_not_triggered_below_threshold(self, _mock_repos):
        _mock_repos["has_call_today"].return_value = False
        _mock_repos["get_contact"].return_value = _contact(occasion_count=1)
        _mock_repos["get_settings"].return_value = {"sms_call_threshold": 3, "retry_days": 3}
        db = MagicMock()

        result = _call_log_call(db, _mock_repos)

        assert result["sms_prompt_needed"] is False
        assert result["occasion_count"] == 2

    def test_log_call_sms_not_triggered_if_already_sent(self, _mock_repos):
        _mock_repos["has_call_today"].return_value = False
        _mock_repos["get_contact"].return_value = _contact(occasion_count=2, sms_sent=True)
        _mock_repos["get_settings"].return_value = {"sms_call_threshold": 3, "retry_days": 3}
        db = MagicMock()

        result = _call_log_call(db, _mock_repos)

        assert result["sms_prompt_needed"] is False

    def test_log_call_outcome_saved(self, _mock_repos):
        _mock_repos["has_call_today"].return_value = True
        _mock_repos["get_contact"].return_value = _contact()
        db = MagicMock()

        _call_log_call(db, _mock_repos, outcome="answered")

        update_data = _mock_repos["update_contact"].call_args[0][2]
        assert update_data["call_outcome"] == "answered"

    def test_didnt_pick_up_sets_retry_at(self, _mock_repos):
        """When outcome is didnt_pick_up, retry_at is set N days in the future."""
        from datetime import date, timedelta

        _mock_repos["has_call_today"].return_value = True
        _mock_repos["get_contact"].return_value = _contact()
        _mock_repos["get_settings"].return_value = {"sms_call_threshold": 3, "retry_days": 5}
        db = MagicMock()

        result = _call_log_call(db, _mock_repos, outcome="didnt_pick_up")

        update_data = _mock_repos["update_contact"].call_args[0][2]
        expected = (date.today() + timedelta(days=5)).isoformat()
        assert update_data["retry_at"] == expected
        assert update_data["call_outcome"] == "didnt_pick_up"
        assert result["retry_at"] == expected

    def test_interested_clears_retry_at(self, _mock_repos):
        """Terminal outcomes clear retry_at."""
        _mock_repos["has_call_today"].return_value = True
        _mock_repos["get_contact"].return_value = _contact()
        db = MagicMock()

        result = _call_log_call(db, _mock_repos, outcome="interested")

        update_data = _mock_repos["update_contact"].call_args[0][2]
        assert update_data["retry_at"] is None
        assert update_data["call_outcome"] == "interested"
        assert result["retry_at"] is None

    def test_didnt_pick_up_with_custom_callback_date(self, _mock_repos):
        """Custom callback_date overrides global retry_days."""
        _mock_repos["has_call_today"].return_value = True
        _mock_repos["get_contact"].return_value = _contact()
        _mock_repos["get_settings"].return_value = {"sms_call_threshold": 3, "retry_days": 3}
        db = MagicMock()

        result = _call_log_call(
            db, _mock_repos, outcome="didnt_pick_up", callback_date="2026-05-15",
        )

        update_data = _mock_repos["update_contact"].call_args[0][2]
        assert update_data["retry_at"] == "2026-05-15"
        assert result["retry_at"] == "2026-05-15"

    def test_didnt_pick_up_without_callback_date_uses_global(self, _mock_repos):
        """When no callback_date is given, global retry_days is used."""
        from datetime import date, timedelta

        _mock_repos["has_call_today"].return_value = True
        _mock_repos["get_contact"].return_value = _contact()
        _mock_repos["get_settings"].return_value = {"sms_call_threshold": 3, "retry_days": 7}
        db = MagicMock()

        result = _call_log_call(
            db, _mock_repos, outcome="didnt_pick_up", callback_date=None,
        )

        update_data = _mock_repos["update_contact"].call_args[0][2]
        expected = (date.today() + timedelta(days=7)).isoformat()
        assert update_data["retry_at"] == expected
        assert result["retry_at"] == expected

    def test_non_didnt_pick_up_ignores_callback_date(self, _mock_repos):
        """Passing callback_date with a non-didnt_pick_up outcome still clears retry_at."""
        _mock_repos["has_call_today"].return_value = True
        _mock_repos["get_contact"].return_value = _contact()
        db = MagicMock()

        result = _call_log_call(
            db, _mock_repos, outcome="interested", callback_date="2026-06-01",
        )

        update_data = _mock_repos["update_contact"].call_args[0][2]
        assert update_data["retry_at"] is None
        assert result["retry_at"] is None
