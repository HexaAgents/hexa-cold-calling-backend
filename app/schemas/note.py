from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class NoteCreate(BaseModel):
    content: str


class NoteUpdate(BaseModel):
    content: str


class NoteOut(BaseModel):
    id: str
    contact_id: str
    user_id: str
    content: str
    note_date: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
