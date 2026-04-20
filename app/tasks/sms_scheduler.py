from __future__ import annotations

import asyncio
import logging

from app.dependencies import get_supabase
from app.services import sms_service

logger = logging.getLogger(__name__)

POLL_INTERVAL_SECONDS = 60


async def run_sms_scheduler() -> None:
    """Background loop that checks for and sends due scheduled SMS messages."""
    logger.info("SMS scheduler started (polling every %ds)", POLL_INTERVAL_SECONDS)

    while True:
        try:
            db = get_supabase()
            sent = sms_service.process_scheduled_messages(db)
            if sent > 0:
                logger.info("Sent %d scheduled SMS messages", sent)
        except Exception as exc:
            logger.error("SMS scheduler error: %s", exc)

        await asyncio.sleep(POLL_INTERVAL_SECONDS)
