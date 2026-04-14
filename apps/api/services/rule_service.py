from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.rule import Rule
from schemas.rule import RuleCreate, RuleUpdate


class RuleService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list_all(self) -> list[Rule]:
        result = await self.db.execute(select(Rule).order_by(Rule.created_at.desc()))
        return list(result.scalars().all())

    async def get(self, rule_id: str) -> Rule | None:
        return await self.db.get(Rule, rule_id)

    async def create(self, payload: RuleCreate) -> Rule:
        rule = Rule(**payload.model_dump())
        self.db.add(rule)
        await self.db.commit()
        await self.db.refresh(rule)
        return rule

    async def update(self, rule_id: str, payload: RuleUpdate) -> Rule | None:
        rule = await self.get(rule_id)
        if not rule:
            return None
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(rule, field, value)
        await self.db.commit()
        await self.db.refresh(rule)
        return rule

    async def delete(self, rule_id: str) -> None:
        rule = await self.get(rule_id)
        if rule:
            await self.db.delete(rule)
            await self.db.commit()
