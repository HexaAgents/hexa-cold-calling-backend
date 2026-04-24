from __future__ import annotations

from pydantic import BaseModel


class SettingsOut(BaseModel):
    id: str
    sms_call_threshold: int
    sms_template: str
    retry_days: int = 3
    email_template_didnt_pick_up: str = ""
    email_template_interested: str = ""
    email_subject_didnt_pick_up: str = "Following up"
    email_subject_interested: str = "Great chatting with you"


class SettingsUpdate(BaseModel):
    sms_call_threshold: int | None = None
    sms_template: str | None = None
    retry_days: int | None = None
    email_template_didnt_pick_up: str | None = None
    email_template_interested: str | None = None
    email_subject_didnt_pick_up: str | None = None
    email_subject_interested: str | None = None
