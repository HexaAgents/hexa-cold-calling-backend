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


class HourBucket(BaseModel):
    hour: int
    total: int
    pickups: int
    interested: int
    pickup_rate: float
    interested_rate: float


class HeatCell(BaseModel):
    weekday: int
    hour: int
    total: int
    pickups: int
    pickup_rate: float


class BestWindow(BaseModel):
    weekday: int
    hour: int
    total: int
    pickup_rate: float


class BestCallTimesResponse(BaseModel):
    timezone: str
    min_sample: int
    total_calls: int
    overall_pickup_rate: float
    hours: list[HourBucket]
    heatmap: list[HeatCell]
    best_hour: HourBucket | None
    best_window: BestWindow | None
