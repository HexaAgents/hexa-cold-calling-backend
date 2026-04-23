from __future__ import annotations

from supabase import Client


VALID_SORT_COLUMNS = {"created_at", "call_occasion_count", "times_called", "call_outcome", "score"}


def list_contacts(
    db: Client,
    sort_by: str = "created_at",
    sort_order: str = "asc",
    outcome_filter: str | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[dict], int]:
    if sort_by not in VALID_SORT_COLUMNS:
        sort_by = "created_at"

    query = db.table("contacts").select("*", count="exact")

    if outcome_filter:
        query = query.eq("call_outcome", outcome_filter)

    if search:
        pattern = f"%{search}%"
        query = query.or_(
            f"first_name.ilike.{pattern},"
            f"last_name.ilike.{pattern},"
            f"company_name.ilike.{pattern},"
            f"mobile_phone.ilike.{pattern},"
            f"work_direct_phone.ilike.{pattern},"
            f"corporate_phone.ilike.{pattern}"
        )

    desc = sort_order.lower() == "desc"
    query = query.order(sort_by, desc=desc)

    offset = (page - 1) * per_page
    query = query.range(offset, offset + per_page - 1)

    result = query.execute()
    return result.data or [], result.count or 0


def get_contact(db: Client, contact_id: str) -> dict | None:
    result = db.table("contacts").select("*").eq("id", contact_id).single().execute()
    return result.data


def create_contacts_batch(db: Client, contacts: list[dict]) -> list[dict]:
    if not contacts:
        return []
    result = db.table("contacts").insert(contacts).execute()
    return result.data or []


def update_contact(db: Client, contact_id: str, data: dict) -> dict | None:
    result = db.table("contacts").update(data).eq("id", contact_id).execute()
    return result.data[0] if result.data else None


def delete_contact(db: Client, contact_id: str) -> bool:
    result = db.table("contacts").delete().eq("id", contact_id).execute()
    return bool(result.data)


def delete_contacts_by_batch(db: Client, batch_id: str) -> int:
    result = db.table("contacts").delete().eq("import_batch_id", batch_id).execute()
    return len(result.data) if result.data else 0


_SCORE_FIELDS = "website, score, company_type, rationale, rejection_reason, exa_scrape_success, company_description"
_SCORE_QUERY_CHUNK = 50


def get_existing_scores(db: Client, websites: list[str]) -> dict[str, dict]:
    """Return a map of website -> {score, company_type, rationale, ...} for already-scored websites."""
    if not websites:
        return {}
    scores: dict[str, dict] = {}
    for i in range(0, len(websites), _SCORE_QUERY_CHUNK):
        chunk = websites[i : i + _SCORE_QUERY_CHUNK]
        result = (
            db.table("contacts")
            .select(_SCORE_FIELDS)
            .in_("website", chunk)
            .not_.is_("score", "null")
            .execute()
        )
        for row in result.data or []:
            w = row.get("website")
            if w and w not in scores:
                scores[w] = row
    return scores


def get_contacts_needing_sms(db: Client) -> list[dict]:
    """Return contacts with scheduled SMS that are due."""
    result = (
        db.table("contacts")
        .select("*")
        .eq("messaging_status", "to_be_messaged")
        .not_.is_("sms_scheduled_at", "null")
        .lte("sms_scheduled_at", "now()")
        .execute()
    )
    return result.data or []
