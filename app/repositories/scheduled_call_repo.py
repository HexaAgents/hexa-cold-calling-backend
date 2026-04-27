from __future__ import annotations

from supabase import Client


def create_scheduled_call(db: Client, data: dict) -> dict:
    result = db.table("scheduled_calls").insert(data).execute()
    return result.data[0] if result.data else {}


def get_scheduled_calls(db: Client, user_id: str | None = None) -> list[dict]:
    """Return pending scheduled calls, optionally filtered by user."""
    query = (
        db.table("scheduled_calls")
        .select("*")
        .eq("status", "pending")
        .order("scheduled_at", desc=False)
    )
    if user_id:
        query = query.eq("user_id", user_id)
    result = query.execute()
    return result.data or []


def get_scheduled_call(db: Client, call_id: str) -> dict | None:
    result = (
        db.table("scheduled_calls")
        .select("*")
        .eq("id", call_id)
        .maybe_single()
        .execute()
    )
    return result.data


def update_scheduled_call(db: Client, call_id: str, data: dict) -> dict | None:
    result = (
        db.table("scheduled_calls")
        .update(data)
        .eq("id", call_id)
        .execute()
    )
    return result.data[0] if result.data else None
