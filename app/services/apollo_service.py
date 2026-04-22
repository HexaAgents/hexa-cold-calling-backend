from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

import httpx

from supabase import Client

from app.config import settings
from app.repositories import contact_repo

logger = logging.getLogger(__name__)

APOLLO_BULK_URL = "https://api.apollo.io/api/v1/people/bulk_match"
BATCH_SIZE = 10
BATCH_DELAY = 1.0


def _extract_domain(website: str) -> str:
    if not website:
        return ""
    parsed = urlparse(website if "://" in website else f"https://{website}")
    host = parsed.hostname or ""
    return host.removeprefix("www.")


def enrich_contacts(db: Client, contact_ids: list[str] | None = None) -> dict:
    """Enrich contacts via Apollo Bulk People Enrichment API.

    If contact_ids is None, enrich all contacts with enrichment_status='pending_enrichment'.
    Returns summary counts.
    """
    if not settings.apollo_api_key or not settings.backend_public_url:
        return {"error": "Apollo API key or backend URL not configured"}

    if contact_ids:
        result = (
            db.table("contacts")
            .select("*")
            .in_("id", contact_ids)
            .execute()
        )
        contacts = result.data or []
    else:
        result = (
            db.table("contacts")
            .select("*")
            .eq("enrichment_status", "pending_enrichment")
            .execute()
        )
        contacts = result.data or []

    if not contacts:
        return {"enriched": 0, "total": 0}

    webhook_url = f"{settings.backend_public_url.rstrip('/')}/apollo/webhook/phone"
    total_sent = 0

    for i in range(0, len(contacts), BATCH_SIZE):
        batch = contacts[i : i + BATCH_SIZE]
        details = []
        for c in batch:
            detail: dict = {}
            if c.get("first_name"):
                detail["first_name"] = c["first_name"]
            if c.get("last_name"):
                detail["last_name"] = c["last_name"]
            if c.get("email"):
                detail["email"] = c["email"]
            if c.get("person_linkedin_url"):
                detail["linkedin_url"] = c["person_linkedin_url"]
            if c.get("company_name"):
                detail["organization_name"] = c["company_name"]
            domain = _extract_domain(c.get("website", ""))
            if domain:
                detail["domain"] = domain
            details.append(detail)

        try:
            resp = httpx.post(
                APOLLO_BULK_URL,
                headers={
                    "x-api-key": settings.apollo_api_key,
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                },
                json={
                    "details": details,
                    "reveal_phone_number": True,
                    "webhook_url": webhook_url,
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

            matches = data.get("matches") or []
            for idx, match in enumerate(matches):
                if idx >= len(batch):
                    break
                contact_id = batch[idx]["id"]
                person_id = None
                if match and isinstance(match, dict):
                    person_id = match.get("id")

                update = {"enrichment_status": "enriching"}
                if person_id:
                    update["apollo_person_id"] = person_id
                contact_repo.update_contact(db, contact_id, update)
                total_sent += 1

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                logger.warning("Apollo credit/rate limit hit, stopping enrichment")
                return {"enriched": total_sent, "total": len(contacts), "no_credits": True}
            logger.error("Apollo HTTP error for batch %d: %s", i, exc)
            for c in batch:
                contact_repo.update_contact(
                    db, c["id"], {"enrichment_status": "enrichment_failed"}
                )
        except Exception as exc:
            logger.error("Apollo enrichment error for batch %d: %s", i, exc)
            for c in batch:
                contact_repo.update_contact(
                    db, c["id"], {"enrichment_status": "enrichment_failed"}
                )

        if i + BATCH_SIZE < len(contacts):
            time.sleep(BATCH_DELAY)

    return {"enriched": total_sent, "total": len(contacts), "no_credits": False}
