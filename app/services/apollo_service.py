from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx

from supabase import Client

from app.config import settings
from app.repositories import contact_repo

logger = logging.getLogger(__name__)

APOLLO_BULK_URL = "https://api.apollo.io/api/v1/people/bulk_match"
BATCH_SIZE = 10
BATCH_DELAY = 1.0

STALE_ENRICHING_MINUTES = 30
MAX_RETRY_ATTEMPTS = 3
ERROR_NO_CREDITS = "apollo_no_credits"

# Columns added by migration 013. Code must tolerate them missing so we can
# deploy before the migration has been applied.
_RETRY_COLUMNS = (
    "enrichment_attempts",
    "enrichment_last_attempt_at",
    "last_enrichment_error",
)
# Status added by migration 012 (loosened CHECK constraint).
_NEW_STATUS = "enrichment_no_phone"


def _strip_unknown(update: dict, error: Exception) -> dict | None:
    """If Supabase/PostgREST rejected the update because a column is unknown,
    return the update without the known-new retry columns. Returns None if
    the error is not a missing-column error.
    """
    msg = str(error)
    if "PGRST204" not in msg and "schema cache" not in msg:
        return None
    cleaned = {k: v for k, v in update.items() if k not in _RETRY_COLUMNS}
    return cleaned if cleaned != update else None


def _safe_update(db: Client, contact_id: str, update: dict) -> None:
    """Update a contact, falling back to pre-migration schema on column-missing errors."""
    try:
        contact_repo.update_contact(db, contact_id, update)
        return
    except Exception as exc:
        cleaned = _strip_unknown(update, exc)
        if cleaned is None:
            logger.error("update_contact failed for %s: %s", contact_id, exc)
            return
        try:
            contact_repo.update_contact(db, contact_id, cleaned)
        except Exception as exc2:
            logger.error("fallback update_contact failed for %s: %s", contact_id, exc2)


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
    missing = []
    if not settings.apollo_api_key:
        missing.append("APOLLO_API_KEY")
    if not settings.backend_public_url:
        missing.append("BACKEND_PUBLIC_URL")
    if missing:
        logger.warning(
            "Apollo enrichment skipped: missing env var(s) %s. "
            "Set them in .env (local) or GitHub secrets/vars (prod). "
            "BACKEND_PUBLIC_URL must be a public https URL reachable by Apollo "
            "(use ngrok in local dev).",
            ", ".join(missing),
        )
        return {"error": f"Missing config: {', '.join(missing)}"}

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
    logger.info(
        "Starting Apollo enrichment: %d contacts, webhook_url=%s",
        len(contacts),
        webhook_url,
    )

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
            matched_ids = sum(1 for m in matches if isinstance(m, dict) and m.get("id"))
            logger.info(
                "Apollo batch %d: sent=%d, status=%d, matches=%d, with_person_id=%d",
                i // BATCH_SIZE,
                len(batch),
                resp.status_code,
                len(matches),
                matched_ids,
            )
            now_iso = datetime.now(timezone.utc).isoformat()
            for idx, match in enumerate(matches):
                if idx >= len(batch):
                    break
                contact_id = batch[idx]["id"]
                person_id = None
                if match and isinstance(match, dict):
                    person_id = match.get("id")

                update: dict = {
                    "enrichment_status": "enriching",
                    "enrichment_attempts": (batch[idx].get("enrichment_attempts") or 0) + 1,
                    "enrichment_last_attempt_at": now_iso,
                    "last_enrichment_error": None,
                }
                if person_id:
                    update["apollo_person_id"] = person_id
                _safe_update(db, contact_id, update)
                total_sent += 1

        except httpx.HTTPStatusError as exc:
            body = ""
            try:
                body = exc.response.text[:500]
            except Exception:
                pass
            now_iso = datetime.now(timezone.utc).isoformat()
            # Apollo signals credit exhaustion two ways:
            #   - 429 (rate limit / hard credit limit)
            #   - 422 with body containing "insufficient credits" (what we actually see in prod)
            body_lower = body.lower()
            out_of_credits = exc.response.status_code == 429 or (
                exc.response.status_code == 422
                and ("insufficient credits" in body_lower or "upgrade your plan" in body_lower)
            )
            if out_of_credits:
                logger.warning(
                    "Apollo credits exhausted (status=%d), stopping enrichment. Body: %s",
                    exc.response.status_code,
                    body,
                )
                # Mark already-attempted contacts (and remaining in batch) with
                # apollo_no_credits so the auto-sweep skips them until the user
                # tops up and clicks Retry on the import page.
                for c in batch:
                    _safe_update(
                        db,
                        c["id"],
                        {
                            "enrichment_status": "enrichment_failed",
                            "last_enrichment_error": ERROR_NO_CREDITS,
                            "enrichment_last_attempt_at": now_iso,
                        },
                    )
                return {"enriched": total_sent, "total": len(contacts), "no_credits": True}
            err_msg = f"http_{exc.response.status_code}:{body[:200]}"
            logger.error(
                "Apollo HTTP error for batch %d: status=%d body=%s",
                i,
                exc.response.status_code,
                body,
            )
            for c in batch:
                _safe_update(
                    db,
                    c["id"],
                    {
                        "enrichment_status": "enrichment_failed",
                        "enrichment_attempts": (c.get("enrichment_attempts") or 0) + 1,
                        "enrichment_last_attempt_at": now_iso,
                        "last_enrichment_error": err_msg,
                    },
                )
        except Exception as exc:
            logger.error("Apollo enrichment error for batch %d: %s", i, exc)
            now_iso = datetime.now(timezone.utc).isoformat()
            err_msg = f"exception:{str(exc)[:200]}"
            for c in batch:
                _safe_update(
                    db,
                    c["id"],
                    {
                        "enrichment_status": "enrichment_failed",
                        "enrichment_attempts": (c.get("enrichment_attempts") or 0) + 1,
                        "enrichment_last_attempt_at": now_iso,
                        "last_enrichment_error": err_msg,
                    },
                )

        if i + BATCH_SIZE < len(contacts):
            time.sleep(BATCH_DELAY)

    return {"enriched": total_sent, "total": len(contacts), "no_credits": False}


