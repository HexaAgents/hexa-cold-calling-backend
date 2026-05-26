from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.dependencies import SupabaseDep, CurrentUserDep
from app.schemas.settings import SettingsOut, SettingsUpdate
from app.repositories import contact_repo, settings_repo

_log = logging.getLogger(__name__)

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

    # The SMS threshold doubles as the "give up after N failed pickups"
    # threshold. Lowering it should retroactively silence contacts that
    # are now over the limit so they stop reappearing in the call tracker.
    # The contacts themselves are kept — only the retry_at is cleared.
    new_threshold = update_data.get("sms_call_threshold")
    if new_threshold is not None and new_threshold != current.get("sms_call_threshold"):
        try:
            silenced = contact_repo.silence_exhausted_didnt_pick_up_contacts(
                db, new_threshold,
            )
            if silenced:
                _log.info(
                    "Silenced %d didn't-pick-up contact(s) at or above new "
                    "threshold of %d.", silenced, new_threshold,
                )
        except Exception as exc:
            _log.warning("Failed to silence over-threshold contacts: %s", exc)

    return SettingsOut(**updated)
