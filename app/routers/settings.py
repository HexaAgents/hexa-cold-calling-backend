from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.dependencies import SupabaseDep, CurrentUserDep
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.repositories import settings_repo

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
def get_settings(current_user: CurrentUserDep, db: SupabaseDep):
    data = settings_repo.get_settings(db)
    if not data:
        raise HTTPException(status_code=404, detail="Settings not found")
    return SettingsOut(**data)


@router.put("", response_model=SettingsOut)
def update_settings(body: SettingsUpdate, current_user: CurrentUserDep, db: SupabaseDep):
    current = settings_repo.get_settings(db)
    if not current:
        raise HTTPException(status_code=404, detail="Settings not found")

    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        return SettingsOut(**current)

    updated = settings_repo.update_settings(db, current["id"], update_data)
    if not updated:
        raise HTTPException(status_code=500, detail="Failed to update settings")
    return SettingsOut(**updated)
