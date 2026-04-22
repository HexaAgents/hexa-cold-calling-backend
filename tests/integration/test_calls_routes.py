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


SAMPLE_FULL_CONTACT = {
    "id": "c-1",
    "first_name": "Jane",
    "last_name": "Doe",
    "title": "CEO",
    "company_name": "ACME Corp",
    "person_linkedin_url": None,
    "website": "https://acme.com",
    "company_linkedin_url": None,
    "employees": "50",
    "city": "Berlin",
    "country": "DE",
    "email": "jane@acme.com",
    "mobile_phone": "+491234567890",
    "work_direct_phone": None,
    "corporate_phone": None,
    "score": 85,
    "company_type": "manufacturer",
    "rationale": "Good fit",
    "rejection_reason": None,
    "company_description": "Makes widgets.",
    "exa_scrape_success": True,
    "scoring_failed": False,
    "call_occasion_count": 0,
    "times_called": 0,
    "call_outcome": None,
    "messaging_status": None,
    "sms_sent": False,
    "sms_sent_after_calls": None,
    "sms_scheduled_at": None,
    "enrichment_status": None,
    "apollo_person_id": None,
    "assigned_to": None,
    "assigned_at": None,
    "created_at": "2025-01-01T00:00:00",
}


class TestClaimNextContact:
    def test_claim_returns_contact(self, client, mock_supabase):
        mock_supabase.rpc.return_value \
            .execute.return_value = _make_execute_result([SAMPLE_FULL_CONTACT])

        resp = client.post("/calls/next")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "c-1"
        assert body["company_name"] == "ACME Corp"

    def test_claim_returns_null_when_empty(self, client, mock_supabase):
        mock_supabase.rpc.return_value \
            .execute.return_value = _make_execute_result([])

        resp = client.post("/calls/next")
        assert resp.status_code == 200
        assert resp.json() is None


class TestReleaseContact:
    def test_release_contact(self, client, mock_supabase):
        mock_supabase.rpc.return_value \
            .execute.return_value = _make_execute_result(None)

        resp = client.post("/calls/release/c-1")
        assert resp.status_code == 200
        assert resp.json()["detail"] == "Contact released"


class TestMyQueue:
    def test_get_my_queue(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .is_.return_value \
            .order.return_value \
            .execute.return_value = _make_execute_result([SAMPLE_FULL_CONTACT])

        resp = client.get("/calls/my-queue")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["id"] == "c-1"

    def test_get_my_queue_empty(self, client, mock_supabase):
        mock_supabase.table.return_value \
            .select.return_value \
            .eq.return_value \
            .is_.return_value \
            .order.return_value \
            .execute.return_value = _make_execute_result([])

        resp = client.get("/calls/my-queue")
        assert resp.status_code == 200
        assert resp.json() == []


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
