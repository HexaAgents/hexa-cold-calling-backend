from __future__ import annotations

from pydantic import BaseModel


class SettingsOut(BaseModel):
    id: str
    sms_call_threshold: int
    sms_template: str
    retry_days: int = 3


class SettingsUpdate(BaseModel):
    sms_call_threshold: int | None = None
    sms_template: str | None = None
    retry_days: int | None = None
