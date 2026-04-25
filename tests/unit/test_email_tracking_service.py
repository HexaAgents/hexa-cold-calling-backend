from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestGetHeader:
    def test_finds_header(self):
        from app.services.email_service import _get_header

        headers = [
            {"name": "From", "value": "alice@example.com"},
            {"name": "Subject", "value": "Hello"},
        ]
        assert _get_header(headers, "From") == "alice@example.com"
        assert _get_header(headers, "Subject") == "Hello"

    def test_case_insensitive(self):
        from app.services.email_service import _get_header

        headers = [{"name": "FROM", "value": "alice@example.com"}]
        assert _get_header(headers, "from") == "alice@example.com"

    def test_returns_empty_when_missing(self):
        from app.services.email_service import _get_header

        assert _get_header([], "From") == ""
        assert _get_header([{"name": "To", "value": "x"}], "From") == ""


class TestSyncEmailsForContact:
    @patch("app.services.email_service._fetch_gmail_messages")
    @patch("app.services.email_service.email_tracking_repo")
    @patch("app.services.email_service._get_valid_access_token")
    def test_syncs_messages(self, mock_token, mock_repo, mock_fetch):
        from app.services.email_service import sync_emails_for_contact

        mock_token.return_value = ("ya29.tok", "user@gmail.com")
        mock_fetch.return_value = [
            {
                "id": "msg-1",
                "internalDate": "1745600000000",
                "snippet": "Hello there",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "contact@acme.com"},
                        {"name": "To", "value": "user@gmail.com"},
                        {"name": "Subject", "value": "Re: Follow up"},
                        {"name": "Date", "value": "Fri, 25 Apr 2025 10:00:00 +0000"},
                    ],
                },
            },
        ]
        mock_repo.upsert_tracked_emails.return_value = 1
        db = MagicMock()

        count = sync_emails_for_contact(db, "user-1", "contact@acme.com", "c-1")

        assert count == 1
        mock_fetch.assert_called_once()
        rows = mock_repo.upsert_tracked_emails.call_args[0][1]
        assert len(rows) == 1
        assert rows[0]["direction"] == "received"
        assert rows[0]["gmail_message_id"] == "msg-1"
        assert rows[0]["contact_id"] == "c-1"

    @patch("app.services.email_service._get_valid_access_token")
    def test_returns_zero_when_gmail_not_connected(self, mock_token):
        from app.services.email_service import sync_emails_for_contact

        mock_token.side_effect = ValueError("Gmail not connected")
        db = MagicMock()

        count = sync_emails_for_contact(db, "user-1", "contact@acme.com", "c-1")

        assert count == 0

    @patch("app.services.email_service._fetch_gmail_messages")
    @patch("app.services.email_service._get_valid_access_token")
    def test_returns_zero_on_fetch_error(self, mock_token, mock_fetch):
        from app.services.email_service import sync_emails_for_contact

        mock_token.return_value = ("ya29.tok", "user@gmail.com")
        mock_fetch.side_effect = Exception("API error")
        db = MagicMock()

        count = sync_emails_for_contact(db, "user-1", "contact@acme.com", "c-1")

        assert count == 0


class TestSyncEmailsForUser:
    @patch("app.services.email_service.sync_emails_for_contact")
    def test_syncs_all_interacted_contacts(self, mock_sync_contact):
        from app.services.email_service import sync_emails_for_user

        mock_sync_contact.return_value = 3
        db = MagicMock()

        db.table.return_value.select.return_value.eq.return_value \
            .not_.is_.return_value.execute.return_value = MagicMock(
                data=[{"contact_id": "c-1"}, {"contact_id": "c-2"}]
            )

        contacts_data = [
            {"id": "c-1", "email": "alice@acme.com"},
            {"id": "c-2", "email": "bob@xyz.com"},
        ]
        db.table.return_value.select.return_value.in_.return_value \
            .not_.is_.return_value.execute.return_value = MagicMock(data=contacts_data)

        total = sync_emails_for_user(db, "user-1")

        assert total == 6
        assert mock_sync_contact.call_count == 2

    @patch("app.services.email_service.sync_emails_for_contact")
    def test_returns_zero_when_no_contacts(self, mock_sync_contact):
        from app.services.email_service import sync_emails_for_user

        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .not_.is_.return_value.execute.return_value = MagicMock(data=[])

        total = sync_emails_for_user(db, "user-1")

        assert total == 0
        mock_sync_contact.assert_not_called()
