from __future__ import annotations

from supabase import Client


def get_notes_for_contact(db: Client, contact_id: str) -> list[dict]:
    result = (
        db.table("notes")
        .select("*")
        .eq("contact_id", contact_id)
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []


def create_note(db: Client, data: dict) -> dict:
    result = db.table("notes").insert(data).execute()
    return result.data[0] if result.data else {}


def update_note(db: Client, note_id: str, data: dict) -> dict | None:
    result = db.table("notes").update(data).eq("id", note_id).execute()
    return result.data[0] if result.data else None


def delete_note(db: Client, note_id: str) -> bool:
    result = db.table("notes").delete().eq("id", note_id).execute()
    return bool(result.data)
