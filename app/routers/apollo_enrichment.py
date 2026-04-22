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


@router.get("/enrich/status")
def enrichment_status(current_user: CurrentUserDep, db: SupabaseDep):
    counts: dict[str, int] = {}
    for status in ("pending_enrichment", "enriching", "enriched", "enrichment_failed"):
        result = (
            db.table("contacts")
            .select("id", count="exact")
            .eq("enrichment_status", status)
            .execute()
        )
        counts[status] = result.count or 0
    return counts
