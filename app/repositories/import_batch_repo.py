from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from supabase import Client

logger = logging.getLogger(__name__)

STALE_THRESHOLD_MINUTES = 10


def create_batch(db: Client, data: dict) -> dict:
    result = db.table("import_batches").insert(data).execute()
    return result.data[0] if result.data else {}


def update_batch(db: Client, batch_id: str, data: dict) -> dict | None:
    result = db.table("import_batches").update(data).eq("id", batch_id).execute()
    return result.data[0] if result.data else None


def delete_batch(db: Client, batch_id: str) -> bool:
    result = db.table("import_batches").delete().eq("id", batch_id).execute()
    return bool(result.data)


def get_batch(db: Client, batch_id: str) -> dict | None:
    result = db.table("import_batches").select("*").eq("id", batch_id).single().execute()
    return result.data


def get_recent_batches(db: Client, limit: int = 10) -> list[dict]:
    result = (
        db.table("import_batches")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def is_stale(batch: dict, stale_minutes: int = STALE_THRESHOLD_MINUTES) -> bool:
    """Return True if a batch is stuck in 'processing' with no recent update."""
    if batch.get("status") != "processing":
        return False
    timestamp = batch.get("updated_at") or batch.get("created_at")
    if not timestamp:
        return False
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    return timestamp < cutoff


def recover_stale_imports(db: Client, stale_minutes: int = STALE_THRESHOLD_MINUTES) -> list[str]:
    """Find batches stuck in 'processing' and mark them failed. Returns recovered IDs."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_minutes)
    cutoff_iso = cutoff.isoformat()

    result = (
        db.table("import_batches")
        .select("id")
        .eq("status", "processing")
        .lt("updated_at", cutoff_iso)
        .execute()
    )
    stale_batches = result.data or []

    recovered_ids: list[str] = []
    for batch in stale_batches:
        batch_id = batch["id"]
        update_batch(db, batch_id, {"status": "failed"})
        recovered_ids.append(batch_id)

    if recovered_ids:
        logger.warning("Recovered %d stale import(s): %s", len(recovered_ids), recovered_ids)

    return recovered_ids
