from __future__ import annotations

import logging
from datetime import date

from supabase import Client
from twilio.rest import Client as TwilioClient
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant

from app.config import settings
from app.repositories import call_log_repo, contact_repo, settings_repo

logger = logging.getLogger(__name__)


def generate_twilio_token(user_id: str) -> str:
    """Generate a Twilio Access Token for browser-based calling."""
    token = AccessToken(
        settings.twilio_account_sid,
        settings.twilio_api_key_sid,
        settings.twilio_api_key_secret,
        identity=user_id,
    )
    voice_grant = VoiceGrant(
        outgoing_application_sid=settings.twilio_twiml_app_sid,
        incoming_allow=False,
    )
    token.add_grant(voice_grant)
    return token.to_jwt()


def initiate_bridge_call(phone_number: str, user_phone: str) -> str:
    """Start a Twilio bridge call: calls user's phone, then connects to the contact."""
    client = TwilioClient(settings.twilio_account_sid, settings.twilio_auth_token)
    call = client.calls.create(
        to=user_phone,
        from_=settings.twilio_phone_number,
        url=f"{settings.frontend_url}/api/twilio/connect?to={phone_number}",
    )
    return call.sid


def log_call(
    db: Client,
    contact_id: str,
    user_id: str,
    call_method: str,
    phone_number_called: str | None,
    outcome: str,
) -> dict:
    """Log a call and determine if SMS prompt is needed.

    Returns {call_log, is_new_occasion, sms_prompt_needed, occasion_count}.
    """
    already_called_today = call_log_repo.has_call_today(db, contact_id)
    is_new_occasion = not already_called_today

    call_data = {
        "contact_id": contact_id,
        "user_id": user_id,
        "call_date": date.today().isoformat(),
        "call_method": call_method,
        "phone_number_called": phone_number_called,
        "outcome": outcome,
        "is_new_occasion": is_new_occasion,
    }
    call_log = call_log_repo.create_call_log(db, call_data)

    contact = contact_repo.get_contact(db, contact_id)
    occasion_count = contact.get("call_occasion_count", 0) if contact else 0
    times_called = contact.get("times_called", 0) if contact else 0

    times_called += 1
    update_data: dict = {"call_outcome": outcome, "times_called": times_called}
    if is_new_occasion:
        occasion_count += 1
        update_data["call_occasion_count"] = occasion_count

    contact_repo.update_contact(db, contact_id, update_data)

    sms_prompt_needed = False
    if is_new_occasion and not (contact or {}).get("sms_sent", False):
        global_settings = settings_repo.get_settings(db)
        threshold = global_settings.get("sms_call_threshold", 3)
        if occasion_count >= threshold:
            sms_prompt_needed = True

    return {
        "call_log": call_log,
        "is_new_occasion": is_new_occasion,
        "sms_prompt_needed": sms_prompt_needed,
        "occasion_count": occasion_count,
        "times_called": times_called,
    }
