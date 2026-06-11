from __future__ import annotations

import csv
import io
import logging
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
    "State": "state",
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
ENRICHMENT_MIN_SCORE = 50

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
    """Parse CSV, dedupe, score, insert, and enrich contacts in streaming batches.

    Rows whose (first name, last name, LinkedIn URL) match a contact already
    in the database — or an earlier row in the same file — are skipped before
    scoring so the same person is never stored or enriched twice.

    Each batch of BATCH_SIZE rows is scored, inserted, and enriched before
    moving to the next batch so contacts become callable as fast as possible.

    Once processing is done the kept-rows-only subset of the original CSV is
    written back to the batch as ``filtered_csv`` (same headers and column
    order as the upload) so users can download the cleaned file. The exact
    complement — the rejected and zero-score rows — is written back as
    ``discarded_csv`` so users can audit what was dropped.
    """
    text = file_content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    fieldnames = list(reader.fieldnames or [])

    raw_rows = list(reader)
    mapped_rows = [_map_row(row, fieldnames) for row in raw_rows]
    # Drop rows missing company_name from both the mapped and raw lists in
    # lock-step so the kept-rows index lines up with the original CSV row.
    keep_indices = [i for i, m in enumerate(mapped_rows) if m.get("company_name")]
    raw_rows = [raw_rows[i] for i in keep_indices]
    rows = [mapped_rows[i] for i in keep_indices]

    import_batch_repo.update_batch(db, batch_id, {"total_rows": len(rows)})

    # Duplicate scan: skip rows whose (first name, last name, LinkedIn URL)
    # already exists in the database — or earlier in this same CSV — so the
    # same person is never inserted, scored, or enriched twice.
    existing_keys = contact_repo.get_existing_identity_keys(db)
    seen_keys: set[tuple[str, str, str]] = set()
    deduped_rows: list[dict[str, Any]] = []
    deduped_raw_rows: list[dict[str, Any]] = []
    duplicate_raw_rows: list[dict[str, Any]] = []
    for raw_row, row in zip(raw_rows, rows):
        key = contact_repo.contact_identity_key(row)
        if key and (key in existing_keys or key in seen_keys):
            duplicate_raw_rows.append(raw_row)
            continue
        if key:
            seen_keys.add(key)
        deduped_rows.append(row)
        deduped_raw_rows.append(raw_row)
    rows, raw_rows = deduped_rows, deduped_raw_rows

    duplicates = len(duplicate_raw_rows)
    if duplicates:
        logger.info("Import %s: skipping %d duplicate contacts that already exist", batch_id, duplicates)

    credits_available = _retry_pending_enrichments(db, batch_id)

    all_websites = list({r["website"] for r in rows if r.get("website")})
    scored_cache = contact_repo.get_existing_scores(db, all_websites)

    stored = 0
    discarded = duplicates
    processed = duplicates
    enriched = 0
    kept_raw_rows: list[dict[str, Any]] = []
    # Skipped duplicates land in the discarded CSV so the upload is auditable.
    discarded_raw_rows: list[dict[str, Any]] = list(duplicate_raw_rows)

    for i in range(0, len(rows), BATCH_SIZE):
        batch_rows = rows[i : i + BATCH_SIZE]
        batch_raw_rows = raw_rows[i : i + BATCH_SIZE]

        to_score: dict[str, dict[str, str]] = {}
        for row in batch_rows:
            w = row.get("website", "")
            if not w or w in to_score:
                continue
            cached = scored_cache.get(w)
            if not cached or cached.get("company_type") != "distributor":
                to_score[w] = {
                    "company_name": row.get("company_name", ""),
                    "job_title": row.get("title", ""),
                }

        if to_score:
            new_scores = _score_batch(to_score)
            scored_cache.update(new_scores)

        contacts_to_insert: list[dict] = []
        for raw_row, row in zip(batch_raw_rows, batch_rows):
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
                if score_data.get("company_type") == "rejected":
                    contact["hidden"] = True
                has_mobile = bool(row.get("mobile_phone"))
                if not has_mobile and score_val >= ENRICHMENT_MIN_SCORE:
                    contact["enrichment_status"] = "pending_enrichment"
                contacts_to_insert.append(contact)
                stored += 1
                # The filtered CSV mirrors what the user will see in the
                # call tracker: rejected contacts (hidden=True) are dropped,
                # everything else (including scoring failures, which the
                # user still works through manually) is kept. The discarded
                # CSV is the exact complement, so rejected rows land there.
                if not contact.get("hidden"):
                    kept_raw_rows.append(raw_row)
                else:
                    discarded_raw_rows.append(raw_row)
            else:
                discarded += 1
                discarded_raw_rows.append(raw_row)

        if contacts_to_insert:
            inserted = _safe_insert_batch(db, contacts_to_insert)
            if credits_available:
                result = _enrich_batch(db, inserted, batch_id)
                if result < 0:
                    credits_available = False
                else:
                    enriched += result

        import_batch_repo.update_batch(db, batch_id, {
            "processed_rows": processed,
            "stored_rows": stored,
            "discarded_rows": discarded,
            "enriched_rows": enriched,
        })

    final_update: dict = {
        "status": "completed",
        # Written here too so counts are correct even when every row was a
        # duplicate and the batch loop never ran.
        "processed_rows": processed,
        "stored_rows": stored,
        "discarded_rows": discarded,
        "filtered_csv": _render_filtered_csv(fieldnames, kept_raw_rows),
        "discarded_csv": _render_filtered_csv(fieldnames, discarded_raw_rows),
    }
    if not credits_available:
        final_update["enrichment_error"] = "Apollo credits exhausted"
    import_batch_repo.update_batch(db, batch_id, final_update)
    return batch_id


