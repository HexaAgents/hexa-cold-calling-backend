from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dependencies import SupabaseDep, CurrentUserDep
from app.repositories import scheduled_call_repo

router = APIRouter(prefix="/calls", tags=["scheduled-calls"])


class ScheduleCallRequest(BaseModel):
    contact_id: str
    scheduled_at: str
    notes: str | None = None


@router.post("/schedule")
def schedule_call(body: ScheduleCallRequest, current_user: CurrentUserDep, db: SupabaseDep):
    """Schedule a follow-up call for an interested contact."""
    data = {
        "contact_id": body.contact_id,
        "user_id": current_user["id"],
        "scheduled_at": body.scheduled_at,
        "notes": body.notes,
        "status": "pending",
    }
    result = scheduled_call_repo.create_scheduled_call(db, data)
    return result


@router.get("/scheduled")
def list_scheduled_calls(current_user: CurrentUserDep, db: SupabaseDep, mine: bool = False):
    """Return pending scheduled calls, enriched with contact and user info."""
    user_filter = current_user["id"] if mine else None
    calls = scheduled_call_repo.get_scheduled_calls(db, user_id=user_filter)

    if not calls:
        return []

    contact_ids = list({c["contact_id"] for c in calls})
    contacts_result = (
        db.table("contacts")
        .select("id, first_name, last_name, company_name")
        .in_("id", contact_ids)
        .execute()
    )
    contact_map = {
        c["id"]: c for c in (contacts_result.data or [])
    }

    users_result = db.rpc("get_auth_users").execute()
    user_map: dict[str, str] = {}
    for u in (users_result.data or []):
        uid = str(u["id"])
        meta = u.get("raw_user_meta_data") or {}
        full_name = meta.get("full_name", u.get("email") or "Unknown")
        user_map[uid] = full_name

    enriched = []
    for c in calls:
        contact = contact_map.get(c["contact_id"], {})
        first = contact.get("first_name") or ""
        last = contact.get("last_name") or ""
        enriched.append({
            **c,
            "contact_name": f"{first} {last}".strip() or "Unknown",
            "company_name": contact.get("company_name", ""),
            "user_name": user_map.get(c["user_id"], "Unknown"),
        })
    return enriched


@router.post("/scheduled/{call_id}/complete")
def complete_scheduled_call(call_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    """Mark a scheduled call as completed."""
    existing = scheduled_call_repo.get_scheduled_call(db, call_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Scheduled call not found")
    scheduled_call_repo.update_scheduled_call(db, call_id, {"status": "completed"})
    return {"detail": "Marked as completed"}


@router.post("/scheduled/{call_id}/cancel")
def cancel_scheduled_call(call_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    """Cancel a scheduled call."""
    existing = scheduled_call_repo.get_scheduled_call(db, call_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Scheduled call not found")
    scheduled_call_repo.update_scheduled_call(db, call_id, {"status": "cancelled"})
    return {"detail": "Cancelled"}
