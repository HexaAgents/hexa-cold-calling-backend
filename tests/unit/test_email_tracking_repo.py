from __future__ import annotations

from unittest.mock import MagicMock

from app.repositories.email_tracking_repo import (
    get_tracked_contacts_summary,
    get_tracked_thread,
    upsert_tracked_emails,
)


class TestUpsertTrackedEmails:
    def test_upserts_and_returns_count(self):
        db = MagicMock()
        db.table.return_value.upsert.return_value.execute.return_value = MagicMock(
            data=[{"id": "e-1"}, {"id": "e-2"}]
        )

        count = upsert_tracked_emails(db, [{"gmail_message_id": "m1"}, {"gmail_message_id": "m2"}])

        assert count == 2
        db.table.assert_called_with("tracked_emails")

    def test_returns_zero_for_empty_list(self):
        db = MagicMock()
        count = upsert_tracked_emails(db, [])
        assert count == 0
        db.table.assert_not_called()


class TestGetTrackedContactsSummary:
    def test_returns_summaries_with_stats(self):
        db = MagicMock()

        tracked_data = [
            {"contact_id": "c-1", "direction": "sent", "message_date": "2026-04-25T10:00:00"},
            {"contact_id": "c-1", "direction": "received", "message_date": "2026-04-25T11:00:00"},
            {"contact_id": "c-1", "direction": "sent", "message_date": "2026-04-24T09:00:00"},
            {"contact_id": "c-2", "direction": "sent", "message_date": "2026-04-25T08:00:00"},
        ]
        contacts_data = [
            {"id": "c-1", "first_name": "Alex", "last_name": "Smith", "company_name": "ACME", "email": "alex@acme.com"},
            {"id": "c-2", "first_name": "Bob", "last_name": "Jones", "company_name": "XYZ", "email": "bob@xyz.com"},
        ]

        mock_tracked = MagicMock()
        mock_tracked.select.return_value.eq.return_value \
            .not_.is_.return_value.order.return_value.execute.return_value = MagicMock(data=tracked_data)

        mock_contacts = MagicMock()
        mock_contacts.select.return_value.in_.return_value \
            .execute.return_value = MagicMock(data=contacts_data)

        def table_router(name):
            if name == "tracked_emails":
                return mock_tracked
            return mock_contacts

        db.table.side_effect = table_router

        result = get_tracked_contacts_summary(db, "user-1")

        assert len(result) == 2
        c1 = next(r for r in result if r["contact_id"] == "c-1")
        assert c1["sent_count"] == 2
        assert c1["received_count"] == 1
        assert c1["reply_status"] == "replied"
        assert c1["first_name"] == "Alex"

        c2 = next(r for r in result if r["contact_id"] == "c-2")
        assert c2["sent_count"] == 1
        assert c2["received_count"] == 0
        assert c2["reply_status"] == "awaiting_reply"

    def test_returns_empty_when_no_tracked_emails(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .not_.is_.return_value.order.return_value.execute.return_value = MagicMock(data=[])

        result = get_tracked_contacts_summary(db, "user-1")

        assert result == []


class TestGetTrackedThread:
    def test_returns_thread(self):
        db = MagicMock()
        emails = [
            {"id": "e-1", "subject": "Hi", "direction": "sent", "message_date": "2026-04-25T10:00:00"},
            {"id": "e-2", "subject": "Re: Hi", "direction": "received", "message_date": "2026-04-25T11:00:00"},
        ]
        db.table.return_value.select.return_value.eq.return_value \
            .eq.return_value.order.return_value.execute.return_value = MagicMock(data=emails)

        result = get_tracked_thread(db, "user-1", "contact-1")

        assert len(result) == 2
        assert result[0]["id"] == "e-1"

    def test_returns_empty_list(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .eq.return_value.order.return_value.execute.return_value = MagicMock(data=[])

        result = get_tracked_thread(db, "user-1", "contact-1")

        assert result == []
