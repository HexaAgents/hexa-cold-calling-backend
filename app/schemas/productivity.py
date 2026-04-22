from __future__ import annotations

from pydantic import BaseModel


class ProductivityUser(BaseModel):
    id: str
    first_name: str


class ProductivityRow(BaseModel):
    date: str
    counts: dict[str, int]


class ProductivityResponse(BaseModel):
    users: list[ProductivityUser]
    rows: list[ProductivityRow]
