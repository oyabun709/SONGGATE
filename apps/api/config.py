import re as _re
from typing import ClassVar

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_SSL_MODES = {"require", "verify-ca", "verify-full", "allow", "prefer"}
_STRIP_PARAMS = {"channel_binding", "sslmode", "ssl", "connect_timeout"}


def _clean_asyncpg_url(url: str) -> tuple[str, bool]:
    """Rewrite a postgresql:// URL to postgresql+asyncpg://, strip libpq-only
    query params, and return (cleaned_url, ssl_required)."""
    ssl_required = False
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            url = "postgresql+asyncpg://" + url[len(prefix):]
            break

    # Parse out query string
    if "?" in url:
        base, qs = url.split("?", 1)
        kept_parts: list[str] = []
        for part in qs.split("&"):
            if not part:
                continue
            key, _, val = part.partition("=")
            if key == "sslmode" and val in _SSL_MODES - {"disable"}:
                ssl_required = True
            elif key == "ssl" and val.lower() in ("true", "1", "require"):
                ssl_required = True
            elif key not in _STRIP_PARAMS:
                kept_parts.append(part)
        url = base + ("?" + "&".join(kept_parts) if kept_parts else "")
    return url, ssl_required


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://ropqa:ropqa@localhost:5432/ropqa"
    database_url_requires_ssl: bool = False  # set automatically by validator

    @model_validator(mode="before")
    @classmethod
    def _coerce_database_url(cls, data: dict) -> dict:
        """Rewrite DATABASE_URL to asyncpg scheme and extract SSL requirement."""
        url = data.get("database_url") or data.get("DATABASE_URL") or ""
        if url:
            cleaned, ssl = _clean_asyncpg_url(url)
            data["database_url"] = cleaned
            data.setdefault("database_url_requires_ssl", ssl)
        return data

    # Redis / Celery
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # Storage
    s3_bucket: str = "ropqa-artifacts"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    s3_endpoint_url: str = ""         # Set to http://localhost:4566 for LocalStack

    # Auth (Clerk)
    clerk_secret_key: str = ""
    clerk_jwks_url: str = ""          # e.g. https://<your-clerk-fapi-host>/.well-known/jwks.json
    clerk_webhook_secret: str = ""    # whsec_... from Clerk dashboard → Webhooks

    # Stripe billing
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""         # whsec_… from Stripe Dashboard → Webhooks
    stripe_starter_price_id: str = ""       # price_… for $500/month Starter
    stripe_pro_price_id: str = ""           # price_… for $2,000/month Pro
    stripe_enterprise_price_id: str = ""    # price_… for $8,000/month Enterprise
    frontend_url: str = "http://localhost:3000"

    # Email (Resend)
    resend_api_key: str = ""
    email_from: str = "noreply@ropqa.com"

    # App
    environment: str = "development"
    debug: bool = True

    # Dev-only: admin bootstrap token for creating the first API key.
    # Set to empty string to disable.  Never expose in production.
    admin_token: str = "songgate-dev-admin"

    # Comma-separated Clerk user IDs that have admin access.
    # e.g. ADMIN_USER_IDS=user_abc123,user_xyz456
    admin_user_ids: str = ""

    # Static secret for machine-to-machine admin calls (no Clerk required).
    # Pass as X-Admin-Secret header.  Leave empty to disable.
    admin_secret: str = ""


settings = Settings()
