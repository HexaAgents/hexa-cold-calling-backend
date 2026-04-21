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


def process_csv_upload(
    db: Client,
    file_content: bytes,
    filename: str,
    user_id: str,
    batch_id: str,
) -> str:
    """Parse CSV, score companies, insert qualifying contacts. Returns batch_id."""
    start_time = time.monotonic()
    text = file_content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    rows = [_map_row(row, reader.fieldnames or []) for row in reader]
    rows = [r for r in rows if r.get("company_name")]

    import_batch_repo.update_batch(db, batch_id, {"total_rows": len(rows)})

    websites = list({r["website"] for r in rows if r.get("website")})
    existing_scores = contact_repo.get_existing_scores(db, websites)

    websites_to_score: dict[str, dict[str, str]] = {}
    for row in rows:
        w = row.get("website", "")
        if w and w not in existing_scores and w not in websites_to_score:
            websites_to_score[w] = {
                "company_name": row.get("company_name", ""),
                "job_title": row.get("title", ""),
            }

    if websites_to_score:
        new_scores = _score_websites_concurrent(
            websites_to_score, db, batch_id, len(rows),
        )
        existing_scores.update(new_scores)

    if _is_timed_out(start_time):
        logger.error("Import timed out after scoring phase for batch %s", batch_id)
        import_batch_repo.update_batch(db, batch_id, {"status": "failed"})
        return batch_id

    stored = 0
    discarded = 0
    processed = 0

    for i in range(0, len(rows), BATCH_SIZE):
        if _is_timed_out(start_time):
            logger.error("Import timed out during row processing for batch %s", batch_id)
            import_batch_repo.update_batch(db, batch_id, {"status": "failed"})
            return batch_id

        batch_rows = rows[i : i + BATCH_SIZE]
        contacts_to_insert: list[dict] = []

        for row in batch_rows:
            processed += 1
            website = row.get("website", "")

            if website and website in existing_scores:
                score_data = existing_scores[website]
            else:
                score_data = dict(_FAILED_SCORE)

            score_val = score_data.get("score", 0)
            is_failed = score_data.get("scoring_failed", False)

            if score_val > 0 or is_failed:
                contact = {**row, **score_data, "import_batch_id": batch_id}
                contacts_to_insert.append(contact)
                stored += 1
            else:
                discarded += 1

        if contacts_to_insert:
            contact_repo.create_contacts_batch(db, contacts_to_insert)

        import_batch_repo.update_batch(db, batch_id, {
            "processed_rows": processed,
            "stored_rows": stored,
            "discarded_rows": discarded,
        })

    import_batch_repo.update_batch(db, batch_id, {"status": "completed"})
    return batch_id


def _is_timed_out(start_time: float) -> bool:
    return (time.monotonic() - start_time) > MAX_IMPORT_SECONDS


def _score_websites_concurrent(
    websites_to_score: dict[str, dict[str, str]],
    db: Client,
    batch_id: str,
    total_rows: int,
) -> dict[str, dict]:
    """Score unique websites concurrently using a thread pool."""
    scores: dict[str, dict] = {}
    total_to_score = len(websites_to_score)
    scored_count = 0

    logger.info(
        "Scoring %d unique websites concurrently (max %d workers)",
        total_to_score,
        MAX_SCORING_WORKERS,
    )

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

            scored_count += 1
            if scored_count % 5 == 0 or scored_count == total_to_score:
                estimated = int(scored_count / total_to_score * total_rows)
                import_batch_repo.update_batch(
                    db, batch_id, {"processed_rows": estimated},
                )
                logger.info("Scored %d/%d websites", scored_count, total_to_score)

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