def _render_filtered_csv(fieldnames: list[str], rows: list[dict[str, Any]]) -> str:
    """Re-emit the kept rows with the original headers in original order.

    Unknown extra keys on rows are dropped so the output schema exactly
    matches the upload.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k, "") for k in fieldnames})
    return buffer.getvalue()


def _safe_insert_batch(db: Client, contacts: list[dict]) -> list[dict]:
    """Insert a batch of contacts, falling back to one-by-one on failure."""
    try:
        return contact_repo.create_contacts_batch(db, contacts)
    except Exception as exc:
        logger.warning("Batch insert failed (%d rows), retrying individually: %s", len(contacts), exc)

    inserted: list[dict] = []
    for contact in contacts:
        try:
            result = contact_repo.create_contacts_batch(db, [contact])
            inserted.extend(result)
        except Exception as exc:
            logger.error("Single-row insert failed for %s: %s", contact.get("company_name", "?"), exc)
    return inserted


def _retry_pending_enrichments(db: Client, batch_id: str) -> bool:
    """Try to enrich pending contacts from previous imports. Returns False if credits exhausted."""
    if not settings.apollo_api_key:
        return True
    result = (
        db.table("contacts")
        .select("id")
        .eq("enrichment_status", "pending_enrichment")
        .neq("import_batch_id", batch_id)
        .execute()
    )
    pending_ids = [r["id"] for r in (result.data or [])]
    if not pending_ids:
        return True
    try:
        from app.services import apollo_service
        res = apollo_service.enrich_contacts(db, pending_ids)
        if res.get("no_credits"):
            logger.warning("Apollo credits exhausted while retrying %d pending contacts", len(pending_ids))
            return False
        return True
    except Exception as exc:
        logger.error("Retry enrichment failed: %s", exc)
        return True


def _enrich_batch(db: Client, inserted: list[dict], batch_id: str) -> int:
    """Send enrichment requests for phoneless contacts in this batch.

    Returns count of contacts sent for enrichment, or -1 if credits exhausted.
    """
    enrich_ids = [
        c["id"] for c in inserted
        if c.get("enrichment_status") == "pending_enrichment"
    ]
    if not enrich_ids or not settings.apollo_api_key:
        return 0
    try:
        from app.services import apollo_service
        res = apollo_service.enrich_contacts(db, enrich_ids)
        if res.get("no_credits"):
            return -1
        return len(enrich_ids)
    except Exception as exc:
        logger.error("Batch enrichment failed for import %s: %s", batch_id, exc)
        return 0


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
