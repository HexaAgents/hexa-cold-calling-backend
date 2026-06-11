from __future__ import annotations

import logging

from supabase import Client

logger = logging.getLogger(__name__)

REACTIVATE_MIN_OCCASIONS = 2
REACTIVATE_STALE_DAYS = 7


def reactivate_contacts(db: Client) -> list[str]:
    """Re-queue stale "didn't pick up" contacts into the shared calling pool.

    Calls the `reactivate_stale_didnt_pickup_contacts` RPC, which sets
    `retry_at = NOW()` and clears `assigned_to`/`assigned_at` on eligible
    contacts (didnt_pick_up, called on >= REACTIVATE_MIN_OCCASIONS occasions,
    last call > REACTIVATE_STALE_DAYS days ago) so any caller can claim them.

    DB-only: contacts are never re-enriched or re-scored.

    Returns the ids of the reactivated contacts.
    """
    res = (
        db.rpc(
            "reactivate_stale_didnt_pickup_contacts",
            {
                "p_min_occasions": REACTIVATE_MIN_OCCASIONS,
                "p_stale_days": REACTIVATE_STALE_DAYS,
            },
        ).execute()
    )
    ids = [row["id"] for row in (res.data or []) if row.get("id")]
    if ids:
        logger.info("Reactivated %d stale didnt_pick_up contacts", len(ids))
    return ids
