"""One-off live test of the overdue digest flow.

Runs the real digest pipeline (overdue query, user directory, admin Gmail
sender) but only delivers the email to TEST_RECIPIENT. If that user has no
overdue tasks, a sample task is substituted so the send path still runs.

Usage: .venv/bin/python scripts/test_overdue_digest.py
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime

sys.path.insert(0, ".")

from app.config import settings
from app.dependencies import get_supabase
from app.repositories import email_repo, todo_repo, user_repo
from app.services import email_service
from app.tasks.overdue_digest import DIGEST_TIMEZONE, _build_email

logging.basicConfig(level=logging.INFO)

TEST_RECIPIENT = "ishaan@hexaagents.com"


def main() -> None:
    db = get_supabase()
    today = datetime.now(tz=DIGEST_TIMEZONE).date()
    print(f"Today (Pacific): {today}")

    directory = user_repo.get_auth_user_directory(db)
    target = next(
        ((uid, u) for uid, u in directory.items() if (u.get("email") or "").lower() == TEST_RECIPIENT),
        None,
    )
    if not target:
        print(f"FAIL: {TEST_RECIPIENT} not found in auth users")
        sys.exit(1)
    target_id, target_user = target
    print(f"Found user {target_id} ({target_user['first_name']})")

    overdue = todo_repo.get_overdue_todos(db, today.isoformat())
    print(f"Total overdue todos: {len(overdue)}")
    mine = [t for t in overdue if any(str(a["id"]) == target_id for a in t.get("assignees", []))]
    print(f"Overdue todos assigned to {TEST_RECIPIENT}: {len(mine)}")

    if not mine:
        print("No real overdue tasks for this user; using a sample task for the send test.")
        mine = [{
            "id": "00000000-0000-0000-0000-000000000000",
            "title": "[TEST] Sample overdue task",
            "due_date": "2026-06-10",
        }]

    sender_tokens = email_repo.get_gmail_tokens_by_address(db, settings.notification_sender_email)
    if not sender_tokens:
        print(f"FAIL: sender {settings.notification_sender_email} has no Gmail tokens connected")
        sys.exit(1)
    print(f"Sender connected: {settings.notification_sender_email} (user {sender_tokens['user_id']})")

    subject, body = _build_email(target_user["first_name"], mine, today)
    print(f"\nSubject: {subject}\n\n{body}\n")

    result = email_service.send_direct_email(db, sender_tokens["user_id"], TEST_RECIPIENT, subject, body)
    print(f"SENT OK: {result}")


if __name__ == "__main__":
    main()
