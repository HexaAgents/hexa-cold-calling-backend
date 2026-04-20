from __future__ import annotations

from supabase import Client

from app.repositories import contact_repo


def list_contacts(
    db: Client,
    sort_by: str = "created_at",
    sort_order: str = "asc",
    outcome_filter: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict], int]:
    return contact_repo.list_contacts(
        db,
        sort_by=sort_by,
        sort_order=sort_order,
        outcome_filter=outcome_filter,
        page=page,
        per_page=per_page,
    )


def get_contact(db: Client, contact_id: str) -> dict | None:
    return contact_repo.get_contact(db, contact_id)


def update_contact(db: Client, contact_id: str, data: dict) -> dict | None:
    return contact_repo.update_contact(db, contact_id, data)


def delete_contact(db: Client, contact_id: str) -> bool:
    return contact_repo.delete_contact(db, contact_id)
