from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from app.dependencies import SupabaseDep, CurrentUserDep
from app.services import apollo_service

router = APIRouter(prefix="/apollo", tags=["apollo"])


class EnrichRequest(BaseModel):
    contact_ids: list[str] | None = None
    enrich_all: bool = False


@router.post("/enrich")
def trigger_enrichment(
    body: EnrichRequest,
    current_user: CurrentUserDep,
    db: SupabaseDep,
    background_tasks: BackgroundTasks,
):
    if not body.enrich_all and not body.contact_ids:
        raise HTTPException(status_code=400, detail="Provide contact_ids or set enrich_all=true")

    ids = body.contact_ids if not body.enrich_all else None
    background_tasks.add_task(apollo_service.enrich_contacts, db, ids)
    return {"status": "enrichment_started"}


@router.post("/enrich/backfill")
def backfill_missing_mobiles(
    current_user: CurrentUserDep,
    db: SupabaseDep,
    background_tasks: BackgroundTasks,
):
    """Reset stale contacts that never received a mobile phone and re-run Apollo enrichment.

    Targets contacts where mobile_phone IS NULL and enrichment_status is in a terminal
    or stuck state (enriched / enriching / enrichment_failed / enrichment_no_phone).
    Flips them back to pending_enrichment so enrich_contacts picks them up.
    """
    stale_statuses = [
        "enriched",
        "enriching",
        "enrichment_failed",
        "enrichment_no_phone",
    ]
    result = (
        db.table("contacts")
        .update({"enrichment_status": "pending_enrichment"})
        .is_("mobile_phone", "null")
        .in_("enrichment_status", stale_statuses)
        .execute()
    )
    reset_count = len(result.data or [])
    background_tasks.add_task(apollo_service.enrich_contacts, db, None)
    return {"status": "backfill_started", "reset": reset_count}


@router.post("/enrich/retry-stale")
def retry_stale_enrichments(
    current_user: CurrentUserDep,
    db: SupabaseDep,
    background_tasks: BackgroundTasks,
    clear_no_credits: bool = True,
):
    """Manually trigger the auto-recovery sweep.

    With clear_no_credits=True (default - used by the 'Retry' button on the
    import page) we also reset contacts marked 'apollo_no_credits', which
    signals the user has topped up their Apollo account.
    """
    background_tasks.add_task(
        apollo_service.sweep_stuck_enrichments, db, clear_no_credits
    )
    return {"status": "sweep_started", "clear_no_credits": clear_no_credits}


@router.get("/enrich/status")
def enrichment_status(current_user: CurrentUserDep, db: SupabaseDep):
    """Return a full health summary used by the import page banner."""
    return apollo_service.get_enrichment_health(db)


@router.post("/enrich/debug")
def debug_apollo_call(
    body: EnrichRequest,
    current_user: CurrentUserDep,
    db: SupabaseDep,
):
    """TEMPORARY debug: synchronously call Apollo with one contact_id and return the raw response.

    Used to diagnose why contacts are being marked enrichment_failed in prod.
    Remove after diagnosis is complete.
    """
    import httpx
    from app.config import settings
    if not body.contact_ids:
        raise HTTPException(status_code=400, detail="contact_ids required")

    result = (
        db.table("contacts")
        .select("*")
        .in_("id", body.contact_ids[:1])
        .execute()
    )
    if not result.data:
        return {"error": "contact not found"}
    c = result.data[0]

    detail = {}
    if c.get("first_name"): detail["first_name"] = c["first_name"]
    if c.get("last_name"): detail["last_name"] = c["last_name"]
    if c.get("email"): detail["email"] = c["email"]
    if c.get("person_linkedin_url"): detail["linkedin_url"] = c["person_linkedin_url"]
    if c.get("company_name"): detail["organization_name"] = c["company_name"]

    webhook_url = f"{settings.backend_public_url.rstrip('/')}/apollo/webhook/phone"

    try:
        r = httpx.post(
            "https://api.apollo.io/api/v1/people/bulk_match",
            headers={
                "x-api-key": settings.apollo_api_key,
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
            },
            json={
                "details": [detail],
                "reveal_phone_number": True,
                "webhook_url": webhook_url,
            },
            timeout=30.0,
        )
        return {
            "apollo_status": r.status_code,
            "apollo_body": r.text[:2000],
            "request_detail": detail,
            "apollo_api_key_present": bool(settings.apollo_api_key),
            "webhook_url": webhook_url,
        }
    except Exception as exc:
        return {"error": str(exc)[:500]}
