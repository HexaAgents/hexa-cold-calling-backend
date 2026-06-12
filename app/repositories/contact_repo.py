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
        # search_text is a generated column concatenating name, company, and
        # phone fields, backed by a trigram GIN index (migration 034) so
        # leading-wildcard ILIKE uses an index scan.
        query = query.ilike("search_text", f"%{search}%")

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


def silence_exhausted_didnt_pick_up_contacts(db: Client, threshold: int) -> int:
    """Silence didn't-pick-up contacts that have hit the give-up threshold.

    "Silencing" means clearing `retry_at` so they no longer match the retry
    branch of `claim_next_contact` and drop out of the call tracker queue.
    The contacts themselves remain in the database and contacts list — the
    user just stops being prompted to call them again.

    Called when the SMS / give-up threshold is lowered, to retroactively
    quiet contacts that now sit at or above the new limit.
    """
    if threshold <= 0:
        return 0
    result = (
        db.table("contacts")
        .update({"retry_at": None})
        .eq("call_outcome", "didnt_pick_up")
        .gte("call_occasion_count", threshold)
        .not_.is_("retry_at", "null")
        .execute()
    )
    return len(result.data) if result.data else 0


def contact_identity_key(row: dict) -> tuple[str, str, str] | None:
    """Normalized (first_name, last_name, person_linkedin_url) identity key.

    Used to detect the same person across imports. Returns None when the row
    has no identifying fields at all (so such rows are never treated as
    duplicates of each other).
    """
    first = (row.get("first_name") or "").strip().lower()
    last = (row.get("last_name") or "").strip().lower()
    linkedin = (row.get("person_linkedin_url") or "").strip().lower().rstrip("/")
    if not (first or last or linkedin):
        return None
    return (first, last, linkedin)


_IDENTITY_PAGE = 1000


def get_existing_identity_keys(
    db: Client,
) -> tuple[set[tuple[str, str, str]], set[tuple[str, str, str]]]:
    """Return (passing_keys, failed_only_keys) for contacts in the database.

    passing_keys: identities with at least one live contact (not rejected,
    not hidden) — imports must never re-insert or re-enrich these.
    failed_only_keys: identities that exist ONLY as rejected/hidden contacts —
    imports may re-evaluate these under the current scoring prompt.
    """
    passing: set[tuple[str, str, str]] = set()
    all_keys: set[tuple[str, str, str]] = set()
    offset = 0
    while True:
        result = (
            db.table("contacts")
            .select("first_name, last_name, person_linkedin_url, company_type, hidden")
            .range(offset, offset + _IDENTITY_PAGE - 1)
            .execute()
        )
        rows = result.data or []
        for row in rows:
            key = contact_identity_key(row)
            if not key:
                continue
            all_keys.add(key)
            if row.get("company_type") != "rejected" and not row.get("hidden"):
                passing.add(key)
        if len(rows) < _IDENTITY_PAGE:
            break
        offset += _IDENTITY_PAGE
    return passing, all_keys - passing


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
            if not w:
                continue
            # A website can have both old rejected rows and a newer passing
            # row (re-evaluated companies). Keep the best verdict so imports
            # don't re-score companies that have already passed filtering.
            current = scores.get(w)
            if current is None or _score_row_rank(row) > _score_row_rank(current):
                scores[w] = row
    return scores


def _score_row_rank(row: dict) -> tuple[int, int]:
    """Prefer distributor rows over rejected ones, then higher scores."""
    return (
        1 if row.get("company_type") == "distributor" else 0,
        row.get("score") or 0,
    )


def get_callable_location_counts(db: Client) -> dict:
    """Counts of callable contacts grouped by country, state, and city.

    "Callable" mirrors the claim_next_contact availability rules: not hidden,
    not rejected, has at least one phone number, and is either never called
    (fresh) or a didnt_pick_up retry that is due. Contacts currently claimed
    by a user are still counted — claims are transient.

    Aggregated in SQL via the get_callable_location_counts RPC (migration
    035) — one GROUP BY instead of paging the whole pool over PostgREST.

    Returns {"total", "countries", "states", "cities", "no_location",
    "call_counts"} where each location list is [{"name", "count"}, ...]
    sorted by count descending, and call_counts buckets the pool by how many
    times each contact has been called before: {"never", "once", "twice",
    "three_plus"}.
    """
    result = db.rpc("get_callable_location_counts").execute()
    return result.data or {
        "total": 0,
        "countries": [],
        "states": [],
        "cities": [],
        "no_location": 0,
        "call_counts": {"never": 0, "once": 0, "twice": 0, "three_plus": 0},
    }


def get_distinct_locations(db: Client) -> dict:
    """Distinct non-empty city/state/country values for filter dropdowns.

    Uses the get_distinct_locations RPC (migration 035): one SQL DISTINCT
    query instead of three unbounded column scans deduped in Python (which
    silently truncated at the PostgREST max-rows cap).
    """
    result = db.rpc("get_distinct_locations").execute()
    return result.data or {"cities": [], "states": [], "countries": []}


def get_contacts_existing_ids(db: Client, contact_ids: list[str]) -> list[str]:
    """Return the subset of contact_ids that still exist, in one query."""
    if not contact_ids:
        return []
    existing: list[str] = []
    chunk_size = 200
    for i in range(0, len(contact_ids), chunk_size):
        chunk = contact_ids[i : i + chunk_size]
        result = db.table("contacts").select("id").in_("id", chunk).execute()
        existing.extend(row["id"] for row in (result.data or []))
    return existing


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


def get_all_companies(db: Client, search: str | None = None) -> list[dict]:
    """Return company summaries grouped by company_name from non-rejected contacts.

    Aggregated in SQL via the get_company_summaries RPC (migration 035)
    instead of fetching every contact row and grouping in Python.
    """
    result = db.rpc("get_company_summaries", {"p_search": search}).execute()
    return result.data or []


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
