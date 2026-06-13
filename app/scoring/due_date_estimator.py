"""LLM due-date recommendation for to-do tasks.

One bounded OpenAI call per invocation: the create-task dialog's "Estimate
due date" button sends the typed title/description here, and the model
recommends a realistic calendar due date. Stateless — nothing is persisted
and failures simply return None so the user picks a date manually.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import date, timedelta

from openai import OpenAI

logger = logging.getLogger(__name__)

MAX_TITLE_CHARS = 120
MAX_DESCRIPTION_CHARS = 500
# Recommended dates are clamped to this window relative to today.
MIN_DAYS_AHEAD = 1
MAX_DAYS_AHEAD = 365

DUE_DATE_SYSTEM_PROMPT = """You recommend due dates for tasks on a small B2B cold-calling / sales-ops team.

Given a task title (and optional description) plus today's date, recommend a realistic due date:
- Small or urgent tasks (a call, an email, a quick fix): within 1-2 days.
- Typical tasks (prep work, follow-ups, small documents): within this week.
- Larger tasks (reports, campaigns, multi-step projects): one to a few weeks out.
- Prefer weekdays unless the task clearly implies otherwise.
- If the text mentions a specific date or timeframe, respect it.

Respond with strict JSON: {"due_date": "YYYY-MM-DD"}. No other keys, no prose."""


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def build_user_message(title: str, description: str | None, today: date) -> str:
    lines = [
        f"Today is {today.strftime('%A')}, {today.isoformat()}.",
        f"Task: {_truncate(title.strip(), MAX_TITLE_CHARS)}",
    ]
    if description and description.strip():
        lines.append(f"Description: {_truncate(description.strip(), MAX_DESCRIPTION_CHARS)}")
    lines.append("Recommend a due date.")
    return "\n".join(lines)


def _call_openai(api_key: str, model: str, messages: list[dict]) -> str | None:
    client = OpenAI(api_key=api_key, timeout=30.0)

    for attempt in range(2):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            return response.choices[0].message.content
        except Exception as exc:
            if attempt == 0:
                logger.warning("OpenAI due-date call failed (attempt 1), retrying in 2s: %s", exc)
                time.sleep(2)
            else:
                logger.error("OpenAI due-date call failed (attempt 2), giving up: %s", exc)

    return None


def _parse_due_date(raw: str, today: date) -> str | None:
    """Extract and clamp the recommended date; None when unusable."""
    try:
        data = json.loads(raw)
        recommended = date.fromisoformat(str(data["due_date"]))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        logger.warning("Unusable due-date response from OpenAI: %.200s", raw)
        return None

    earliest = today + timedelta(days=MIN_DAYS_AHEAD)
    latest = today + timedelta(days=MAX_DAYS_AHEAD)
    return min(max(recommended, earliest), latest).isoformat()


def estimate_due_date(
    api_key: str,
    title: str,
    description: str | None,
    today: date | None = None,
    model: str = "gpt-4o-mini",
) -> str | None:
    """Recommend a due date (YYYY-MM-DD) for a task, or None on any failure.

    Makes at most one OpenAI request (with one built-in retry). The result is
    clamped to tomorrow .. today+365 so a confused model can never produce a
    past or absurdly distant date.
    """
    today = today or date.today()
    messages = [
        {"role": "system", "content": DUE_DATE_SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(title, description, today)},
    ]

    raw = _call_openai(api_key, model, messages)
    if raw is None:
        return None
    return _parse_due_date(raw, today)
