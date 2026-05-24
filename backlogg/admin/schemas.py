"""Admin domain — Pydantic v2 schemas."""

from pydantic import BaseModel


class SyncResponse(BaseModel):
    status: str
    type: str
