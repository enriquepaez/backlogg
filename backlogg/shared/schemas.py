from pydantic import BaseModel, ConfigDict


class CreditOut(BaseModel):
    person_name: str
    person_slug: str
    profile_url: str | None
    role: str
    character_name: str | None
    billing_order: int | None

    model_config = ConfigDict(from_attributes=True)
