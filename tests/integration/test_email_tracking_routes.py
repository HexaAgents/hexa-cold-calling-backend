from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestSyncEndpoint:
    @patch("app.services.email_service.sync_emails_for_user")
    def test_sync_success(self, mock_sync, client, mock_supabase):
        mock_sync.return_value = 5

        resp = client.post("/email/tracking/sync")

        assert resp.status_code == 200
        assert resp.json()["synced"] == 5

    @patch("app.services.email_service.sync_emails_for_user")
    def test_sync_gmail_not_connected(self, mock_sync, client, mock_supabase):
        mock_sync.side_effect = ValueError("Gmail not connected")

        resp = client.post("/email/tracking/sync")

        assert resp.status_code == 400

    @patch("app.services.email_service.sync_emails_for_user")
    def test_sync_error(self, mock_sync, client, mock_supabase):
        mock_sync.side_effect = Exception("API error")

        resp = client.post("/email/tracking/sync")

        assert resp.status_code == 500


class TestGetTrackedContacts:
    @patch("app.repositories.email_tracking_repo.get_tracked_contacts_summary")
    def test_returns_contacts(self, mock_summary, client, mock_supabase):
        mock_summary.return_value = [
            {
                "contact_id": "c-1",
                "first_name": "Alex",
                "last_name": "Smith",
                "company_name": "ACME",
                "email": "alex@acme.com",
                "sent_count": 3,
                "received_count": 1,
                "last_sent_at": "2026-04-25T10:00:00",
                "last_received_at": "2026-04-25T12:00:00",
                "reply_status": "replied",
            },
        ]

        resp = client.get("/email/tracking")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["contact_id"] == "c-1"
        assert data[0]["reply_status"] == "replied"

    @patch("app.repositories.email_tracking_repo.get_tracked_contacts_summary")
    def test_returns_empty_list(self, mock_summary, client, mock_supabase):
        mock_summary.return_value = []

        resp = client.get("/email/tracking")

        assert resp.status_code == 200
        assert resp.json() == []


class TestGetTrackedThread:
    @patch("app.repositories.email_tracking_repo.get_tracked_thread")
    def test_returns_thread(self, mock_thread, client, mock_supabase):
        mock_thread.return_value = [
            {
                "id": "e-1",
                "gmail_message_id": "msg-1",
                "from_address": "user@gmail.com",
                "to_address": "alex@acme.com",
                "subject": "Follow up",
                "snippet": "Hi Alex",
                "direction": "sent",
                "message_date": "2026-04-25T10:00:00",
                "synced_at": "2026-04-25T10:05:00",
            },
            {
                "id": "e-2",
                "gmail_message_id": "msg-2",
                "from_address": "alex@acme.com",
                "to_address": "user@gmail.com",
                "subject": "Re: Follow up",
                "snippet": "Thanks for reaching out",
                "direction": "received",
                "message_date": "2026-04-25T11:00:00",
                "synced_at": "2026-04-25T11:05:00",
            },
        ]

        resp = client.get("/email/tracking/c-1")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["direction"] == "sent"
        assert data[1]["direction"] == "received"

    @patch("app.repositories.email_tracking_repo.get_tracked_thread")
    def test_returns_empty_thread(self, mock_thread, client, mock_supabase):
        mock_thread.return_value = []

        resp = client.get("/email/tracking/c-1")

        assert resp.status_code == 200
        assert resp.json() == []
