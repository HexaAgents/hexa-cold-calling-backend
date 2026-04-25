from __future__ import annotations

from pydantic import BaseModel


class ProductivityUser(BaseModel):
    id: str
    first_name: str


class ProductivityRow(BaseModel):
    date: str
    counts: dict[str, int]


class OutcomeBreakdown(BaseModel):
    total: int
    didnt_pick_up: int
    interested: int
    not_interested: int
    bad_number: int
    other: int


class UserOutcomeBreakdown(BaseModel):
    user_id: str
    first_name: str
    breakdown: OutcomeBreakdown


class ProductivityResponse(BaseModel):
    users: list[ProductivityUser]
    rows: list[ProductivityRow]
    overall_breakdown: OutcomeBreakdown
    per_user_breakdown: list[UserOutcomeBreakdown]
