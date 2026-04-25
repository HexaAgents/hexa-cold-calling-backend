from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from email.mime.text import MIMEText

import httpx
from supabase import Client

from app.config import settings
from app.repositories import contact_repo, email_repo, email_tracking_repo, settings_repo

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
SCOPES = "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/userinfo.email"


def get_oauth_url(user_id: str, redirect_uri: str) -> str:
    """Build the Google OAuth consent URL."""
    params = httpx.QueryParams({
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": user_id,
    })
    return f"{GOOGLE_AUTH_URL}?{params}"


def exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange an authorization code for access + refresh tokens."""
    resp = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )
    resp.raise_for_status()
    return resp.json()


def refresh_access_token(refresh_token: str) -> dict:
    """Use a refresh token to get a new access token."""
    resp = httpx.post(
        GOOGLE_TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "grant_type": "refresh_token",
        },
    )
    resp.raise_for_status()
    return resp.json()


def get_gmail_address(access_token: str) -> str:
    """Fetch the Gmail address associated with an access token."""
    resp = httpx.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp.raise_for_status()
    return resp.json().get("email", "")


def _get_valid_access_token(db: Client, user_id: str) -> tuple[str, str]:
    """Return (access_token, gmail_address) refreshing if expired."""
    tokens = email_repo.get_gmail_tokens(db, user_id)
    if not tokens:
        raise ValueError("Gmail not connected. Please connect your Gmail account in Settings.")

    expiry = tokens.get("token_expiry")
    access_token = tokens["access_token"]

    needs_refresh = True
    if expiry:
        try:
            exp_dt = datetime.fromisoformat(expiry.replace("Z", "+00:00"))
            if exp_dt > datetime.now(timezone.utc):
                needs_refresh = False
        except (ValueError, TypeError):
            pass

    if needs_refresh:
        token_data = refresh_access_token(tokens["refresh_token"])
        access_token = token_data["access_token"]
        expires_in = token_data.get("expires_in", 3600)
        from datetime import timedelta
        new_expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()
        email_repo.upsert_gmail_tokens(db, user_id, {
            "access_token": access_token,
            "gmail_address": tokens["gmail_address"],
            "refresh_token": tokens["refresh_token"],
            "token_expiry": new_expiry,
        })

    return access_token, tokens["gmail_address"]


def render_template(template: str, contact: dict, sender_name: str = "") -> str:
    """Replace <variable> placeholders with contact values."""
    replacements = {
        "<first_name>": contact.get("first_name") or "",
        "<last_name>": contact.get("last_name") or "",
        "<company_name>": contact.get("company_name") or "",
        "<title>": contact.get("title") or "",
        "<website>": contact.get("website") or "",
        "<your_name>": sender_name,
        "<type>": contact.get("industry_tag") or "",
    }
    result = template
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)
    return result


def get_draft(db: Client, contact_id: str, template_key: str, sender_name: str = "") -> dict:
    """Render an email draft from a template for a contact.

    template_key: 'didnt_pick_up' or 'interested'
    """
    contact = contact_repo.get_contact(db, contact_id)
    if not contact:
        raise ValueError(f"Contact {contact_id} not found")

    global_settings = settings_repo.get_settings(db)

    subject_key = f"email_subject_{template_key}"
    body_key = f"email_template_{template_key}"
    subject_template = global_settings.get(subject_key, "")
    body_template = global_settings.get(body_key, "")

    return {
        "to": contact.get("email", ""),
        "subject": render_template(subject_template, contact, sender_name),
        "body": render_template(body_template, contact, sender_name),
        "contact_name": f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip(),
    }


def send_email(
    db: Client,
    user_id: str,
    contact_id: str,
    subject: str,
    body: str,
    outcome_context: str | None = None,
) -> dict:
    """Send an email via the user's connected Gmail and log it."""
    contact = contact_repo.get_contact(db, contact_id)
    if not contact:
        raise ValueError(f"Contact {contact_id} not found")

    recipient = contact.get("email")
    if not recipient:
        raise ValueError(f"Contact {contact_id} has no email address")

    access_token, gmail_address = _get_valid_access_token(db, user_id)

    msg = MIMEText(body, "plain")
    msg["To"] = recipient
    msg["From"] = gmail_address
    msg["Subject"] = subject

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()

    resp = httpx.post(
        GMAIL_SEND_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        json={"raw": raw},
    )
    resp.raise_for_status()
    gmail_msg_id = resp.json().get("id", "")

    log = email_repo.create_email_log(db, {
        "contact_id": contact_id,
        "user_id": user_id,
        "gmail_address": gmail_address,
        "recipient_email": recipient,
        "subject": subject,
        "body": body,
        "outcome_context": outcome_context,
    })

    logger.info("Email sent to %s (contact %s) via %s, Gmail ID %s", recipient, contact_id, gmail_address, gmail_msg_id)
    return {"email_log": log, "gmail_message_id": gmail_msg_id}


