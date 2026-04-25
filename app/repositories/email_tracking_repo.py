from __future__ import annotations

from supabase import Client


def upsert_tracked_emails(db: Client, emails: list[dict]) -> int:
    """Bulk upsert tracked emails, deduplicating by (user_id, gmail_message_id)."""
    if not emails:
        return 0
    result = (
        db.table("tracked_emails")
        .upsert(emails, on_conflict="user_id,gmail_message_id")
        .execute()
    )
    return len(result.data) if result.data else 0


def get_tracked_contacts_summary(db: Client, user_id: str) -> list[dict]:
    """Return contacts the user has email interactions with, along with stats.

    Uses an RPC-free approach: fetch tracked emails grouped info, then
    join with contacts in Python for maximum compatibility.
    """
    tracked = (
        db.table("tracked_emails")
        .select("contact_id, direction, message_date")
        .eq("user_id", user_id)
        .not_.is_("contact_id", "null")
        .order("message_date", desc=True)
        .execute()
    )
    rows = tracked.data or []
    if not rows:
        return []

    contact_stats: dict[str, dict] = {}
    for row in rows:
        cid = row["contact_id"]
        if cid not in contact_stats:
            contact_stats[cid] = {
                "contact_id": cid,
                "sent_count": 0,
                "received_count": 0,
                "last_sent_at": None,
                "last_received_at": None,
            }
        s = contact_stats[cid]
        if row["direction"] == "sent":
            s["sent_count"] += 1
            if not s["last_sent_at"]:
                s["last_sent_at"] = row["message_date"]
        else:
            s["received_count"] += 1
            if not s["last_received_at"]:
                s["last_received_at"] = row["message_date"]

    contact_ids = list(contact_stats.keys())
    contacts_result = (
        db.table("contacts")
        .select("id, first_name, last_name, company_name, email")
        .in_("id", contact_ids)
        .execute()
    )
    contact_map = {c["id"]: c for c in (contacts_result.data or [])}

    summaries = []
    for cid, stats in contact_stats.items():
        contact = contact_map.get(cid)
        if not contact:
            continue
        reply_status = "no_emails"
        if stats["sent_count"] > 0 and stats["received_count"] > 0:
            reply_status = "replied"
        elif stats["sent_count"] > 0:
            reply_status = "awaiting_reply"

        summaries.append({
            **stats,
            "first_name": contact.get("first_name"),
            "last_name": contact.get("last_name"),
            "company_name": contact.get("company_name", ""),
            "email": contact.get("email", ""),
            "reply_status": reply_status,
        })

    summaries.sort(
        key=lambda s: s["last_received_at"] or s["last_sent_at"] or "",
        reverse=True,
    )
    return summaries


def get_tracked_thread(db: Client, user_id: str, contact_id: str) -> list[dict]:
    """Return all tracked emails between the user and a specific contact."""
    result = (
        db.table("tracked_emails")
        .select("*")
        .eq("user_id", user_id)
        .eq("contact_id", contact_id)
        .order("message_date", desc=True)
        .execute()
    )
    return result.data or []
