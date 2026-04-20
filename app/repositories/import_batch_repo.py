from __future__ import annotations

from supabase import Client


def create_batch(db: Client, data: dict) -> dict:
    result = db.table("import_batches").insert(data).execute()
    return result.data[0] if result.data else {}


def update_batch(db: Client, batch_id: str, data: dict) -> dict | None:
    result = db.table("import_batches").update(data).eq("id", batch_id).execute()
    return result.data[0] if result.data else None


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
