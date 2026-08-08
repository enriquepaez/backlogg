from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.core.database import get_db
from backlogg.users import service
from backlogg.users.auth import get_current_user
from backlogg.users.models import User
from backlogg.users.schemas import (
    LogoutRequest,
    RefreshRequest,
    TokenPairOut,
    UserCreate,
    UserLogin,
    UserMeOut,
    UserOut,
    UserUpdate,
)

auth_router = APIRouter(prefix="/auth", tags=["auth"])
users_router = APIRouter(prefix="/users", tags=["users"])


@auth_router.post("/register", response_model=UserMeOut, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    return await service.register_user(db, payload)


@auth_router.post("/login", response_model=TokenPairOut)
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
