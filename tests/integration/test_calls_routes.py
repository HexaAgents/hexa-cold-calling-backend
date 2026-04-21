from __future__ import annotations

from unittest.mock import MagicMock, patch


SAMPLE_CALL_LOG = {
    "id": "log-1",
    "contact_id": "c-1",
    "user_id": "test-user-id",
    "call_date": "2025-01-15",
    "call_method": "browser",
    "phone_number_called": "+491234567890",
    "outcome": "no_answer",
    "is_new_occasion": True,
    "created_at": "2025-01-15T10:00:00",
}

SAMPLE_CONTACT = {
    "id": "c-1",
    "company_name": "ACME Corp",
    "call_occasion_count": 2,
    "call_outcome": "no_answer",
    "sms_sent": False,
}

SAMPLE_SETTINGS = {
    "id": "settings-1",
    "sms_call_threshold": 3,
    "sms_template": "Hello",
}


def _make_execute_result(data, count=None):
    result = MagicMock()
    result.data = data
    result.count = count
    return result


class TestLogCall:
    @patch("app.services.call_service.settings_repo")
    @patch("app.services.call_service.contact_repo")
    @patch("app.services.call_service.call_log_repo")
    def test_log_call(
        self, mock_call_log_repo, mock_contact_repo, mock_settings_repo,
        client, mock_supabase,
    ):
        mock_call_log_repo.has_call_today.return_value = False
        mock_call_log_repo.create_call_log.return_value = SAMPLE_CALL_LOG
        mock_contact_repo.get_contact.return_value = SAMPLE_CONTACT
        mock_contact_repo.update_contact.return_value = None
        mock_settings_repo.get_settings.return_value = SAMPLE_SETTINGS

        resp = client.post("/calls/log", json={
            "contact_id": "c-1",
            "call_method": "browser",
            "phone_number_called": "+491234567890",
            "outcome": "no_answer",
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["call_log"]["id"] == "log-1"
        assert body["call_log"]["contact_id"] == "c-1"
        assert isinstance(body["sms_prompt_needed"], bool)
        assert isinstance(body["occasion_count"], int)


class TestCallHistory:
    def test_get_call_history(self, client, mock_supabase):
        second = {**SAMPLE_CALL_LOG, "id": "log-2", "outcome": "voicemail"}
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .order.return_value \
            .execute.return_value = _make_execute_result(
                [SAMPLE_CALL_LOG, second],
            )

        resp = client.get("/calls/contact/c-1")
        assert resp.status_code == 200

        body = resp.json()
        assert len(body) == 2
        assert body[0]["id"] == "log-1"
        assert body[1]["outcome"] == "voicemail"
