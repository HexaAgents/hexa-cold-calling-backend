from __future__ import annotations

import logging
from datetime import datetime

from supabase import Client
from twilio.rest import Client as TwilioClient

from app.config import settings
from app.repositories import contact_repo, settings_repo

logger = logging.getLogger(__name__)


def render_template(template: str, contact: dict) -> str:
    """Replace <variable> placeholders with contact values."""
    replacements = {
        "<first_name>": contact.get("first_name") or "",
        "<last_name>": contact.get("last_name") or "",
        "<company_name>": contact.get("company_name") or "",
        "<title>": contact.get("title") or "",
        "<website>": contact.get("website") or "",
    }
    result = template
    for placeholder, value in replacements.items():
        result = result.replace(placeholder, value)
    return result


def send_sms(db: Client, contact_id: str) -> dict:
    """Send an SMS immediately to the contact's mobile phone."""
    contact = contact_repo.get_contact(db, contact_id)
    if not contact:
        raise ValueError(f"Contact {contact_id} not found")

    phone = contact.get("mobile_phone")
    if not phone:
        raise ValueError(f"Contact {contact_id} has no mobile phone number")

    global_settings = settings_repo.get_settings(db)
    template = global_settings.get("sms_template", "")
    body = render_template(template, contact)

    client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
    message = client.messages.create(
        to=phone,
        from_=settings.twilio_phone_number,
        body=body,
    )

    contact_repo.update_contact(db, contact_id, {
        "sms_sent": True,
        "messaging_status": "message_sent",
        "sms_sent_after_calls": contact.get("call_occasion_count", 0),
    })

    logger.info("SMS sent to %s (contact %s): SID %s", phone, contact_id, message.sid)
    return {"message_sid": message.sid, "body": body}


def schedule_sms(db: Client, contact_id: str, scheduled_at: datetime) -> dict:
    """Schedule an SMS for a future date/time."""
    contact = contact_repo.get_contact(db, contact_id)
    if not contact:
        raise ValueError(f"Contact {contact_id} not found")

    if not contact.get("mobile_phone"):
        raise ValueError(f"Contact {contact_id} has no mobile phone number")

    contact_repo.update_contact(db, contact_id, {
        "messaging_status": "to_be_messaged",
        "sms_scheduled_at": scheduled_at.isoformat(),
    })

    return {"scheduled_at": scheduled_at.isoformat(), "contact_id": contact_id}


def process_scheduled_messages(db: Client) -> int:
    """Send all scheduled messages that are due. Returns count sent."""
    contacts = contact_repo.get_contacts_needing_sms(db)
    sent_count = 0

    for contact in contacts:
        try:
            send_sms(db, contact["id"])
            sent_count += 1
        except Exception as exc:
            logger.error("Failed to send scheduled SMS to contact %s: %s", contact["id"], exc)

    return sent_count
