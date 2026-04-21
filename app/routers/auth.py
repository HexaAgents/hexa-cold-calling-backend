from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.dependencies import SupabaseDep, CurrentUserDep

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: dict


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, db: SupabaseDep):
    try:
        result = db.auth.sign_in_with_password({
            "email": body.email,
            "password": body.password,
        })
        user = result.user
        session = result.session
        if not user or not session:
            raise HTTPException(status_code=401, detail="Invalid credentials")

        return LoginResponse(
            access_token=session.access_token,
            refresh_token=session.refresh_token,
            user={
                "id": str(user.id),
                "email": user.email,
                "full_name": (user.user_metadata or {}).get("full_name", ""),
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Login failed: {exc}")


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponse(BaseModel):
    access_token: str
    refresh_token: str


@router.post("/refresh", response_model=RefreshResponse)
def refresh_token(body: RefreshRequest, db: SupabaseDep):
    try:
        result = db.auth.refresh_session(body.refresh_token)
        session = result.session
        if not session:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        return RefreshResponse(
            access_token=session.access_token,
            refresh_token=session.refresh_token,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Token refresh failed: {exc}")


@router.get("/me")
def get_me(current_user: CurrentUserDep):
    return current_user


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
def change_password(body: ChangePasswordRequest, current_user: CurrentUserDep, db: SupabaseDep):
    try:
        db.auth.sign_in_with_password({
            "email": current_user["email"],
            "password": body.current_password,
        })
    except Exception:
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    try:
        db.auth.admin.update_user_by_id(
            current_user["id"],
            {"password": body.new_password},
        )
        return {"detail": "Password updated successfully"}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to update password: {exc}")
