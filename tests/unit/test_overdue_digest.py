from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from app.tasks import overdue_digest


PACIFIC = ZoneInfo("America/Los_Angeles")
TODAY = date(2026, 6, 12)

DIRECTORY = {
    "user-1": {"email": "alice@example.com", "first_name": "Alice"},
    "user-2": {"email": "bob@example.com", "first_name": "Bob"},
    "user-3": {"email": None, "first_name": "NoEmail"},
}

SENDER_TOKENS = {"user_id": "admin-user-id", "gmail_address": "admin@hexaagents.com"}


def _todo(todo_id: str, assignee_ids: list[str], due: str = "2026-06-10", title: str = "Task") -> dict:
    return {
        "id": todo_id,
        "title": title,
        "due_date": due,
        "is_done": False,
        "assignees": [{"id": uid, "first_name": uid} for uid in assignee_ids],
    }


@patch("app.tasks.overdue_digest.email_service")
@patch("app.tasks.overdue_digest.email_repo")
@patch("app.tasks.overdue_digest.user_repo")
@patch("app.tasks.overdue_digest.todo_repo")
class TestSendOverdueDigests:
    def test_groups_tasks_by_assignee_and_sends_one_email_each(
        self, mock_todo_repo, mock_user_repo, mock_email_repo, mock_email_service
    ):
        mock_todo_repo.get_overdue_todos.return_value = [
            _todo("t1", ["user-1"], title="Call leads"),
            _todo("t2", ["user-1", "user-2"], title="Send report"),
        ]
        mock_user_repo.get_auth_user_directory.return_value = DIRECTORY
        mock_email_repo.get_gmail_tokens_by_address.return_value = SENDER_TOKENS

        sent = overdue_digest.send_overdue_digests(MagicMock(), TODAY)

        assert sent == 2
        recipients = {c.args[2] for c in mock_email_service.send_direct_email.call_args_list}
        assert recipients == {"alice@example.com", "bob@example.com"}

        # Alice has both tasks in one email; Bob only the shared one.
        by_recipient = {c.args[2]: c for c in mock_email_service.send_direct_email.call_args_list}
        alice_subject, alice_body = by_recipient["alice@example.com"].args[3:5]
        assert alice_subject == "You have 2 overdue tasks"
        assert "Call leads" in alice_body and "Send report" in alice_body
        bob_subject, bob_body = by_recipient["bob@example.com"].args[3:5]
        assert bob_subject == "You have 1 overdue task"
        assert "Send report" in bob_body and "Call leads" not in bob_body

    def test_sends_from_admin_account(
        self, mock_todo_repo, mock_user_repo, mock_email_repo, mock_email_service
    ):
        mock_todo_repo.get_overdue_todos.return_value = [_todo("t1", ["user-1"])]
        mock_user_repo.get_auth_user_directory.return_value = DIRECTORY
        mock_email_repo.get_gmail_tokens_by_address.return_value = SENDER_TOKENS

        overdue_digest.send_overdue_digests(MagicMock(), TODAY)

        sender_user_id = mock_email_service.send_direct_email.call_args.args[1]
        assert sender_user_id == "admin-user-id"

    def test_skips_users_without_email(
        self, mock_todo_repo, mock_user_repo, mock_email_repo, mock_email_service
    ):
        mock_todo_repo.get_overdue_todos.return_value = [_todo("t1", ["user-3"])]
        mock_user_repo.get_auth_user_directory.return_value = DIRECTORY
        mock_email_repo.get_gmail_tokens_by_address.return_value = SENDER_TOKENS

        sent = overdue_digest.send_overdue_digests(MagicMock(), TODAY)

        assert sent == 0
        mock_email_service.send_direct_email.assert_not_called()

    def test_noop_when_nothing_overdue(
        self, mock_todo_repo, mock_user_repo, mock_email_repo, mock_email_service
    ):
        mock_todo_repo.get_overdue_todos.return_value = []

        sent = overdue_digest.send_overdue_digests(MagicMock(), TODAY)

        assert sent == 0
        mock_email_repo.get_gmail_tokens_by_address.assert_not_called()
        mock_email_service.send_direct_email.assert_not_called()

    def test_skips_unassigned_overdue_tasks(
        self, mock_todo_repo, mock_user_repo, mock_email_repo, mock_email_service
    ):
        mock_todo_repo.get_overdue_todos.return_value = [_todo("t1", [])]

        sent = overdue_digest.send_overdue_digests(MagicMock(), TODAY)

        assert sent == 0
        mock_email_service.send_direct_email.assert_not_called()

    def test_skips_all_when_sender_not_connected(
        self, mock_todo_repo, mock_user_repo, mock_email_repo, mock_email_service
    ):
        mock_todo_repo.get_overdue_todos.return_value = [_todo("t1", ["user-1"])]
        mock_user_repo.get_auth_user_directory.return_value = DIRECTORY
        mock_email_repo.get_gmail_tokens_by_address.return_value = None

        sent = overdue_digest.send_overdue_digests(MagicMock(), TODAY)

        assert sent == 0
        mock_email_service.send_direct_email.assert_not_called()

    def test_one_failed_send_does_not_block_others(
        self, mock_todo_repo, mock_user_repo, mock_email_repo, mock_email_service
    ):
        mock_todo_repo.get_overdue_todos.return_value = [
            _todo("t1", ["user-1"]),
            _todo("t2", ["user-2"]),
        ]
        mock_user_repo.get_auth_user_directory.return_value = DIRECTORY
        mock_email_repo.get_gmail_tokens_by_address.return_value = SENDER_TOKENS
        mock_email_service.send_direct_email.side_effect = [Exception("boom"), {}]

        sent = overdue_digest.send_overdue_digests(MagicMock(), TODAY)

        assert sent == 1
        assert mock_email_service.send_direct_email.call_count == 2


