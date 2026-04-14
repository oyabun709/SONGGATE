from datetime import datetime
from pydantic import BaseModel


class RuleCreate(BaseModel):
    name: str
    description: str | None = None
    rule_type: str
    expression: str
    enabled: bool = True


class RuleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    expression: str | None = None
    enabled: bool | None = None


class RuleRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    description: str | None
    rule_type: str
    expression: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
