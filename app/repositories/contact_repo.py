from __future__ import annotations

from datetime import datetime, timedelta, timezone

from supabase import Client

STALE_CLAIM_HOURS = 10

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
    query = query.neq("company_type", "rejected")
    query = query.or_("hidden.is.null,hidden.eq.false")

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


def release_stale_claims(db: Client) -> int:
    """Release contacts claimed more than STALE_CLAIM_HOURS ago with no outcome."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=STALE_CLAIM_HOURS)).isoformat()
    result = (
        db.table("contacts")
        .update({"assigned_to": None, "assigned_at": None})
        .not_.is_("assigned_to", "null")
        .is_("call_outcome", "null")
        .lt("assigned_at", cutoff)
        .execute()
    )
    return len(result.data) if result.data else 0


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


_COMPANY_FIELDS = (
    "company_name, website, company_linkedin_url, company_description,"
    "employees, industry_tag, score, city, state, country, call_outcome"
)


def get_all_companies(db: Client, search: str | None = None) -> list[dict]:
    """Return company summaries grouped by company_name from non-rejected contacts."""
    query = (
        db.table("contacts")
        .select(_COMPANY_FIELDS)
        .neq("company_type", "rejected")
        .or_("hidden.is.null,hidden.eq.false")
        .neq("company_name", "")
    )
    if search:
        query = query.ilike("company_name", f"%{search}%")
    result = query.execute()
    rows = result.data or []
    if not rows:
        return []

    groups: dict[str, dict] = {}
    for row in rows:
        name = row["company_name"]
        if name not in groups:
            groups[name] = {
                "company_name": name,
                "website": None,
                "company_linkedin_url": None,
                "company_description": None,
                "employees": None,
                "industry_tag": None,
                "city": None,
                "state": None,
                "country": None,
                "contact_count": 0,
                "score_sum": 0,
                "score_count": 0,
            }
        g = groups[name]
        g["contact_count"] += 1
        for field in ("website", "company_linkedin_url", "company_description",
                      "employees", "industry_tag", "city", "state", "country"):
            if not g[field] and row.get(field):
                g[field] = row[field]
        if row.get("score") is not None:
            g["score_sum"] += row["score"]
            g["score_count"] += 1

    summaries = []
    for g in groups.values():
        avg = round(g["score_sum"] / g["score_count"]) if g["score_count"] else None
        summaries.append({
            "company_name": g["company_name"],
            "website": g["website"],
            "company_linkedin_url": g["company_linkedin_url"],
            "company_description": g["company_description"],
            "employees": g["employees"],
            "industry_tag": g["industry_tag"],
            "city": g["city"],
            "state": g["state"],
            "country": g["country"],
            "contact_count": g["contact_count"],
            "avg_score": avg,
        })
    summaries.sort(key=lambda s: s["contact_count"], reverse=True)
    return summaries


def get_contacts_by_company(db: Client, company_name: str) -> list[dict]:
    """Return all non-rejected, non-hidden contacts for an exact company name."""
    result = (
        db.table("contacts")
        .select("*")
        .eq("company_name", company_name)
        .neq("company_type", "rejected")
        .or_("hidden.is.null,hidden.eq.false")
        .order("score", desc=True)
        .execute()
    )
    return result.data or []
