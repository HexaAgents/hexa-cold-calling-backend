from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CompanyFlagCreate(BaseModel):
    company_name: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    details: str | None = None


class CompanyFlagOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    company_name: str
    reason: str
    details: str | None = None
    flagged_by: str | None = None
    flagged_by_name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
