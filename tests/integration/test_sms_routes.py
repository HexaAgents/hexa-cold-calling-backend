from __future__ import annotations

from unittest.mock import MagicMock, patch


SAMPLE_CONTACT = {
    "id": "c-1",
    "company_name": "ACME Corp",
    "first_name": "Jane",
    "last_name": "Doe",
    "title": "CEO",
    "website": "https://acme.com",
    "mobile_phone": "+491234567890",
    "call_occasion_count": 3,
    "sms_sent": False,
    "messaging_status": None,
}

SAMPLE_SETTINGS = {
    "id": "settings-1",
    "sms_call_threshold": 3,
    "sms_template": "Hi <first_name>, this is Hexa Agents.",
}


class TestSendSMS:
    @patch("app.services.sms_service.TwilioClient")
    @patch("app.services.sms_service.contact_repo")
    @patch("app.services.sms_service.settings_repo")
    def test_send_sms_success(
        self, mock_settings_repo, mock_contact_repo, mock_twilio_cls,
        client, mock_supabase,
    ):
        mock_contact_repo.get_contact.return_value = SAMPLE_CONTACT
        mock_contact_repo.update_contact.return_value = None
        mock_settings_repo.get_settings.return_value = SAMPLE_SETTINGS

        mock_twilio = MagicMock()
        mock_twilio_cls.return_value = mock_twilio
        mock_twilio.messages.create.return_value = MagicMock(sid="SM123")

        resp = client.post("/sms/send", json={"contact_id": "c-1"})

        assert resp.status_code == 200
        body = resp.json()
        assert body["message_sid"] == "SM123"
        assert "Jane" in body["body"]

        mock_twilio.messages.create.assert_called_once()
        call_kwargs = mock_twilio.messages.create.call_args.kwargs
        assert call_kwargs["to"] == "+491234567890"


class TestScheduleSMS:
    @patch("app.services.sms_service.contact_repo")
    def test_schedule_sms(self, mock_contact_repo, client, mock_supabase):
        mock_contact_repo.get_contact.return_value = SAMPLE_CONTACT
        mock_contact_repo.update_contact.return_value = None

        resp = client.post("/sms/schedule", json={
            "contact_id": "c-1",
            "scheduled_at": "2025-06-01T09:00:00",
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["contact_id"] == "c-1"
        assert "2025-06-01" in body["scheduled_at"]
