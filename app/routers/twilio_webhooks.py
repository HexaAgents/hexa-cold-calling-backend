from __future__ import annotations

from fastapi import APIRouter, Form, Response

from app.config import settings

router = APIRouter(prefix="/twilio", tags=["twilio"])


@router.post("/voice")
def voice_webhook(To: str = Form("")):
    """TwiML endpoint for browser-initiated calls. Twilio calls this to get instructions."""
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Dial callerId="{settings.twilio_phone_number}">
        <Number>{To}</Number>
    </Dial>
</Response>"""
    return Response(content=twiml, media_type="application/xml")


@router.post("/status")
def status_callback(CallSid: str = Form(""), CallStatus: str = Form("")):
    """Receive call status updates from Twilio."""
    return {"call_sid": CallSid, "status": CallStatus}
