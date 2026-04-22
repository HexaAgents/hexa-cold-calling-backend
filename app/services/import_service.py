from __future__ import annotations

import csv
import io
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from supabase import Client

from app.config import settings
from app.repositories import contact_repo, import_batch_repo
from app.services.scoring_service import score_website

logger = logging.getLogger(__name__)

COLUMN_MAP: dict[str, str] = {
    "First Name": "first_name",
    "Last Name": "last_name",
    "Title": "title",
    "Company Name": "company_name",
    "Person Linkedin Url": "person_linkedin_url",
    "Website": "website",
    "Company Linkedin Url": "company_linkedin_url",
    "# Employees": "employees",
    "City": "city",
    "Country": "country",
    "Email": "email",
    "Phone": "mobile_phone",
    "Mobile Phone": "mobile_phone",
    "Work Direct Phone": "work_direct_phone",
    "Corporate Phone": "corporate_phone",
}

BATCH_SIZE = 10
MAX_SCORING_WORKERS = 8
SCORING_TIMEOUT = 90
MAX_IMPORT_SECONDS = 600

_FAILED_SCORE: dict[str, object] = {
    "score": 0,
    "company_type": "rejected",
    "rationale": "No website provided",
    "rejection_reason": "unclear",
    "exa_scrape_success": False,
    "scoring_failed": False,
}

_PHONE_FIELDS = ("mobile_phone", "work_direct_phone", "corporate_phone")


def process_csv_upload(
    db: Client,
    file_content: bytes,
    filename: str,
    user_id: str,
    batch_id: str,
) -> str:
    """Parse CSV, score, insert, and enrich contacts in streaming batches.

    Each batch of BATCH_SIZE rows is scored, inserted, and enriched before
    moving to the next batch so contacts become callable as fast as possible.
    """
    start_time = time.monotonic()
    text = file_content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    rows = [_map_row(row, reader.fieldnames or []) for row in reader]
    rows = [r for r in rows if r.get("company_name")]

    import_batch_repo.update_batch(db, batch_id, {"total_rows": len(rows)})

    all_websites = list({r["website"] for r in rows if r.get("website")})
    scored_cache = contact_repo.get_existing_scores(db, all_websites)

    stored = 0
    discarded = 0
    processed = 0
    enriched = 0

    for i in range(0, len(rows), BATCH_SIZE):
        if _is_timed_out(start_time):
            logger.error("Import timed out for batch %s", batch_id)
            import_batch_repo.update_batch(db, batch_id, {"status": "failed"})
            return batch_id

        batch_rows = rows[i : i + BATCH_SIZE]

        to_score: dict[str, dict[str, str]] = {}
        for row in batch_rows:
            w = row.get("website", "")
            if w and w not in scored_cache and w not in to_score:
                to_score[w] = {
                    "company_name": row.get("company_name", ""),
                    "job_title": row.get("title", ""),
                }

        if to_score:
            new_scores = _score_batch(to_score)
            scored_cache.update(new_scores)

        contacts_to_insert: list[dict] = []
        for row in batch_rows:
            processed += 1
            website = row.get("website", "")

            if website and website in scored_cache:
                score_data = scored_cache[website]
            else:
                score_data = dict(_FAILED_SCORE)

            score_val = score_data.get("score", 0)
            is_failed = score_data.get("scoring_failed", False)

            if score_val > 0 or is_failed:
                contact = {**row, **score_data, "import_batch_id": batch_id}
                has_phone = any(row.get(f) for f in _PHONE_FIELDS)
                if not has_phone:
                    contact["enrichment_status"] = "pending_enrichment"
                contacts_to_insert.append(contact)
                stored += 1
            else:
                discarded += 1

        if contacts_to_insert:
            inserted = contact_repo.create_contacts_batch(db, contacts_to_insert)

            enrich_ids = [
                c["id"] for c in inserted
                if c.get("enrichment_status") == "pending_enrichment"
            ]
            if enrich_ids and settings.apollo_api_key:
                try:
                    from app.services import apollo_service
                    apollo_service.enrich_contacts(db, enrich_ids)
                    enriched += len(enrich_ids)
                except Exception as exc:
                    logger.error("Auto-enrichment failed for batch %s: %s", batch_id, exc)

        import_batch_repo.update_batch(db, batch_id, {
            "processed_rows": processed,
            "stored_rows": stored,
            "discarded_rows": discarded,
            "enriched_rows": enriched,
        })

    import_batch_repo.update_batch(db, batch_id, {"status": "completed"})
    return batch_id


def _is_timed_out(start_time: float) -> bool:
    return (time.monotonic() - start_time) > MAX_IMPORT_SECONDS


def _score_batch(websites_to_score: dict[str, dict[str, str]]) -> dict[str, dict]:
    """Score a small set of websites concurrently using a thread pool."""
    scores: dict[str, dict] = {}

    with ThreadPoolExecutor(max_workers=MAX_SCORING_WORKERS) as executor:
        futures = {}
        for website, info in websites_to_score.items():
            future = executor.submit(
                score_website,
                exa_api_key=settings.exa_api_key,
                openai_api_key=settings.openai_api_key,
                openai_model=settings.openai_model,
                website=website,
                company_name=info["company_name"],
                job_title=info["job_title"],
            )
            futures[future] = website

        for future in as_completed(futures):
            website = futures[future]
            try:
                scores[website] = future.result(timeout=SCORING_TIMEOUT)
            except Exception as exc:
                logger.error("Scoring failed for %s: %s", website, exc)
                scores[website] = {
                    "score": 0,
                    "company_type": "rejected",
                    "rationale": f"Scoring error: {str(exc)[:200]}",
                    "rejection_reason": "unclear",
                    "exa_scrape_success": False,
                    "scoring_failed": True,
                }

    return scores


def _map_row(row: dict[str, Any], fieldnames: list[str]) -> dict[str, Any]:
    """Map CSV column names to database column names, discarding unknown columns."""
    mapped: dict[str, Any] = {}
    for csv_col in fieldnames:
        db_col = COLUMN_MAP.get(csv_col)
        if db_col:
            value = (row.get(csv_col) or "").strip()
            if value:
                if db_col in mapped and mapped[db_col]:
                    continue
                mapped[db_col] = value
    return mapped
