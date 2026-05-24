from pydantic import BaseModel, ConfigDict


class CreditOut(BaseModel):
    item_type: str
    item_id: int
    item_slug: str | None
    item_title: str | None
    role: str
    character_name: str | None
    billing_order: int | None

    model_config = ConfigDict(from_attributes=True)


class PersonOut(BaseModel):
    id: int
    name: str
    slug: str
    profile_url: str | None
    credits: list[CreditOut]

    model_config = ConfigDict(from_attributes=True)
