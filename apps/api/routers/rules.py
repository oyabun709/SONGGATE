from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies.auth import get_current_org
from models.organization import Organization
from schemas.rule import RuleCreate, RuleRead, RuleUpdate
from services.rule_service import RuleService

router = APIRouter()

# Rules are global (seeded from YAML) but reads still require a valid org session.


@router.get("/", response_model=list[RuleRead])
async def list_rules(
    db: AsyncSession = Depends(get_db),
    _org: Organization = Depends(get_current_org),
):
    return await RuleService(db).list_all()


@router.get("/{rule_id}", response_model=RuleRead)
async def get_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    _org: Organization = Depends(get_current_org),
):
    rule = await RuleService(db).get(rule_id)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


@router.post("/", response_model=RuleRead, status_code=status.HTTP_201_CREATED)
async def create_rule(
    payload: RuleCreate,
    db: AsyncSession = Depends(get_db),
    _org: Organization = Depends(get_current_org),
):
    return await RuleService(db).create(payload)


@router.patch("/{rule_id}", response_model=RuleRead)
async def update_rule(
    rule_id: str,
    payload: RuleUpdate,
    db: AsyncSession = Depends(get_db),
    _org: Organization = Depends(get_current_org),
):
    rule = await RuleService(db).update(rule_id, payload)
    if not rule:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Rule not found")
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    _org: Organization = Depends(get_current_org),
):
    await RuleService(db).delete(rule_id)
