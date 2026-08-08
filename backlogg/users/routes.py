from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.core.email import EmailSender, get_email_sender
from backlogg.core.rate_limit import rate_limit_auth
from backlogg.users import service
from backlogg.users.auth import get_current_user
from backlogg.users.models import User
from backlogg.users.schemas import (
    ForgotPasswordRequest,
    LogoutRequest,
    MessageOut,
    RefreshRequest,
    ResetPasswordRequest,
    TokenPairOut,
    UserCreate,
    UserLogin,
    UserMeOut,
    UserOut,
    UserUpdate,
    VerifyConfirmRequest,
)

auth_router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])


@auth_router.post(
    "/register",
    response_model=UserMeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit_auth)],
)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    return await service.register_user(db, payload)


@auth_router.post(
    "/login",
    response_model=TokenPairOut,
    dependencies=[Depends(rate_limit_auth)],
)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    return await service.login_user(db, payload)


@auth_router.post("/refresh", response_model=TokenPairOut)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)):
    return await service.refresh_tokens(db, payload)


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: LogoutRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await service.logout_user(db, current_user, payload)


# ── Account recovery: email verification ─────────────────────────────────────


@auth_router.post(
    "/verify/request", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED
)
async def request_email_verification(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
):
    return await service.request_email_verification(db, current_user, sender)


@auth_router.post("/verify/confirm", response_model=MessageOut)
async def confirm_email_verification(
    payload: VerifyConfirmRequest, db: AsyncSession = Depends(get_db)
):
    return await service.confirm_email_verification(db, payload)


# ── Account recovery: password reset ─────────────────────────────────────────


@auth_router.post(
    "/password/forgot", response_model=MessageOut, status_code=status.HTTP_202_ACCEPTED
)
async def forgot_password(
    payload: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
    sender: EmailSender = Depends(get_email_sender),
):
    return await service.request_password_reset(db, payload, sender)


@auth_router.post("/password/reset", response_model=MessageOut)
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    return await service.reset_password(db, payload)


# NOTE: "/me" must be registered before "/{username}" — otherwise the
# dynamic route would swallow "/me" as a username.
@users_router.get("/me", response_model=UserMeOut)
async def get_me(current_user: User = Depends(get_current_user)):
    return service.get_current_user_profile(current_user)


@users_router.patch("/me", response_model=UserMeOut)
async def update_me(
    payload: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.update_current_user(db, current_user, payload)


@users_router.get("/{username}", response_model=UserOut)
async def get_user(username: str, db: AsyncSession = Depends(get_db)):
    return await service.get_user_profile(db, username)
