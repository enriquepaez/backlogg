from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator


class LogIn(BaseModel):
    """Request body for POST /{type}/{slug}/log.

    ``logged_on`` defaults to the current date (resolved in the service) when
    omitted. A future date is rejected here — at the schema layer, not in the
    route or service — same as every other request-shape validation in the
    codebase (Pydantic v2 models as the single source of truth for input
    constraints).
    """

    logged_on: date | None = Field(default=None)
    rewatch: bool = Field(default=False)
    note: str | None = Field(default=None, max_length=10000)

    @field_validator("logged_on")
    @classmethod
    def logged_on_not_in_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("logged_on cannot be in the future")
        return value


class LogOut(BaseModel):
    """Response of POST /{type}/{slug}/log and each item of GET .../log."""

    id: int
    item_type: str
    slug: str
    logged_on: date
    rewatch: bool
    note: str | None
    created_at: datetime


class LogListOut(BaseModel):
    items: list[LogOut]
    total: int
    page: int
    limit: int


class UserLogItemOut(BaseModel):
    item_type: str
    title: str
    slug: str
    poster_url: str | None


class UserLogOut(BaseModel):
    id: int
    item: UserLogItemOut
    logged_on: date
    rewatch: bool
    note: str | None
    created_at: datetime


class UserLogListOut(BaseModel):
    items: list[UserLogOut]
    total: int
    page: int
    limit: int
