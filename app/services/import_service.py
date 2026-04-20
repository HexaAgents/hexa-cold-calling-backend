from __future__ import annotations

import csv
import io
import logging
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


def process_csv_upload(
    db: Client,
    file_content: bytes,
    filename: str,
    user_id: str,
) -> str:
    """Parse CSV, score companies, insert qualifying contacts. Returns batch_id."""
    text = file_content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    rows = [_map_row(row, reader.fieldnames or []) for row in reader]
    rows = [r for r in rows if r.get("company_name")]

    batch = import_batch_repo.create_batch(db, {
        "user_id": user_id,
        "filename": filename,
        "total_rows": len(rows),
        "status": "processing",
    })
    batch_id = batch["id"]

    websites = list({r["website"] for r in rows if r.get("website")})
    existing_scores = contact_repo.get_existing_scores(db, websites)

    stored = 0
    discarded = 0
    processed = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch_rows = rows[i : i + BATCH_SIZE]
        contacts_to_insert: list[dict] = []

        for row in batch_rows:
            processed += 1
            website = row.get("website", "")

            if website and website in existing_scores:
                score_data = existing_scores[website]
            elif website:
                try:
                    score_data = score_website(
                        exa_api_key=settings.exa_api_key,
                        openai_api_key=settings.openai_api_key,
                        openai_model=settings.openai_model,
                        website=website,
                        company_name=row.get("company_name", ""),
                        job_title=row.get("title", ""),
                    )
                except Exception as exc:
                    logger.error("Scoring failed for %s: %s", website, exc)
                    score_data = {
                        "score": 0,
                        "company_type": "rejected",
                        "rationale": f"Scoring error: {str(exc)[:200]}",
                        "rejection_reason": "unclear",
                        "exa_scrape_success": False,
                        "scoring_failed": True,
                    }

                if website not in existing_scores:
                    existing_scores[website] = score_data
            else:
                score_data = {
                    "score": 0,
                    "company_type": "rejected",
                    "rationale": "No website provided",
                    "rejection_reason": "unclear",
                    "exa_scrape_success": False,
                    "scoring_failed": False,
                }

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