def sweep_stuck_enrichments(db: Client, clear_no_credits: bool = False) -> dict:
    """Auto-recover contacts stuck in enrichment without user intervention.

    Two conditions resetting a contact back to 'pending_enrichment':
      1. enrichment_status = 'enriching' for > STALE_ENRICHING_MINUTES
         (webhook never arrived — common when BACKEND_PUBLIC_URL was misset).
      2. enrichment_status = 'enrichment_failed' with attempts < MAX_RETRY_ATTEMPTS
         and last_enrichment_error != 'apollo_no_credits'.

    When clear_no_credits=True (from the manual retry button), contacts whose
    last_enrichment_error is 'apollo_no_credits' are ALSO reset, because the
    user is signalling that credits have been topped up.

    Returns counts per category plus whether enrichment ran.
    """
    stale_cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=STALE_ENRICHING_MINUTES)
    ).isoformat()

    stale_count = 0
    try:
        stale_enriching = (
            db.table("contacts")
            .update(
                {
                    "enrichment_status": "pending_enrichment",
                    "last_enrichment_error": "stale_enriching_timeout",
                }
            )
            .eq("enrichment_status", "enriching")
            .lt("enrichment_last_attempt_at", stale_cutoff)
            .execute()
        )
        stale_count = len(stale_enriching.data or [])
    except Exception as exc:
        msg = str(exc)
        if "PGRST204" in msg or "schema cache" in msg or "column" in msg.lower():
            logger.warning(
                "Skipping stale_enriching sweep (migration 013 not yet applied): %s",
                msg[:200],
            )
        else:
            raise

    retry_count = 0
    try:
        retryable_query = (
            db.table("contacts")
            .update({"enrichment_status": "pending_enrichment"})
            .eq("enrichment_status", "enrichment_failed")
            .lt("enrichment_attempts", MAX_RETRY_ATTEMPTS)
        )
        if not clear_no_credits:
            retryable_query = retryable_query.neq("last_enrichment_error", ERROR_NO_CREDITS)
        retryable = retryable_query.execute()
        retry_count = len(retryable.data or [])
    except Exception as exc:
        msg = str(exc)
        if "PGRST204" in msg or "schema cache" in msg or "column" in msg.lower():
            # Pre-migration fallback: reset all enrichment_failed up to a cap.
            logger.warning("Using pre-migration retry fallback: %s", msg[:200])
            simple_retry = (
                db.table("contacts")
                .update({"enrichment_status": "pending_enrichment"})
                .eq("enrichment_status", "enrichment_failed")
                .execute()
            )
            retry_count = len(simple_retry.data or [])
        else:
            raise

    credits_cleared = 0
    if clear_no_credits:
        try:
            credits_result = (
                db.table("contacts")
                .update(
                    {
                        "enrichment_status": "pending_enrichment",
                        "last_enrichment_error": None,
                    }
                )
                .eq("last_enrichment_error", ERROR_NO_CREDITS)
                .execute()
            )
            credits_cleared = len(credits_result.data or [])
        except Exception as exc:
            msg = str(exc)
            if "PGRST204" in msg or "schema cache" in msg or "column" in msg.lower():
                logger.warning("Skipping credits_cleared (migration 013 not applied)")
            else:
                raise

    total_reset = stale_count + retry_count + credits_cleared
    logger.info(
        "Enrichment sweep reset %d contacts (stale_enriching=%d, retry_failed=%d, credits_cleared=%d)",
        total_reset,
        stale_count,
        retry_count,
        credits_cleared,
    )
    # Always kick off enrich_contacts — it's a no-op if no contacts are in
    # pending_enrichment. Previously we gated on total_reset>0 which meant
    # contacts already sitting in pending_enrichment from a prior interrupted
    # run would never be picked back up by the Retry button.
    result = enrich_contacts(db, None)
    return {
        "stale_enriching_reset": stale_count,
        "failed_retried": retry_count,
        "credits_cleared": credits_cleared,
        "enrichment_result": result,
    }


