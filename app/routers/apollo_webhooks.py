from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request

from app.dependencies import get_supabase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/apollo", tags=["apollo"])


TYPE_TO_FIELD: dict[str, str | None] = {
    "mobile": "mobile_phone",
    "work_direct": "work_direct_phone",
    "work": "work_direct_phone",
    "direct": "work_direct_phone",
    "corporate": "corporate_phone",
    "hq": "corporate_phone",
    "home": "mobile_phone",
    "other": None,
}

FALLBACK_ORDER = ("mobile_phone", "work_direct_phone", "corporate_phone")


def _set_status(db, contact_id: str, status: str) -> None:
    """Update enrichment_status, falling back to the pre-migration 'enriched' if the
    CHECK constraint rejects the new 'enrichment_no_phone' value.
    """
    try:
        db.table("contacts").update({"enrichment_status": status}).eq("id", contact_id).execute()
    except Exception as exc:
        msg = str(exc).lower()
        if status == "enrichment_no_phone" and ("check" in msg or "constraint" in msg or "enrichment_status_check" in msg):
            logger.warning(
                "Falling back to 'enriched' for contact %s (migration 012 not yet applied)",
                contact_id,
            )
            db.table("contacts").update({"enrichment_status": "enriched"}).eq("id", contact_id).execute()
        else:
            raise


def _classify_phones(phone_numbers: list[dict]) -> tuple[dict[str, str], list[str]]:
    """Map Apollo phone entries to our three DB columns.

    Returns (phones_dict, type_cds_seen). Explicit type_cd matches win first;
    unclassified/"other" numbers fill remaining slots in priority order.
    """
    phones: dict[str, str] = {}
    type_cds_seen: list[str] = []
    leftovers: list[str] = []

    for pn in phone_numbers:
        sanitized = pn.get("sanitized_number") or pn.get("raw_number") or ""
        if not sanitized:
            continue
        type_cd = (pn.get("type_cd") or "").lower()
        type_cds_seen.append(type_cd or "<empty>")

        field: str | None = None
        for key, mapped in TYPE_TO_FIELD.items():
            if key in type_cd:
                field = mapped
                break

        if field and field not in phones:
            phones[field] = sanitized
        else:
            leftovers.append(sanitized)

    for number in leftovers:
        for fallback in FALLBACK_ORDER:
            if fallback not in phones:
                phones[fallback] = number
                break

    return phones, type_cds_seen


@router.post("/webhook/phone")
async def receive_phone_webhook(request: Request, db=Depends(get_supabase)):
    """Receive async phone number data from Apollo enrichment."""
    try:
        payload = await request.json()
    except Exception:
        logger.warning("Apollo webhook: invalid/non-JSON payload")
        return {"status": "invalid payload"}

    people = payload.get("people") or []
    logger.info("Apollo webhook received: people=%d", len(people))
    if not people:
        return {"status": "no people in payload"}

    updated = 0
    no_phone_people = 0

    for person in people:
        apollo_id = person.get("id")
        if not apollo_id:
            logger.warning("Apollo webhook: person entry missing id, skipping")
            continue

        phone_numbers = person.get("phone_numbers") or []

        if not phone_numbers:
            logger.info(
                "Apollo webhook: apollo_id=%s returned no phone_numbers "
                "(likely out of phone credits or no mobile on file)",
                apollo_id,
            )
            no_phone_people += 1
            result = (
                db.table("contacts")
                .select("id")
                .eq("apollo_person_id", apollo_id)
                .execute()
            )
            for row in result.data or []:
                _set_status(db, row["id"], "enrichment_no_phone")
            continue

        phones, type_cds = _classify_phones(phone_numbers)
        logger.info(
            "Apollo webhook: apollo_id=%s phones=%d type_cds=%s mapped=%s",
            apollo_id,
            len(phone_numbers),
            type_cds,
            list(phones.keys()),
        )

        if not phones:
            no_phone_people += 1
            result = (
                db.table("contacts")
                .select("id")
                .eq("apollo_person_id", apollo_id)
                .execute()
            )
            for row in result.data or []:
                _set_status(db, row["id"], "enrichment_no_phone")
            continue

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

    logger.info(
        "Apollo webhook done: updated=%d no_phone=%d",
        updated,
        no_phone_people,
    )
    return {"status": "ok", "updated": updated, "no_phone": no_phone_people}
