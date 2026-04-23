from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class ContactOut(BaseModel):
    id: str
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    company_name: str
    person_linkedin_url: str | None = None
    website: str | None = None
    company_linkedin_url: str | None = None
    employees: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None
    timezone: str | None = None
    email: str | None = None
    mobile_phone: str | None = None
    work_direct_phone: str | None = None
    corporate_phone: str | None = None
    score: int | None = None
    company_type: str | None = None
    rationale: str | None = None
    rejection_reason: str | None = None
    company_description: str | None = None
    exa_scrape_success: bool = False
    scoring_failed: bool = False
    call_occasion_count: int = 0
    times_called: int = 0
    call_outcome: str | None = None
    messaging_status: str | None = None
    sms_sent: bool = False
    sms_sent_after_calls: int | None = None
    sms_scheduled_at: datetime | None = None
    enrichment_status: str | None = None
    apollo_person_id: str | None = None
    assigned_to: str | None = None
    assigned_at: datetime | None = None
    retry_at: datetime | None = None
    created_at: datetime | None = None


class ContactUpdate(BaseModel):
    call_outcome: str | None = None
    messaging_status: str | None = None


class ContactListParams(BaseModel):
    sort_by: str = "created_at"
    sort_order: str = "asc"
    outcome_filter: str | None = None
    page: int = 1
    per_page: int = 50


class ContactListOut(BaseModel):
    contacts: list[ContactOut]
    total: int
    page: int
    per_page: int