def get_enrichment_health(db: Client) -> dict:
    """Return a summary of current enrichment state for the UI."""
    counts: dict[str, int] = {}
    for status in (
        "pending_enrichment",
        "enriching",
        "enriched",
        "enrichment_failed",
        "enrichment_no_phone",
    ):
        r = (
            db.table("contacts")
            .select("id", count="exact")
            .eq("enrichment_status", status)
            .execute()
        )
        counts[status] = r.count or 0

    def _safe_count(builder_fn) -> int:
        """Run a count query; return 0 if it fails due to missing columns (pre-migration)."""
        try:
            return builder_fn().count or 0
        except Exception as exc:
            msg = str(exc)
            if "PGRST204" in msg or "schema cache" in msg or "column" in msg.lower():
                return 0
            raise

    no_credits_count = _safe_count(
        lambda: db.table("contacts")
        .select("id", count="exact")
        .eq("last_enrichment_error", ERROR_NO_CREDITS)
        .execute()
    )
    exhausted_retries_count = _safe_count(
        lambda: db.table("contacts")
        .select("id", count="exact")
        .eq("enrichment_status", "enrichment_failed")
        .gte("enrichment_attempts", MAX_RETRY_ATTEMPTS)
        .execute()
    )
    stale_cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=STALE_ENRICHING_MINUTES)
    ).isoformat()
    stale_enriching_count = _safe_count(
        lambda: db.table("contacts")
        .select("id", count="exact")
        .eq("enrichment_status", "enriching")
        .lt("enrichment_last_attempt_at", stale_cutoff)
        .execute()
    )

    return {
        "counts_by_status": counts,
        "out_of_credits_count": no_credits_count,
        "exhausted_retries_count": exhausted_retries_count,
        "stale_enriching_count": stale_enriching_count,
        "out_of_credits": no_credits_count > 0,
    }
