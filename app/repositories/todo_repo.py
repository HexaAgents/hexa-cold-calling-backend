from __future__ import annotations

from supabase import Client


def get_todos(db: Client) -> list[dict]:
    # Closest due dates first; tasks without a due date sort to the bottom.
    result = (
        db.table("todos")
        .select("*")
        .order("due_date", desc=False, nullsfirst=False)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


def get_todo(db: Client, todo_id: str) -> dict | None:
    result = db.table("todos").select("*").eq("id", todo_id).execute()
    return result.data[0] if result.data else None


def create_todo(db: Client, data: dict) -> dict:
    result = db.table("todos").insert(data).execute()
    return result.data[0] if result.data else {}


def update_todo(db: Client, todo_id: str, data: dict) -> dict | None:
    result = db.table("todos").update(data).eq("id", todo_id).execute()
    return result.data[0] if result.data else None


def delete_todo(db: Client, todo_id: str) -> bool:
    result = db.table("todos").delete().eq("id", todo_id).execute()
    return bool(result.data)
