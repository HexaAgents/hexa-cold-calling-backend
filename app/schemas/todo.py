from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class TodoAssignee(BaseModel):
    id: str
    first_name: str


class TodoCreate(BaseModel):
    title: str
    description: str | None = None
    assigned_to_id: str | None = None
    assigned_to_name: str | None = None
    assignees: list[TodoAssignee] | None = None
    due_date: str | None = None


class TodoUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    assigned_to_id: str | None = None
    assigned_to_name: str | None = None
    assignees: list[TodoAssignee] | None = None
    due_date: str | None = None
    is_done: bool | None = None
    # Distinguishes "unassign" (explicit null) from "leave unchanged" (omitted),
    # since assigned_to_id=None is also the value used to clear an assignee.
    unassign: bool = False


class TodoOut(BaseModel):
    id: str
    title: str
    description: str | None = None
    assigned_to_id: str | None = None
    assigned_to_name: str | None = None
    assignees: list[TodoAssignee] = []
    assigned_by_id: str
    assigned_by_name: str | None = None
    due_date: str | None = None
    is_done: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
