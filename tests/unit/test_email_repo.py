from __future__ import annotations

from unittest.mock import MagicMock

from app.repositories.email_repo import (
    create_email_log,
    delete_gmail_tokens,
    get_email_logs_for_contact,
    get_gmail_tokens,
    upsert_gmail_tokens,
)


class TestGetGmailTokens:
    def test_returns_tokens(self):
        db = MagicMock()
        token_data = {"user_id": "u-1", "gmail_address": "a@b.com", "access_token": "tok"}
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(data=token_data)

        result = get_gmail_tokens(db, "u-1")

        assert result == token_data
        db.table.assert_called_with("user_gmail_tokens")

    def test_returns_none_when_not_found(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .maybe_single.return_value.execute.return_value = MagicMock(data=None)

        result = get_gmail_tokens(db, "u-1")

        assert result is None


class TestUpsertGmailTokens:
    def test_upserts_and_returns_data(self):
        db = MagicMock()
        db.table.return_value.upsert.return_value.execute.return_value = MagicMock(
            data=[{"user_id": "u-1", "gmail_address": "a@b.com"}]
        )

        result = upsert_gmail_tokens(db, "u-1", {"gmail_address": "a@b.com", "access_token": "tok"})

        assert result["user_id"] == "u-1"
        upsert_call = db.table.return_value.upsert.call_args
        payload = upsert_call[0][0]
        assert payload["user_id"] == "u-1"
        assert payload["gmail_address"] == "a@b.com"
        assert payload["updated_at"] == "now()"
        assert upsert_call[1]["on_conflict"] == "user_id"

    def test_returns_empty_dict_when_no_data(self):
        db = MagicMock()
        db.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])

        result = upsert_gmail_tokens(db, "u-1", {"gmail_address": "a@b.com"})

        assert result == {}


class TestDeleteGmailTokens:
    def test_deletes_and_returns_true(self):
        db = MagicMock()
        db.table.return_value.delete.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[{"user_id": "u-1"}])

        result = delete_gmail_tokens(db, "u-1")

        assert result is True
        db.table.assert_called_with("user_gmail_tokens")

    def test_returns_false_when_nothing_deleted(self):
        db = MagicMock()
        db.table.return_value.delete.return_value.eq.return_value \
            .execute.return_value = MagicMock(data=[])

        result = delete_gmail_tokens(db, "u-1")

        assert result is False


class TestCreateEmailLog:
    def test_creates_and_returns_log(self):
        db = MagicMock()
        db.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": "log-1", "subject": "Test"}]
        )

        log_data = {
            "contact_id": "c-1",
            "user_id": "u-1",
            "gmail_address": "a@b.com",
            "recipient_email": "r@b.com",
            "subject": "Test",
            "body": "Body",
        }
        result = create_email_log(db, log_data)

        assert result["id"] == "log-1"
        db.table.assert_called_with("email_logs")

    def test_returns_empty_dict_when_no_data(self):
        db = MagicMock()
        db.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

        result = create_email_log(db, {"subject": "Test"})

        assert result == {}


class TestGetEmailLogsForContact:
    def test_returns_sorted_logs(self):
        db = MagicMock()
        logs = [
            {"id": "log-2", "sent_at": "2026-04-25T00:00:00"},
            {"id": "log-1", "sent_at": "2026-04-24T00:00:00"},
        ]
        db.table.return_value.select.return_value.eq.return_value \
            .order.return_value.execute.return_value = MagicMock(data=logs)

        result = get_email_logs_for_contact(db, "c-1")

        assert len(result) == 2
        assert result[0]["id"] == "log-2"
        db.table.assert_called_with("email_logs")
        db.table.return_value.select.return_value.eq.assert_called_with("contact_id", "c-1")

    def test_returns_empty_list_when_none(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value \
            .order.return_value.execute.return_value = MagicMock(data=None)

        result = get_email_logs_for_contact(db, "c-1")

        assert result == []
