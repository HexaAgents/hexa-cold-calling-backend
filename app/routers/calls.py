from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SupabaseDep, CurrentUserDep
from app.schemas.call import CallLogCreate, CallLogResponse, CallLogOut
from app.services import call_service
from app.repositories import call_log_repo

router = APIRouter(prefix="/calls", tags=["calls"])


@router.post("/token")
def get_twilio_token(current_user: CurrentUserDep):
    try:
        token = call_service.generate_twilio_token(current_user["id"])
        return {"token": token}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate token: {exc}")


@router.post("/log", response_model=CallLogResponse)
def log_call(body: CallLogCreate, current_user: CurrentUserDep, db: SupabaseDep):
    result = call_service.log_call(
        db=db,
        contact_id=body.contact_id,
        user_id=current_user["id"],
        call_method=body.call_method,
        phone_number_called=body.phone_number_called,
        outcome=body.outcome,
    )
    return CallLogResponse(
        call_log=CallLogOut(**result["call_log"]),
        sms_prompt_needed=result["sms_prompt_needed"],
        occasion_count=result["occasion_count"],
    )


@router.get("/contact/{contact_id}", response_model=list[CallLogOut])
def get_call_history(contact_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    logs = call_log_repo.get_call_logs_for_contact(db, contact_id)
    return [CallLogOut(**log) for log in logs]
