from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.dependencies import SupabaseDep, CurrentUserDep
from app.schemas.call import CallLogCreate, CallLogResponse, CallLogDeleteResponse, CallLogOut
from app.schemas.contact import ContactOut
from app.services import call_service
from app.repositories import call_log_repo

router = APIRouter(prefix="/calls", tags=["calls"])

CLAIM_EXPIRE_MINUTES = 60


@router.post("/token")
def get_twilio_token(current_user: CurrentUserDep):
    try:
        token = call_service.generate_twilio_token(current_user["id"])
        return {"token": token}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate token: {exc}")


@router.post("/next", response_model=ContactOut | None)
def claim_next_contact(
    current_user: CurrentUserDep,
    db: SupabaseDep,
    cities: list[str] | None = Query(None),
    states: list[str] | None = Query(None),
    countries: list[str] | None = Query(None),
    business_hours_only: bool = Query(False),
):
    """Claim the next available contact, optionally filtered by multiple locations.

    Uses Postgres SKIP LOCKED to guarantee no two users get the same contact.
    Contacts with blank/null location always pass through filters.
    When business_hours_only is true, only contacts whose local time is in
    8:00-11:59 or 14:00-17:59 are returned (plus contacts with unknown timezone).
    """
    result = db.rpc(
        "claim_next_contact",
        {
            "p_user_id": current_user["id"],
            "p_expire_minutes": CLAIM_EXPIRE_MINUTES,
            "p_cities": cities or None,
            "p_states": states or None,
            "p_countries": countries or None,
            "p_business_hours_only": business_hours_only,
        },
    ).execute()
    if not result.data:
        return None
    return ContactOut(**result.data[0])


@router.post("/release/{contact_id}")
def release_contact(contact_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    """Release a claimed contact back to the pool."""
    db.rpc(
        "release_contact",
        {"p_contact_id": contact_id, "p_user_id": current_user["id"]},
    ).execute()
    return {"detail": "Contact released"}


@router.get("/my-queue", response_model=list[ContactOut])
def get_my_queue(current_user: CurrentUserDep, db: SupabaseDep):
    """Return all contacts currently claimed by the current user."""
    result = (
        db.table("contacts")
        .select("*")
        .eq("assigned_to", current_user["id"])
        .is_("call_outcome", "null")
        .neq("company_type", "rejected")
        .or_("hidden.is.null,hidden.eq.false")
        .order("score", desc=True)
        .execute()
    )
    return [ContactOut(**c) for c in (result.data or [])]


@router.post("/log", response_model=CallLogResponse)
def log_call(body: CallLogCreate, current_user: CurrentUserDep, db: SupabaseDep):
    result = call_service.log_call(
        db=db,
        contact_id=body.contact_id,
        user_id=current_user["id"],
        call_method=body.call_method,
        phone_number_called=body.phone_number_called,
        outcome=body.outcome,
        callback_date=body.callback_date,
    )
    return CallLogResponse(
        call_log=CallLogOut(**result["call_log"]),
        sms_prompt_needed=result["sms_prompt_needed"],
        occasion_count=result["occasion_count"],
        times_called=result["times_called"],
        retry_at=result["retry_at"],
    )


@router.get("/contact/{contact_id}", response_model=list[CallLogOut])
def get_call_history(contact_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    logs = call_log_repo.get_call_logs_for_contact(db, contact_id)
    return [CallLogOut(**log) for log in logs]


@router.delete("/{call_id}", response_model=CallLogDeleteResponse)
def delete_call_log(call_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    result = call_service.delete_call_log(db, call_id)
    if not result.get("deleted"):
        raise HTTPException(status_code=404, detail="Call log not found")
    return CallLogDeleteResponse(
        contact_id=result["contact_id"],
        times_called=result["times_called"],
        call_outcome=result["call_outcome"],
    )
