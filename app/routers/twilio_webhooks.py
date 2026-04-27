from __future__ import annotations

from fastapi import APIRouter, Form, Response

from app.config import settings
from app.dependencies import CurrentUserDep

router = APIRouter(prefix="/twilio", tags=["twilio"])


@router.post("/voice")
def voice_webhook(To: str = Form(""), Country: str = Form("US")):
    """TwiML endpoint for browser-initiated calls.

    Selects the caller ID based on the contact's country so recipients
    see a local number. Falls back to the default US number.
    """
    numbers = settings.twilio_phone_numbers
    caller_id = numbers.get(Country, settings.twilio_phone_number)
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial callerId="{caller_id}">
        <Number>{To}</Number>
    </Dial>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@router.post("/status")
def status_callback(CallSid: str = Form(""), CallStatus: str = Form("")):
    """Receive call status updates from Twilio."""
    return {"call_sid": CallSid, "status": CallStatus}


@router.get("/numbers")
def get_available_numbers(current_user: CurrentUserDep):
    """Return country codes that have a local Twilio number configured."""
    numbers = settings.twilio_phone_numbers
    return {
        "countries": sorted(numbers.keys()),
        "default": "US",
    }
