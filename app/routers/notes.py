from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SupabaseDep, CurrentUserDep
from app.schemas.note import NoteCreate, NoteUpdate, NoteOut
from app.repositories import note_repo

router = APIRouter(tags=["notes"])


@router.get("/contacts/{contact_id}/notes", response_model=list[NoteOut])
def get_notes(contact_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    notes = note_repo.get_notes_for_contact(db, contact_id)
    return [NoteOut(**n) for n in notes]


@router.post("/contacts/{contact_id}/notes", response_model=NoteOut, status_code=201)
def create_note(
    contact_id: str,
    body: NoteCreate,
    current_user: CurrentUserDep,
    db: SupabaseDep,
):
    data = {
        "contact_id": contact_id,
        "user_id": current_user["id"],
        "content": body.content,
    }
    note = note_repo.create_note(db, data)
    return NoteOut(**note)


@router.patch("/notes/{note_id}", response_model=NoteOut)
def update_note(
    note_id: str,
    body: NoteUpdate,
    current_user: CurrentUserDep,
    db: SupabaseDep,
):
    updated = note_repo.update_note(db, note_id, {"content": body.content})
    if not updated:
        raise HTTPException(status_code=404, detail="Note not found")
    return NoteOut(**updated)


@router.delete("/notes/{note_id}")
def delete_note(note_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    deleted = note_repo.delete_note(db, note_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"detail": "Note deleted"}
