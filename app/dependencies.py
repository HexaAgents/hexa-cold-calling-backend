from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, HTTPException, Header
from supabase import create_client, Client

from app.config import settings


@lru_cache
def get_supabase() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: Client = Depends(get_supabase),
) -> dict:
    """Validate the JWT from the Authorization header and return user info."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    try:
        user_response = db.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid token")
        user = user_response.user
        return {
            "id": str(user.id),
            "email": user.email,
            "full_name": (user.user_metadata or {}).get("full_name", ""),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {exc}")


SupabaseDep = Annotated[Client, Depends(get_supabase)]
CurrentUserDep = Annotated[dict, Depends(get_current_user)]
