from __future__ import annotations

from supabase import Client


def get_settings(db: Client) -> dict:
    result = db.table("settings").select("*").limit(1).single().execute()
    return result.data or {}


def update_settings(db: Client, settings_id: str, data: dict) -> dict | None:
    result = db.table("settings").update(data).eq("id", settings_id).execute()
    return result.data[0] if result.data else None
