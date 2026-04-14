from datetime import datetime
from pydantic import BaseModel


class RuleCreate(BaseModel):
    id: str                          # e.g. 'spotify.metadata.publisher_required'
    layer: str
    dsp: str | None = None
    title: str
    description: str | None = None
    severity: str                    # critical / warning / info
    category: str
    fix_hint: str | None = None
    doc_url: str | None = None
    active: bool = True
    version: str = "1.0.0"


class RuleUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    severity: str | None = None
    category: str | None = None
    fix_hint: str | None = None
    doc_url: str | None = None
    active: bool | None = None
    version: str | None = None


class RuleRead(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    layer: str
    dsp: str | None
    title: str
    description: str | None
    severity: str
    category: str
    fix_hint: str | None
    doc_url: str | None
    active: bool
    version: str
    created_at: datetime
    updated_at: datetime
