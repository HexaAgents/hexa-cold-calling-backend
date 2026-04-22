from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from app.dependencies import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/apollo", tags=["apollo"])


@router.post("/webhook/phone")
async def receive_phone_webhook(request: Request, db=Depends(get_supabase)):
    """Receive async phone number data from Apollo enrichment."""
    try:
        payload = await request.json()
    except Exception:
        return {"status": "invalid payload"}

    people = payload.get("people") or []
    if not people:
        return {"status": "no people in payload"}
    updated = 0

    for person in people:
        apollo_id = person.get("id")
        if not apollo_id:
            continue

        phone_numbers = person.get("phone_numbers") or []
        if not phone_numbers:
            result = (
                db.table("contacts")
                .select("id")
                .eq("apollo_person_id", apollo_id)
                .execute()
            )
            for row in result.data or []:
                db.table("contacts").update(
                    {"enrichment_status": "enriched"}
                ).eq("id", row["id"]).execute()
            continue

        phones: dict[str, str] = {}
        for pn in phone_numbers:
            sanitized = pn.get("sanitized_number") or pn.get("raw_number", "")
            if not sanitized:
                continue
            type_cd = pn.get("type_cd", "")
            if "mobile" in type_cd and "mobile_phone" not in phones:
                phones["mobile_phone"] = sanitized
            elif "work" in type_cd and "work_direct_phone" not in phones:
                phones["work_direct_phone"] = sanitized
            elif "mobile_phone" not in phones:
                phones["mobile_phone"] = sanitized
            elif "work_direct_phone" not in phones:
                phones["work_direct_phone"] = sanitized
            elif "corporate_phone" not in phones:
                phones["corporate_phone"] = sanitized

        update_data = {**phones, "enrichment_status": "enriched"}

        result = (
            db.table("contacts")
            .select("id")
            .eq("apollo_person_id", apollo_id)
            .execute()
        )
        for row in result.data or []:
            db.table("contacts").update(update_data).eq("id", row["id"]).execute()
            updated += 1

    return {"status": "ok", "updated": updated}
