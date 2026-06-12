"""LLM time estimation for to-do tasks.

Produces an estimated hour range for a task using the same OpenAI client,
model, and JSON-mode call pattern as company scoring. The prompt is strictly
bounded: titles/descriptions are truncated and at most MAX_EXAMPLES recent
completed tasks (with reported actual hours) are included as calibration
examples, so a single estimation call can never grow unbounded in tokens.
"""

from __future__ import annotations

import json
import logging

from app.scoring.openai_scorer import _call_openai

logger = logging.getLogger(__name__)

# Hard bounds on prompt inputs (token-usage safeguards).
MAX_EXAMPLES = 10
MAX_TITLE_CHARS = 120
MAX_DESCRIPTION_CHARS = 500

# Hard bounds on the estimate itself.
MIN_HOURS = 0.25
MAX_HOURS = 200.0

ESTIMATE_SYSTEM_PROMPT = """You estimate how long work tasks will take for a small B2B cold-calling/sales-ops team.

Tasks are short to-do items: outreach prep, CSV imports, CRM cleanup, follow-up emails, research, small platform tweaks, admin work, etc.

Given a task title (and optional description), respond with a realistic range of focused working hours for one person.

Rules:
- Respond ONLY with JSON: {"hours_min": <number>, "hours_max": <number>}
- hours_min <= hours_max. Use decimals for sub-hour work (e.g. 0.5).
- Keep the range tight and practical (max is usually 1.5-3x min).
- Quick admin tasks are often 0.25-1h; substantial projects rarely exceed 40h.
- If calibration examples of past tasks with actual hours are provided, weigh them heavily - they reflect how long THIS team really takes.
"""


def _truncate(text: str | None, limit: int) -> str:
    return (text or "").strip()[:limit]


def format_calibration_examples(examples: list[dict]) -> str:
    """Render past (title, estimate, actual) rows into a bounded prompt block."""
    lines: list[str] = []
    for ex in examples[:MAX_EXAMPLES]:
        title = _truncate(ex.get("title"), MAX_TITLE_CHARS)
        actual = ex.get("actual_hours")
        if not title or actual is None:
            continue
        est_min = ex.get("estimated_hours_min")
        est_max = ex.get("estimated_hours_max")
        if est_min is not None and est_max is not None:
            lines.append(f'- "{title}" (estimated {est_min}-{est_max}h) actually took {actual}h')
        else:
            lines.append(f'- "{title}" actually took {actual}h')
    if not lines:
        return ""
    return "Past tasks completed by this team:\n" + "\n".join(lines)


def build_user_message(title: str, description: str | None, examples: list[dict]) -> str:
    parts = [f"Task: {_truncate(title, MAX_TITLE_CHARS)}"]
    desc = _truncate(description, MAX_DESCRIPTION_CHARS)
    if desc:
        parts.append(f"Description: {desc}")
    calibration = format_calibration_examples(examples)
    if calibration:
        parts.append(calibration)
    parts.append("How many focused working hours will this take?")
    return "\n\n".join(parts)


def _parse_hours(raw: str) -> tuple[float, float] | None:
    try:
        data = json.loads(raw)
        hours_min = float(data["hours_min"])
        hours_max = float(data["hours_max"])
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None

    hours_min = max(MIN_HOURS, min(MAX_HOURS, round(hours_min, 1)))
    hours_max = max(MIN_HOURS, min(MAX_HOURS, round(hours_max, 1)))
    if hours_max < hours_min:
        hours_min, hours_max = hours_max, hours_min
    return hours_min, hours_max


def estimate_todo_hours(
    api_key: str,
    title: str,
    description: str | None = None,
    examples: list[dict] | None = None,
    model: str = "gpt-4o-mini",
) -> dict | None:
    """Estimate a task's hour range. Returns {hours_min, hours_max} or None.

    Makes at most one OpenAI request (plus the client's single built-in
    retry). Any failure - API error, bad JSON, missing fields - returns None;
    the caller marks the estimate as terminally failed and never retries.
    """
    messages = [
        {"role": "system", "content": ESTIMATE_SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(title, description, examples or [])},
    ]

    raw = _call_openai(api_key, model, messages)
    if raw is None:
        return None

    parsed = _parse_hours(raw)
    if parsed is None:
        logger.warning("Todo estimate parse failed for title %r: %s", title[:50], raw[:200])
        return None

    return {"hours_min": parsed[0], "hours_max": parsed[1]}
