"""Background generation of AI time estimates for to-do tasks.

Hard token-usage guarantees:
- An estimate is only ever generated for a todo whose estimate_status is
  exactly "pending" (set once at creation). Re-invoking this function for the
  same todo is a no-op, so duplicate background tasks cannot double-spend.
- Failures (missing API key, OpenAI error, unparseable output) set the
  terminal status "failed" and are never retried.
- Therefore each task costs at most one estimation call, ever.
"""

from __future__ import annotations

import logging

from supabase import Client

from app.config import settings
from app.repositories import todo_repo
from app.scoring import todo_estimator

logger = logging.getLogger(__name__)


def generate_estimate(db: Client, todo_id: str) -> None:
    """Estimate one pending todo's hour range. Never raises, never retries."""
    try:
        todo = todo_repo.get_todo(db, todo_id)
        if not todo or todo.get("estimate_status") != "pending":
            return

        if not settings.openai_api_key:
            logger.warning("OPENAI_API_KEY not set; marking todo %s estimate failed", todo_id)
            todo_repo.set_estimate(db, todo_id, {"estimate_status": "failed"})
            return

        examples = todo_repo.get_calibration_examples(db)
        result = todo_estimator.estimate_todo_hours(
            api_key=settings.openai_api_key,
            title=todo.get("title") or "",
            description=todo.get("description"),
            examples=examples,
            model=settings.openai_model,
        )

        if result is None:
            todo_repo.set_estimate(db, todo_id, {"estimate_status": "failed"})
            return

        todo_repo.set_estimate(
            db,
            todo_id,
            {
                "estimated_hours_min": result["hours_min"],
                "estimated_hours_max": result["hours_max"],
                "estimate_status": "done",
            },
        )
        logger.info(
            "Estimated todo %s at %s-%sh", todo_id, result["hours_min"], result["hours_max"]
        )
    except Exception as exc:
        logger.error("Todo estimate generation failed for %s: %s", todo_id, exc)
        try:
            todo_repo.set_estimate(db, todo_id, {"estimate_status": "failed"})
        except Exception:
            logger.exception("Could not mark todo %s estimate as failed", todo_id)
