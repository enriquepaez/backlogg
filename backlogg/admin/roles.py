"""Admin role management — superadmin grants/revokes the admin role.

Deliberate deviation from the rest of /v1/admin/*: every other admin endpoint
is gated solely by the shared X-API-Key secret (no user identity involved).
These two endpoints flip the highest-privilege flag in the system (is_admin),
so on top of the router-level X-API-Key they also require the caller's own
Bearer token and check `caller.is_superadmin` server-side — a frontend that
merely hides the button is not enough.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backlogg.admin import service as admin_service
from backlogg.admin.auth import verify_api_key
from backlogg.admin.schemas import RoleGrantOut
from backlogg.core.database import get_db
from backlogg.users.auth import get_current_user
from backlogg.users.models import User

# Same router-level X-API-Key gate as backlogg.admin.router /
# backlogg.moderation.routes. get_current_user is added per-endpoint below —
# it is not a router-level dependency because it also needs to be evaluated
# (and its 401 raised) before the is_superadmin check runs in the service.
admin_roles_router = APIRouter(
    prefix="/admin", tags=["admin"], dependencies=[Depends(verify_api_key)]
)


@admin_roles_router.post(
    "/users/{username}/grant-admin",
    response_model=RoleGrantOut,
    summary="Grant the admin role",
    description=(
        "Grant `is_admin` to the target user. Requires `X-API-Key` AND a valid "
        "Bearer token for a superadmin caller (`is_superadmin`); 403 otherwise. "
        "Idempotent. 404 if the target user does not exist."
    ),
)
async def grant_admin(
    username: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoleGrantOut:
    return await admin_service.set_user_admin_role(db, current_user, username, is_admin=True)


@admin_roles_router.post(
    "/users/{username}/revoke-admin",
    response_model=RoleGrantOut,
    summary="Revoke the admin role",
    description=(
        "Revoke `is_admin` from the target user. Requires `X-API-Key` AND a valid "
        "Bearer token for a superadmin caller (`is_superadmin`); 403 otherwise. "
        "Idempotent. 404 if the target user does not exist. Self-revocation and "
        "revoking another superadmin are both allowed — see service docstring."
    ),
)
async def revoke_admin(
    username: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> RoleGrantOut:
    return await admin_service.set_user_admin_role(db, current_user, username, is_admin=False)
