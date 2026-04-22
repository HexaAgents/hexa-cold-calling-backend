from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.dependencies import SupabaseDep, CurrentUserDep
from app.schemas.contact import ContactOut, ContactUpdate, ContactListOut
from app.services import contact_service

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=ContactListOut)
def list_contacts(
    current_user: CurrentUserDep,
    db: SupabaseDep,
    sort_by: str = Query("created_at"),
    sort_order: str = Query("asc"),
    outcome_filter: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
):
    contacts, total = contact_service.list_contacts(
        db,
        sort_by=sort_by,
        sort_order=sort_order,
        outcome_filter=outcome_filter,
        page=page,
        per_page=per_page,
    )
    return ContactListOut(
        contacts=[ContactOut(**c) for c in contacts],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/locations")
def get_locations(current_user: CurrentUserDep, db: SupabaseDep):
    """Return distinct non-empty location values for filter dropdowns."""
    locations: dict[str, list[str]] = {"cities": [], "states": [], "countries": []}
    for field, key in [("city", "cities"), ("state", "states"), ("country", "countries")]:
        result = db.table("contacts").select(field).not_.is_(field, "null").neq(field, "").execute()
        values = sorted({row[field] for row in (result.data or []) if row.get(field)})
        locations[key] = values
    return locations


@router.get("/{contact_id}", response_model=ContactOut)
def get_contact(contact_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    contact = contact_service.get_contact(db, contact_id)
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return ContactOut(**contact)


@router.patch("/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: str,
    body: ContactUpdate,
    current_user: CurrentUserDep,
    db: SupabaseDep,
):
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    updated = contact_service.update_contact(db, contact_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Contact not found")
    return ContactOut(**updated)


@router.delete("/{contact_id}")
def delete_contact(contact_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    deleted = contact_service.delete_contact(db, contact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Contact not found")
    return {"detail": "Contact deleted"}
