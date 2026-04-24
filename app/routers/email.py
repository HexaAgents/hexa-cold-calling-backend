from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.config import settings
from app.dependencies import SupabaseDep, CurrentUserDep
from app.repositories import email_repo
from app.services import email_service

router = APIRouter(prefix="/email", tags=["email"])


class SendEmailRequest(BaseModel):
    contact_id: str
    subject: str
    body: str
    outcome_context: str | None = None


class DraftRequest(BaseModel):
    contact_id: str
    template_key: str = "didnt_pick_up"


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------

def _redirect_uri(request: Request) -> str:
    """Build the OAuth redirect URI from the current request."""
    if settings.backend_public_url:
        return f"{settings.backend_public_url}/email/oauth/callback"
    return str(request.url_for("gmail_oauth_callback"))


@router.get("/oauth/url")
def gmail_oauth_url(request: Request, current_user: CurrentUserDep):
    redirect_uri = _redirect_uri(request)
    url = email_service.get_oauth_url(current_user["id"], redirect_uri)
    return {"url": url}


@router.get("/oauth/callback", name="gmail_oauth_callback")
def gmail_oauth_callback(request: Request, db: SupabaseDep, code: str, state: str):
    """Google redirects here after user consent."""
    user_id = state
    redirect_uri = _redirect_uri(request)
    try:
        token_data = email_service.exchange_code(code, redirect_uri)
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token", "")
        expires_in = token_data.get("expires_in", 3600)

        gmail_address = email_service.get_gmail_address(access_token)

        from datetime import datetime, timedelta, timezone
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

        email_repo.upsert_gmail_tokens(db, user_id, {
            "gmail_address": gmail_address,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_expiry": expiry,
        })

        frontend = settings.frontend_url.rstrip("/")
        return RedirectResponse(f"{frontend}/settings?gmail=connected")
    except Exception as exc:
        frontend = settings.frontend_url.rstrip("/")
        return RedirectResponse(f"{frontend}/settings?gmail=error&detail={exc}")


@router.get("/oauth/status")
def gmail_oauth_status(current_user: CurrentUserDep, db: SupabaseDep):
    tokens = email_repo.get_gmail_tokens(db, current_user["id"])
    if tokens:
        return {"connected": True, "gmail_address": tokens["gmail_address"]}
    return {"connected": False, "gmail_address": None}


@router.delete("/oauth/disconnect")
def gmail_oauth_disconnect(current_user: CurrentUserDep, db: SupabaseDep):
    email_repo.delete_gmail_tokens(db, current_user["id"])
    return {"disconnected": True}


# ---------------------------------------------------------------------------
# Email compose & send
# ---------------------------------------------------------------------------

@router.post("/draft")
def get_email_draft(body: DraftRequest, current_user: CurrentUserDep, db: SupabaseDep):
    sender_name = (current_user.get("full_name") or "").split()[0] if current_user.get("full_name") else ""
    try:
        return email_service.get_draft(db, body.contact_id, body.template_key, sender_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/send")
def send_email(body: SendEmailRequest, current_user: CurrentUserDep, db: SupabaseDep):
    try:
        return email_service.send_email(
            db,
            current_user["id"],
            body.contact_id,
            body.subject,
            body.body,
            body.outcome_context,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Email send failed: {exc}")


@router.get("/logs/{contact_id}")
def get_email_logs(contact_id: str, current_user: CurrentUserDep, db: SupabaseDep):
    return email_repo.get_email_logs_for_contact(db, contact_id)
