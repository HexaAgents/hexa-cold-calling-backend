from __future__ import annotations

from datetime import datetime, timezone

from supabase import Client


def company_flag_key(company_name: str) -> str:
    """Normalized key matching how the companies pages group contacts."""
    return (company_name or "").strip().lower()


def get_flag(db: Client, company_name: str) -> dict | None:
    key = company_flag_key(company_name)
    if not key:
        return None
    result = (
        db.table("company_flags")
        .select("*")
        .eq("company_key", key)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def upsert_flag(
    db: Client,
    company_name: str,
    reason: str,
    details: str | None,
    flagged_by: str,
    flagged_by_name: str | None,
) -> dict:
    """Create or replace the flag for a company (one flag per company)."""
    payload = {
        "company_key": company_flag_key(company_name),
        "company_name": company_name.strip(),
        "reason": reason,
        "details": details,
        "flagged_by": flagged_by,
        "flagged_by_name": flagged_by_name,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    result = (
        db.table("company_flags")
        .upsert(payload, on_conflict="company_key")
        .execute()
    )
    return result.data[0]


def delete_flag(db: Client, company_name: str) -> bool:
    key = company_flag_key(company_name)
    if not key:
        return False
    result = db.table("company_flags").delete().eq("company_key", key).execute()
    return bool(result.data)
