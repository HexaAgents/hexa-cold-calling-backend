from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from supabase import Client

logger = logging.getLogger(__name__)

STALE_THRESHOLD_MINUTES = 10

# Lightweight column list used by list/get queries. We deliberately omit
# `filtered_csv` (potentially several MB) and instead surface a boolean via
# `_with_csv_flag` so the API can advertise downloadability without
# shipping the file payload on every poll.
_LIGHT_COLUMNS = (
    "id, user_id, filename, total_rows, processed_rows, stored_rows, "
    "discarded_rows, enriched_rows, enrichment_error, status, created_at, "
    "updated_at"
)


def _with_csv_flag(db: Client, batch: dict | None) -> dict | None:
    if not batch:
        return batch
    batch["has_filtered_csv"] = _csv_present(db, batch["id"])
    return batch


def _attach_csv_flags(db: Client, batches: list[dict]) -> list[dict]:
    if not batches:
        return batches
    ids = [b["id"] for b in batches]
    result = (
        db.table("import_batches")
        .select("id, filtered_csv")
        .in_("id", ids)
        .execute()
    )
    presence = {r["id"]: bool(r.get("filtered_csv")) for r in (result.data or [])}
    for b in batches:
        b["has_filtered_csv"] = presence.get(b["id"], False)
    return batches


def _csv_present(db: Client, batch_id: str) -> bool:
    result = (
        db.table("import_batches")
        .select("filtered_csv")
        .eq("id", batch_id)
        .single()
        .execute()
    )
    return bool((result.data or {}).get("filtered_csv"))


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
    result = (
        db.table("import_batches")
        .select(_LIGHT_COLUMNS)
        .eq("id", batch_id)
        .single()
        .execute()
    )
    return _with_csv_flag(db, result.data)


def get_recent_batches(db: Client, limit: int = 10) -> list[dict]:
    result = (
        db.table("import_batches")
        .select(_LIGHT_COLUMNS)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return _attach_csv_flags(db, result.data or [])


def get_filtered_csv(db: Client, batch_id: str) -> tuple[str, str] | None:
    """Return (csv_text, original_filename) for a batch, or None if no CSV
    has been stored yet (e.g. processing failed before the writeback)."""
    result = (
        db.table("import_batches")
        .select("filtered_csv, filename")
        .eq("id", batch_id)
        .single()
        .execute()
    )
    row = result.data
    if not row:
        return None
    csv_text = row.get("filtered_csv")
    if not csv_text:
        return None
    return csv_text, row.get("filename") or "filtered.csv"


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
