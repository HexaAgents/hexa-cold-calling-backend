from __future__ import annotations

from supabase import Client


def get_gmail_tokens(db: Client, user_id: str) -> dict | None:
    result = (
        db.table("user_gmail_tokens")
        .select("*")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    return result.data


def upsert_gmail_tokens(db: Client, user_id: str, data: dict) -> dict:
    payload = {"user_id": user_id, **data, "updated_at": "now()"}
    result = (
        db.table("user_gmail_tokens")
        .upsert(payload, on_conflict="user_id")
        .execute()
    )
    return result.data[0] if result.data else {}


def delete_gmail_tokens(db: Client, user_id: str) -> bool:
    result = (
        db.table("user_gmail_tokens")
        .delete()
        .eq("user_id", user_id)
        .execute()
    )
    return bool(result.data)


def create_email_log(db: Client, data: dict) -> dict:
    result = db.table("email_logs").insert(data).execute()
    return result.data[0] if result.data else {}


def get_email_logs_for_contact(db: Client, contact_id: str) -> list[dict]:
    result = (
        db.table("email_logs")
        .select("*")
        .eq("contact_id", contact_id)
        .order("sent_at", desc=True)
        .execute()
    )
    return result.data or []
