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


@router.get("/me")
def get_me(current_user: CurrentUserDep):
    return current_user
