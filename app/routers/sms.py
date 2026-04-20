from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dependencies import SupabaseDep, CurrentUserDep
from app.services import sms_service

router = APIRouter(prefix="/sms", tags=["sms"])


class SendSMSRequest(BaseModel):
    contact_id: str


class ScheduleSMSRequest(BaseModel):
    contact_id: str
    scheduled_at: datetime


@router.post("/send")
def send_sms(body: SendSMSRequest, current_user: CurrentUserDep, db: SupabaseDep):
    try:
        result = sms_service.send_sms(db, body.contact_id)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"SMS send failed: {exc}")


@router.post("/schedule")
def schedule_sms(body: ScheduleSMSRequest, current_user: CurrentUserDep, db: SupabaseDep):
    try:
        result = sms_service.schedule_sms(db, body.contact_id, body.scheduled_at)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