@patch("app.tasks.overdue_digest.send_overdue_digests")
@patch("app.tasks.overdue_digest.settings_repo")
class TestRunDigestIfDue:
    def test_does_not_send_before_send_hour(self, mock_settings_repo, mock_send):
        before = datetime(2026, 6, 12, 9, 0, tzinfo=PACIFIC)

        assert overdue_digest.run_digest_if_due(MagicMock(), before) is False
        mock_send.assert_not_called()

    def test_sends_after_hour_and_records_date(self, mock_settings_repo, mock_send):
        mock_settings_repo.get_settings.return_value = {
            "id": "settings-1",
            "overdue_digest_last_sent": "2026-06-11",
        }
        mock_send.return_value = 3
        after = datetime(2026, 6, 12, 17, 5, tzinfo=PACIFIC)

        assert overdue_digest.run_digest_if_due(MagicMock(), after) is True
        mock_send.assert_called_once()
        assert mock_send.call_args.args[1] == TODAY
        mock_settings_repo.update_settings.assert_called_once()
        assert mock_settings_repo.update_settings.call_args.args[2] == {
            "overdue_digest_last_sent": "2026-06-12"
        }

    def test_idempotent_when_already_sent_today(self, mock_settings_repo, mock_send):
        mock_settings_repo.get_settings.return_value = {
            "id": "settings-1",
            "overdue_digest_last_sent": "2026-06-12",
        }
        after = datetime(2026, 6, 12, 18, 0, tzinfo=PACIFIC)

        assert overdue_digest.run_digest_if_due(MagicMock(), after) is False
        mock_send.assert_not_called()

    def test_sends_when_never_sent_before(self, mock_settings_repo, mock_send):
        mock_settings_repo.get_settings.return_value = {"id": "settings-1"}
        mock_send.return_value = 0
        after = datetime(2026, 6, 12, 17, 0, tzinfo=PACIFIC)

        assert overdue_digest.run_digest_if_due(MagicMock(), after) is True
        mock_send.assert_called_once()

    def test_uses_pacific_date_for_utc_input(self, mock_settings_repo, mock_send):
        mock_settings_repo.get_settings.return_value = {"id": "settings-1"}
        mock_send.return_value = 0
        # 2026-06-13 01:00 UTC == 2026-06-12 18:00 Pacific (PDT).
        utc_evening = datetime(2026, 6, 13, 1, 0, tzinfo=ZoneInfo("UTC"))

        assert overdue_digest.run_digest_if_due(MagicMock(), utc_evening) is True
        assert mock_send.call_args.args[1] == TODAY

    def test_does_not_send_when_recording_date_fails(self, mock_settings_repo, mock_send):
        # Anti-flood guarantee: if the send date cannot be persisted (e.g. the
        # overdue_digest_last_sent column is missing), we must send zero emails
        # rather than resend on every poll.
        mock_settings_repo.get_settings.return_value = {"id": "settings-1"}
        mock_settings_repo.update_settings.side_effect = Exception("column does not exist")
        after = datetime(2026, 6, 12, 17, 5, tzinfo=PACIFIC)

        assert overdue_digest.run_digest_if_due(MagicMock(), after) is False
        mock_send.assert_not_called()

    def test_does_not_send_when_no_settings_row(self, mock_settings_repo, mock_send):
        # No settings row means we cannot claim the day, so we must not send.
        mock_settings_repo.get_settings.return_value = {}
        after = datetime(2026, 6, 12, 17, 5, tzinfo=PACIFIC)

        assert overdue_digest.run_digest_if_due(MagicMock(), after) is False
        mock_send.assert_not_called()
        mock_settings_repo.update_settings.assert_not_called()

    def test_claims_the_day_before_sending(self, mock_settings_repo, mock_send):
        # The send date must be recorded BEFORE any email is sent, so a crash
        # mid-send cannot lead to a resend flood on the next poll.
        order: list[str] = []
        mock_settings_repo.update_settings.side_effect = lambda *a, **k: order.append("claim")
        mock_send.side_effect = lambda *a, **k: (order.append("send"), 2)[1]
        mock_settings_repo.get_settings.return_value = {
            "id": "settings-1",
            "overdue_digest_last_sent": "2026-06-11",
        }
        after = datetime(2026, 6, 12, 17, 5, tzinfo=PACIFIC)

        assert overdue_digest.run_digest_if_due(MagicMock(), after) is True
        assert order == ["claim", "send"]
