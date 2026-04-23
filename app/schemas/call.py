from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class CallLogCreate(BaseModel):
    contact_id: str
    call_method: str
    phone_number_called: str | None = None
    outcome: str
    callback_date: str | None = None


class CallLogOut(BaseModel):
    id: str
    contact_id: str
    user_id: str
    call_date: str
    call_method: str
    phone_number_called: str | None = None
    outcome: str | None = None
    is_new_occasion: bool = False
    created_at: datetime | None = None


class CallLogResponse(BaseModel):
    call_log: CallLogOut
    sms_prompt_needed: bool = False
    occasion_count: int = 0
    times_called: int = 0
    retry_at: str | None = None
