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


