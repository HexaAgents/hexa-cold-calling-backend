from __future__ import annotations

from datetime import date

from supabase import Client


def create_call_log(db: Client, data: dict) -> dict:
    result = db.table("call_logs").insert(data).execute()
    return result.data[0] if result.data else {}


def get_call_logs_for_contact(db: Client, contact_id: str) -> list[dict]:
    result = (
        db.table("call_logs")
        .select("*")
        .eq("contact_id", contact_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


def get_call_log(db: Client, call_id: str) -> dict | None:
    result = db.table("call_logs").select("*").eq("id", call_id).single().execute()
    return result.data


def get_latest_call_log_for_contact(db: Client, contact_id: str) -> dict | None:
    result = (
        db.table("call_logs")
        .select("*")
        .eq("contact_id", contact_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def count_call_logs_for_contact(db: Client, contact_id: str) -> int:
    result = (
        db.table("call_logs")
        .select("id", count="exact")
        .eq("contact_id", contact_id)
        .execute()
    )
    return result.count or 0


def delete_call_log(db: Client, call_id: str) -> bool:
    result = db.table("call_logs").delete().eq("id", call_id).execute()
    return bool(result.data)


def has_call_today(db: Client, contact_id: str) -> bool:
    today = date.today().isoformat()
    result = (
        db.table("call_logs")
        .select("id", count="exact")
        .eq("contact_id", contact_id)
        .eq("call_date", today)
        .execute()
    )
    return (result.count or 0) > 0