# ---------------------------------------------------------------------------
# Email tracking / sync
# ---------------------------------------------------------------------------

def _get_header(headers: list[dict], name: str) -> str:
    """Extract a header value from Gmail API headers list."""
    for h in headers:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _fetch_gmail_messages(access_token: str, query: str, max_results: int = 50) -> list[dict]:
    """List + batch-get messages matching a Gmail search query."""
    resp = httpx.get(
        GMAIL_MESSAGES_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"q": query, "maxResults": max_results},
        timeout=30,
    )
    resp.raise_for_status()
    message_stubs = resp.json().get("messages", [])
    if not message_stubs:
        return []

    messages = []
    for stub in message_stubs:
        detail = httpx.get(
            f"{GMAIL_MESSAGES_URL}/{stub['id']}",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"format": "metadata", "metadataHeaders": "From,To,Subject,Date"},
            timeout=15,
        )
        if detail.status_code != 200:
            continue
        messages.append(detail.json())
    return messages


def sync_emails_for_contact(
    db: Client, user_id: str, contact_email: str, contact_id: str,
) -> int:
    """Sync Gmail messages to/from a specific contact email. Returns new count."""
    try:
        access_token, gmail_address = _get_valid_access_token(db, user_id)
    except ValueError:
        return 0

    query = f"from:{contact_email} OR to:{contact_email}"
    try:
        messages = _fetch_gmail_messages(access_token, query)
    except Exception as exc:
        logger.warning("Gmail fetch failed for %s: %s", contact_email, exc)
        return 0

    if not messages:
        return 0

    rows = []
    for msg in messages:
        headers = msg.get("payload", {}).get("headers", [])
        from_addr = _get_header(headers, "From")
        to_addr = _get_header(headers, "To")
        subject = _get_header(headers, "Subject")
        date_str = _get_header(headers, "Date")

        from_lower = from_addr.lower()
        direction = "received" if contact_email.lower() in from_lower else "sent"

        internal_ts = int(msg.get("internalDate", "0"))
        msg_date = datetime.fromtimestamp(internal_ts / 1000, tz=timezone.utc).isoformat()

        rows.append({
            "user_id": user_id,
            "contact_id": contact_id,
            "gmail_message_id": msg["id"],
            "from_address": from_addr,
            "to_address": to_addr,
            "subject": subject,
            "snippet": msg.get("snippet", "")[:500],
            "direction": direction,
            "message_date": msg_date,
        })

    return email_tracking_repo.upsert_tracked_emails(db, rows)


def sync_emails_for_user(db: Client, user_id: str) -> int:
    """Sync emails for all contacts the user has interacted with."""
    call_contacts = (
        db.table("call_logs")
        .select("contact_id")
        .eq("user_id", user_id)
        .not_.is_("contact_id", "null")
        .execute()
    )
    email_contacts = (
        db.table("email_logs")
        .select("contact_id")
        .eq("user_id", user_id)
        .not_.is_("contact_id", "null")
        .execute()
    )

    contact_ids = set()
    for row in (call_contacts.data or []):
        contact_ids.add(row["contact_id"])
    for row in (email_contacts.data or []):
        contact_ids.add(row["contact_id"])

    if not contact_ids:
        return 0

    contacts = (
        db.table("contacts")
        .select("id, email")
        .in_("id", list(contact_ids))
        .not_.is_("email", "null")
        .execute()
    )

    total = 0
    for c in (contacts.data or []):
        if not c.get("email"):
            continue
        try:
            total += sync_emails_for_contact(db, user_id, c["email"], c["id"])
        except Exception as exc:
            logger.warning("Sync failed for contact %s: %s", c["id"], exc)
    return total
