"""
Integration tests for the billing tier gate and API key management.

Tests the dependency logic directly (no HTTP layer needed) to verify:
  - require_tier() blocks below-minimum tiers
  - check_scan_limit() raises 429 when limit reached
  - API key hash/prefix generation is correct
  - Billing router API key CRUD (create / list / revoke)
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from models.api_key import APIKey
from models.organization import Organization, OrgTier, TIER_SCAN_LIMIT


# ─── DB fixture ───────────────────────────────────────────────────────────────

TEST_DB_URL = "sqlite+aiosqlite://"


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DB_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _org(tier: OrgTier = OrgTier.starter, scan_count: int = 0) -> Organization:
    return Organization(
        id=uuid.uuid4(),
        clerk_org_id=f"org_{uuid.uuid4().hex[:8]}",
        name="Test",
        tier=tier,
        settings={},
        scan_count_current_period=scan_count,
    )


# ─── Tier gate ────────────────────────────────────────────────────────────────

class TestRequireTier:
    @pytest.mark.asyncio
    async def test_passes_when_tier_met(self):
        from dependencies.tier_gate import require_tier
        org = _org(OrgTier.pro)
        dep = require_tier(OrgTier.pro)
        result = dep(org)
        assert result is org

    @pytest.mark.asyncio
    async def test_passes_higher_tier(self):
        from dependencies.tier_gate import require_tier
        org = _org(OrgTier.enterprise)
        dep = require_tier(OrgTier.pro)
        assert dep(org) is org

    @pytest.mark.asyncio
    async def test_blocks_lower_tier(self):
        from dependencies.tier_gate import require_tier
        org = _org(OrgTier.starter)
        dep = require_tier(OrgTier.pro)
        with pytest.raises(HTTPException) as exc_info:
            dep(org)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_starter_can_access_starter_features(self):
        from dependencies.tier_gate import require_tier
        org = _org(OrgTier.starter)
        dep = require_tier(OrgTier.starter)
        assert dep(org) is org


class TestCheckScanLimit:
    @pytest.mark.asyncio
    async def test_allows_when_under_limit(self):
        from dependencies.tier_gate import check_scan_limit
        org = _org(OrgTier.starter, scan_count=10)
        # Should not raise
        await check_scan_limit(org)

    @pytest.mark.asyncio
    async def test_raises_429_at_limit(self):
        from dependencies.tier_gate import check_scan_limit
        limit = TIER_SCAN_LIMIT[OrgTier.starter]
        org = _org(OrgTier.starter, scan_count=limit)
        with pytest.raises(HTTPException) as exc_info:
            await check_scan_limit(org)
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    async def test_enterprise_unlimited(self):
        from dependencies.tier_gate import check_scan_limit
        # Enterprise has limit -1 — should never raise regardless of count
        org = _org(OrgTier.enterprise, scan_count=999_999)
        await check_scan_limit(org)

    @pytest.mark.asyncio
    async def test_allows_exactly_one_below_limit(self):
        from dependencies.tier_gate import check_scan_limit
        limit = TIER_SCAN_LIMIT[OrgTier.pro]
        org = _org(OrgTier.pro, scan_count=limit - 1)
        await check_scan_limit(org)


# ─── API key generation ───────────────────────────────────────────────────────

class TestAPIKeyGeneration:
    def test_key_format(self):
        from routers.billing import _generate_api_key
        plaintext, prefix, key_hash = _generate_api_key()
        assert plaintext.startswith("ropqa_sk_")
        assert prefix == plaintext[:16]
        assert len(prefix) == 16
        assert key_hash == hashlib.sha256(plaintext.encode()).hexdigest()
        assert len(key_hash) == 64

    def test_keys_are_unique(self):
        from routers.billing import _generate_api_key
        keys = {_generate_api_key()[0] for _ in range(50)}
        assert len(keys) == 50  # all unique

    def test_prefix_is_safe_to_display(self):
        """Prefix must not contain the secret portion (past position 16)."""
        from routers.billing import _generate_api_key
        for _ in range(10):
            plaintext, prefix, _ = _generate_api_key()
            assert plaintext[:16] == prefix
            # The full key is longer than the prefix
            assert len(plaintext) > len(prefix)


# ─── API key CRUD ─────────────────────────────────────────────────────────────

class TestAPIKeyCRUD:
    @pytest.mark.asyncio
    async def test_create_and_retrieve(self, db: AsyncSession):
        from routers.billing import _generate_api_key
        org = _org(OrgTier.pro)
        db.add(org)
        await db.commit()

        plaintext, prefix, key_hash = _generate_api_key()
        key = APIKey(
            org_id=org.id,
            name="CI pipeline",
            key_prefix=prefix,
            key_hash=key_hash,
            created_by="user_test",
        )
        db.add(key)
        await db.commit()

        from sqlalchemy import select
        result = await db.scalar(select(APIKey).where(APIKey.org_id == org.id))
        assert result is not None
        assert result.key_prefix == prefix
        assert result.revoked is False

    @pytest.mark.asyncio
    async def test_revoke(self, db: AsyncSession):
        from routers.billing import _generate_api_key
        org = _org(OrgTier.pro)
        db.add(org)
        await db.commit()

        _, prefix, key_hash = _generate_api_key()
        key = APIKey(
            org_id=org.id,
            name="To revoke",
            key_prefix=prefix,
            key_hash=key_hash,
        )
        db.add(key)
        await db.commit()

        key.revoked = True
        key.revoked_at = datetime.now(timezone.utc)
        await db.commit()

        await db.refresh(key)
        assert key.revoked is True
        assert key.revoked_at is not None

    @pytest.mark.asyncio
    async def test_hash_lookup_matches(self, db: AsyncSession):
        """Verify the public API lookup pattern: hash the token, find by hash."""
        from routers.billing import _generate_api_key
        from sqlalchemy import select

        org = _org(OrgTier.enterprise)
        db.add(org)
        await db.commit()

        plaintext, prefix, key_hash = _generate_api_key()
        key = APIKey(org_id=org.id, name="Lookup test", key_prefix=prefix, key_hash=key_hash)
        db.add(key)
        await db.commit()

        # Simulate what public_api._get_api_key_org does
        incoming_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        found = await db.scalar(
            select(APIKey).where(
                APIKey.key_hash == incoming_hash,
                APIKey.revoked.is_(False),
            )
        )
        assert found is not None
        assert found.key_prefix == prefix

    @pytest.mark.asyncio
    async def test_revoked_key_not_found(self, db: AsyncSession):
        """Revoked keys must not be returned in hash lookups."""
        from routers.billing import _generate_api_key
        from sqlalchemy import select

        org = _org(OrgTier.pro)
        db.add(org)
        await db.commit()

        plaintext, prefix, key_hash = _generate_api_key()
        key = APIKey(
            org_id=org.id,
            name="Revoked",
            key_prefix=prefix,
            key_hash=key_hash,
            revoked=True,
        )
        db.add(key)
        await db.commit()

        incoming_hash = hashlib.sha256(plaintext.encode()).hexdigest()
        found = await db.scalar(
            select(APIKey).where(
                APIKey.key_hash == incoming_hash,
                APIKey.revoked.is_(False),
            )
        )
        assert found is None


# ─── Scan limit / tier boundary ───────────────────────────────────────────────

class TestTierBoundaries:
    def test_starter_scan_limit(self):
        assert TIER_SCAN_LIMIT[OrgTier.starter] == 50

    def test_pro_scan_limit(self):
        assert TIER_SCAN_LIMIT[OrgTier.pro] == 500

    def test_enterprise_unlimited(self):
        assert TIER_SCAN_LIMIT[OrgTier.enterprise] == -1

    def test_allowed_layers_starter(self):
        org = _org(OrgTier.starter)
        assert set(org.allowed_layers) == {"ddex", "metadata"}

    def test_allowed_layers_pro(self):
        org = _org(OrgTier.pro)
        assert "fraud" in org.allowed_layers
        assert "audio" in org.allowed_layers
        assert "artwork" in org.allowed_layers

    def test_allowed_layers_enterprise(self):
        org = _org(OrgTier.enterprise)
        assert len(org.allowed_layers) == 6
