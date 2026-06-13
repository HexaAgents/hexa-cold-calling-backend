from __future__ import annotations

from supabase import Client


def first_name(full_name: str | None, fallback: str = "") -> str:
    if not full_name:
        return fallback
    return full_name.split(" ")[0]


def get_auth_user_directory(db: Client) -> dict[str, dict]:
    """All platform users keyed by id, with email and first name resolved."""
    users_result = db.rpc("get_auth_users").execute()
    rows = users_result.data if isinstance(users_result.data, list) else []
    directory: dict[str, dict] = {}
    for u in rows:
        uid = str(u["id"])
        meta = u.get("raw_user_meta_data") or {}
        full_name = meta.get("full_name", u.get("email") or "Unknown")
        directory[uid] = {
            "email": u.get("email"),
            "first_name": first_name(full_name, "Unknown"),
        }
    return directory
