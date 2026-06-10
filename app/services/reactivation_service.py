from __future__ import annotations

import logging

from supabase import Client

from app.services import apollo_service

logger = logging.getLogger(__name__)

REACTIVATE_MIN_OCCASIONS = 2
REACTIVATE_STALE_DAYS = 7


def reactivate_contacts(db: Client) -> list[str]:
    """Re-queue stale "didn't pick up" contacts into the shared calling pool.

    Calls the `reactivate_stale_didnt_pickup_contacts` RPC, which sets
    `retry_at = NOW()` and clears `assigned_to`/`assigned_at` on eligible
    contacts (didnt_pick_up, called on >= REACTIVATE_MIN_OCCASIONS occasions,
    last call > REACTIVATE_STALE_DAYS days ago) so any caller can claim them.

    Returns the ids of the reactivated contacts (DB-only, no enrichment).
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
    return [row["id"] for row in (res.data or []) if row.get("id")]


def reactivate_stale_didnt_pickup_contacts(db: Client) -> dict:
    """Reactivate stale "didn't pick up" contacts and re-enrich them on Apollo.

    The reactivated contacts are re-enriched so fresh phone numbers overwrite
    the old ones. Scoring is never invoked.
    """
    ids = reactivate_contacts(db)

    if not ids:
        return {"reactivated": 0, "enrichment": {"enriched": 0, "total": 0}}

    logger.info("Reactivated %d stale didnt_pick_up contacts; re-enriching", len(ids))
    enrichment = apollo_service.enrich_contacts(db, ids)
    return {"reactivated": len(ids), "enrichment": enrichment}
