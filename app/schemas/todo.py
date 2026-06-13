from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

RecurrenceUnit = Literal["day", "week", "month"]


class TodoAssignee(BaseModel):
    id: str
    first_name: str


class DueDateEstimateRequest(BaseModel):
    """Title/description typed so far in the create dialog; nothing persisted."""

    title: str = Field(min_length=1)
    description: str | None = None


class DueDateEstimateResponse(BaseModel):
    due_date: str


def _validate_recurrence_pair(model: BaseModel) -> None:
    """Recurrence interval and unit must be set together (or cleared together)."""
    interval = getattr(model, "recurrence_interval", None)
    unit = getattr(model, "recurrence_unit", None)
    if (interval is None) != (unit is None):
        raise ValueError("recurrence_interval and recurrence_unit must be provided together")


class TodoCreate(BaseModel):
    title: str
    description: str | None = None
    assigned_to_id: str | None = None
    assigned_to_name: str | None = None
    assignees: list[TodoAssignee] | None = None
    due_date: str | None = None
    recurrence_interval: int | None = Field(default=None, ge=1, le=365)
    recurrence_unit: RecurrenceUnit | None = None

    @model_validator(mode="after")
    def _check_recurrence(self):
        _validate_recurrence_pair(self)
        return self


class TodoUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    assigned_to_id: str | None = None
    assigned_to_name: str | None = None
    assignees: list[TodoAssignee] | None = None
    due_date: str | None = None
    is_done: bool | None = None
    recurrence_interval: int | None = Field(default=None, ge=1, le=365)
    recurrence_unit: RecurrenceUnit | None = None
    # Distinguishes "unassign" (explicit null) from "leave unchanged" (omitted),
    # since assigned_to_id=None is also the value used to clear an assignee.
    unassign: bool = False

    @model_validator(mode="after")
    def _check_recurrence(self):
        # Partial updates may omit both fields; but if either is touched, the
        # pair must end up consistent (both set or both null).
        if "recurrence_interval" in self.model_fields_set or "recurrence_unit" in self.model_fields_set:
            _validate_recurrence_pair(self)
        return self


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
    recurrence_interval: int | None = None
    recurrence_unit: RecurrenceUnit | None = None
    recurrence_spawned: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
