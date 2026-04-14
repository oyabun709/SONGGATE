"""
Email notifications via Resend.

Sends scan-complete and scan-failed emails to the org's primary contact.
Falls back to a no-op if RESEND_API_KEY is not configured (dev environments).

Usage
─────
    from services.email_service import send_scan_complete, send_scan_failed
    await send_scan_complete(org_name, recipient_email, scan_id, grade, score, total_issues, dashboard_url)
    await send_scan_failed(org_name, recipient_email, scan_id, error_hint, dashboard_url)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from config import settings

logger = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"
_TIMEOUT = 10.0


async def _send(to: str, subject: str, html: str) -> None:
    """Post one email via the Resend REST API. No-ops when key is absent."""
    if not settings.resend_api_key:
        logger.debug("RESEND_API_KEY not set — skipping email to %s: %s", to, subject)
        return

    payload: dict[str, Any] = {
        "from": settings.email_from,
        "to": [to],
        "subject": subject,
        "html": html,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _RESEND_URL,
                json=payload,
                headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            )
            if resp.status_code >= 400:
                logger.warning(
                    "Resend API error %d sending to %s: %s",
                    resp.status_code, to, resp.text[:200],
                )
    except Exception as exc:
        logger.warning("Failed to send email to %s: %s", to, exc)


def _grade_color(grade: str) -> str:
    return {"PASS": "#16a34a", "WARN": "#d97706", "FAIL": "#dc2626"}.get(grade, "#64748b")


def _grade_bg(grade: str) -> str:
    return {"PASS": "#f0fdf4", "WARN": "#fffbeb", "FAIL": "#fef2f2"}.get(grade, "#f8fafc")


async def send_scan_complete(
    org_name: str,
    recipient_email: str,
    scan_id: str,
    release_title: str,
    grade: str,
    readiness_score: int,
    total_issues: int,
    critical_count: int,
    warning_count: int,
    dashboard_url: str,
) -> None:
    """Send a scan-complete notification with grade + issue summary."""
    color = _grade_color(grade)
    bg = _grade_bg(grade)
    subject = f"Scan complete — {release_title} [{grade}]"

    issues_summary = ""
    if total_issues:
        parts = []
        if critical_count:
            parts.append(f"<strong style='color:#dc2626'>{critical_count} critical</strong>")
        if warning_count:
            parts.append(f"<strong style='color:#d97706'>{warning_count} warnings</strong>")
        info = total_issues - critical_count - warning_count
        if info:
            parts.append(f"{info} info")
        issues_summary = f"<p style='margin:0 0 16px;color:#475569;font-size:14px'>{', '.join(parts)} found.</p>"
    else:
        issues_summary = "<p style='margin:0 0 16px;color:#16a34a;font-size:14px'>No issues found — release looks good.</p>"

    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:40px 16px">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1)">
        <!-- Header -->
        <tr><td style="background:#4f46e5;padding:24px 32px">
          <p style="margin:0;color:#fff;font-size:18px;font-weight:700">⚡ RopQA</p>
        </td></tr>
        <!-- Body -->
        <tr><td style="padding:32px">
          <h1 style="margin:0 0 8px;font-size:22px;color:#0f172a">Scan complete</h1>
          <p style="margin:0 0 24px;color:#64748b;font-size:14px">{release_title} · {org_name}</p>

          <!-- Grade badge -->
          <div style="background:{bg};border:1px solid {color}30;border-radius:8px;padding:16px 20px;margin:0 0 24px;display:inline-block">
            <span style="font-size:28px;font-weight:800;color:{color}">{grade}</span>
            <span style="font-size:16px;color:#64748b;margin-left:12px">Readiness score: <strong style="color:#0f172a">{readiness_score}</strong></span>
          </div>

          {issues_summary}

          <a href="{dashboard_url}/scans/{scan_id}"
             style="display:inline-block;background:#4f46e5;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600">
            View full results →
          </a>
        </td></tr>
        <!-- Footer -->
        <tr><td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:16px 32px">
          <p style="margin:0;color:#94a3b8;font-size:12px">RopQA · Scan ID: {scan_id[:8]}… · <a href="{dashboard_url}" style="color:#4f46e5;text-decoration:none">Open dashboard</a></p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
    await _send(recipient_email, subject, html)


async def send_scan_failed(
    org_name: str,
    recipient_email: str,
    scan_id: str,
    release_title: str,
    error_hint: str,
    dashboard_url: str,
) -> None:
    """Send a scan-failed notification."""
    subject = f"Scan failed — {release_title}"
    html = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:40px 16px">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1)">
        <tr><td style="background:#4f46e5;padding:24px 32px">
          <p style="margin:0;color:#fff;font-size:18px;font-weight:700">⚡ RopQA</p>
        </td></tr>
        <tr><td style="padding:32px">
          <h1 style="margin:0 0 8px;font-size:22px;color:#0f172a">Scan failed</h1>
          <p style="margin:0 0 24px;color:#64748b;font-size:14px">{release_title} · {org_name}</p>

          <div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:16px 20px;margin:0 0 24px">
            <p style="margin:0;color:#dc2626;font-size:14px;font-weight:600">The scan could not complete</p>
            <p style="margin:8px 0 0;color:#64748b;font-size:13px">{error_hint}</p>
          </div>

          <a href="{dashboard_url}/scans/{scan_id}"
             style="display:inline-block;background:#4f46e5;color:#fff;text-decoration:none;padding:12px 24px;border-radius:8px;font-size:14px;font-weight:600">
            View scan details →
          </a>
        </td></tr>
        <tr><td style="background:#f8fafc;border-top:1px solid #e2e8f0;padding:16px 32px">
          <p style="margin:0;color:#94a3b8;font-size:12px">RopQA · Scan ID: {scan_id[:8]}… · <a href="{dashboard_url}" style="color:#4f46e5;text-decoration:none">Open dashboard</a></p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>
"""
    await _send(recipient_email, subject, html)
