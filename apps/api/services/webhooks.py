"""
Outgoing webhook delivery service.

Signs payloads with HMAC-SHA256:
  X-SONGGATE-Signature: sha256=<hex digest>

Delivery:
  deliver_event() — fire one event to all active endpoints for an org
  _deliver_to_endpoint() — single POST with retry logic

Events:
  scan.complete   — scan finished, grade, score, issue counts
  scan.failed     — scan errored out
  bulk.complete   — bulk registration scan finished
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def generate_webhook_secret() -> str:
    """Return a fresh 32-byte hex webhook signing secret."""
    return secrets.token_hex(32)


def sign_payload(secret: str, payload: bytes) -> str:
    """Return 'sha256=<hex>' HMAC-SHA256 signature."""
    sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


async def deliver_event(
    db: Any,
    org_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    """
    Deliver an event to all active webhook endpoints registered for this org.

    Runs synchronously within the caller's async context.
    Each delivery is logged in webhook_deliveries.
    """
    from sqlalchemy import text

    # Fetch active endpoints for this org
    rows = await db.execute(
        text("""
            SELECT id, url, secret, events
            FROM webhook_endpoints
            WHERE org_id = :org_id AND active = true
        """),
        {"org_id": org_id},
    )
    endpoints = rows.mappings().all()

    if not endpoints:
        return

    for ep in endpoints:
        # Check event filter
        ep_events = ep["events"]
        if ep_events is not None and event_type not in ep_events:
            continue

        await _deliver_to_endpoint(
            db=db,
            endpoint_id=str(ep["id"]),
            url=ep["url"],
            secret=ep["secret"],
            event_type=event_type,
            payload=payload,
        )


async def _deliver_to_endpoint(
    db: Any,
    endpoint_id: str,
    url: str,
    secret: str,
    event_type: str,
    payload: dict[str, Any],
    attempt: int = 1,
) -> None:
    """POST the signed payload to one endpoint and log the delivery."""
    from sqlalchemy import text

    delivery_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    full_payload = {
        "event": event_type,
        "delivered_at": now,
        "data": payload,
    }
    body = json.dumps(full_payload, default=str).encode()
    signature = sign_payload(secret, body)

    status_code: int | None = None
    response_body: str | None = None
    error: str | None = None
    delivery_status = "failed"
    delivered_at = None

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-SONGGATE-Signature": signature,
                    "X-SONGGATE-Event": event_type,
                    "X-SONGGATE-Delivery": delivery_id,
                },
            )
        status_code = resp.status_code
        response_body = resp.text[:2000]  # truncate
        if 200 <= resp.status_code < 300:
            delivery_status = "delivered"
            delivered_at = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        error = str(exc)
        logger.warning("Webhook delivery failed for %s: %s", url, exc)

    await db.execute(
        text("""
            INSERT INTO webhook_deliveries
                (id, endpoint_id, event_type, payload, status_code,
                 response_body, attempt, status, error, delivered_at, created_at)
            VALUES
                (:id, :endpoint_id, :event_type, :payload, :status_code,
                 :response_body, :attempt, :status, :error, :delivered_at, :now)
        """),
        {
            "id":            delivery_id,
            "endpoint_id":   endpoint_id,
            "event_type":    event_type,
            "payload":       json.dumps(full_payload, default=str),
            "status_code":   status_code,
            "response_body": response_body,
            "attempt":       attempt,
            "status":        delivery_status,
            "error":         error,
            "delivered_at":  delivered_at,
            "now":           now,
        },
    )
    await db.commit()
