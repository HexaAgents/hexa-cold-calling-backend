from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from supabase import Client

from app.config import settings
from app.dependencies import get_supabase
from app.repositories import email_repo, settings_repo, todo_repo, user_repo
from app.services import email_service

logger = logging.getLogger(__name__)

# Overdue-ness and "end of day" are evaluated on the Pacific calendar, matching
# the productivity dashboard and the frontend's backlog logic.
DIGEST_TIMEZONE = ZoneInfo("America/Los_Angeles")
SEND_HOUR = 17  # 5:00 PM Pacific
POLL_INTERVAL_SECONDS = 300


def _format_task_line(todo: dict, today: date) -> str:
    title = todo.get("title") or "Untitled task"
    due_str = todo.get("due_date") or ""
    line = f"- {title}"
    try:
        due = date.fromisoformat(due_str)
        days_overdue = (today - due).days
        plural = "day" if days_overdue == 1 else "days"
        line += f" (due {due_str}, {days_overdue} {plural} overdue)"
    except ValueError:
        if due_str:
            line += f" (due {due_str})"
    task_url = f"{settings.frontend_url.rstrip('/')}/todo-list/{todo['id']}"
    line += f"\n  {task_url}"
    return line


def _build_email(first_name: str, todos: list[dict], today: date) -> tuple[str, str]:
    count = len(todos)
    plural = "task" if count == 1 else "tasks"
    subject = f"You have {count} overdue {plural}"
    lines = "\n\n".join(_format_task_line(t, today) for t in todos)
    body = (
        f"Hi {first_name},\n\n"
        f"You have {count} overdue {plural} in Hexa:\n\n"
        f"{lines}\n\n"
        f"Please update or complete them when you can.\n"
    )
    return subject, body


def send_overdue_digests(db: Client, today: date) -> int:
    """Email each user their overdue tasks. Returns the number of emails sent."""
    overdue = todo_repo.get_overdue_todos(db, today.isoformat())
    if not overdue:
        logger.info("Overdue digest: no overdue tasks, nothing to send")
        return 0

    by_user: dict[str, list[dict]] = {}
    for todo in overdue:
        for assignee in todo.get("assignees", []):
            by_user.setdefault(str(assignee["id"]), []).append(todo)
    if not by_user:
        logger.info("Overdue digest: overdue tasks exist but none are assigned")
        return 0

    try:
        directory = user_repo.get_auth_user_directory(db)
    except Exception as exc:
        logger.warning("Overdue digest: could not load users: %s", exc)
        return 0

    sender_tokens = email_repo.get_gmail_tokens_by_address(db, settings.notification_sender_email)
    if not sender_tokens:
        logger.warning(
            "Overdue digest: sender %s not connected; skipping",
            settings.notification_sender_email,
        )
        return 0
    sender_user_id = sender_tokens["user_id"]

    sent = 0
    for user_id, todos in by_user.items():
        user = directory.get(user_id, {})
        recipient = user.get("email")
        if not recipient:
            logger.warning("Overdue digest: no email for user %s, skipping", user_id)
            continue
        subject, body = _build_email(user.get("first_name") or "there", todos, today)
        try:
            email_service.send_direct_email(db, sender_user_id, recipient, subject, body)
            sent += 1
        except Exception as exc:
            logger.warning("Overdue digest email failed for %s: %s", recipient, exc)
    return sent


def run_digest_if_due(db: Client, now: datetime) -> bool:
    """Send the digest once per Pacific day at/after SEND_HOUR. Returns True if sent."""
    local_now = now.astimezone(DIGEST_TIMEZONE)
    if local_now.hour < SEND_HOUR:
        return False

    today = local_now.date()
    app_settings = settings_repo.get_settings(db)
    last_sent = app_settings.get("overdue_digest_last_sent")
    if last_sent and date.fromisoformat(str(last_sent)) >= today:
        return False

    # Claim the day BEFORE sending anything. If we cannot durably record that
    # today's digest is being handled (no settings row, or the bookkeeping
    # column is missing), we must NOT send — otherwise every poll would resend
    # and flood every recipient. Skipping one day's digest is the safe failure.
    settings_id = app_settings.get("id")
    if not settings_id:
        logger.error(
            "Overdue digest: no settings row to record send date; skipping to avoid a resend flood"
        )
        return False
    try:
        settings_repo.update_settings(db, settings_id, {"overdue_digest_last_sent": today.isoformat()})
    except Exception as exc:
        logger.error(
            "Overdue digest: could not record send date (%s); skipping to avoid a resend flood",
            exc,
        )
        return False

    # Trade-off: the day is now claimed. If all sends fail (e.g. Gmail is
    # disconnected), today's digest is skipped rather than retried — the safe
    # choice over flooding. Per-recipient failures are swallowed inside
    # send_overdue_digests, and a disconnected sender returns 0 early.
    sent = send_overdue_digests(db, today)
    logger.info("Overdue digest: sent %d emails for %s", sent, today.isoformat())
    return True


async def run_overdue_digest_scheduler() -> None:
    """Background loop: once a day at the end of the day (Pacific), email every
    user a digest of their overdue tasks."""
    logger.info(
        "Overdue digest scheduler started (sends daily at %d:00 %s)",
        SEND_HOUR,
        DIGEST_TIMEZONE.key,
    )
    while True:
        try:
            db = get_supabase()
            now = datetime.now(tz=DIGEST_TIMEZONE)
            # Blocking Supabase/Gmail HTTP calls; keep them off the event loop.
            await asyncio.to_thread(run_digest_if_due, db, now)
        except Exception as exc:
            logger.error("Overdue digest scheduler error: %s", exc)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
