from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql+asyncpg://ropqa:ropqa@localhost:5432/ropqa"

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

    # App
    environment: str = "development"
    debug: bool = True


settings = Settings()
