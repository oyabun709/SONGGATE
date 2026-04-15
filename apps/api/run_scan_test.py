#!/usr/bin/env python3
"""
Trigger and poll a scan using the real ScanOrchestrator.
Same code path as POST /releases/{id}/scan + GET /scans/{id}/results.

Run inside the API container:
    docker exec ropqa-api python3 run_scan_test.py
"""
import asyncio
import json
import sys
import time
import uuid
from datetime import datetime, timezone

RELEASE_ID = "fbb64a1e-3fe4-412d-96f0-d603f5758421"
ORG_ID     = "eaf6c080-db64-49cd-8fe0-b743a7a0b3d8"

SEP = "─" * 64


def log(label, data=None, *, ok=True):
    sym = "✓" if ok else "✗"
    print(f"\n{SEP}\n  {sym}  {label}\n{SEP}")
    if data is not None:
        if isinstance(data, (dict, list)):
            print(json.dumps(data, indent=2, default=str))
        else:
            print(data)


async def main():
    print(f"\n{'═'*64}")
    print("  SONGGATE — Scan Trigger & Poll")
    print(f"  Release: {RELEASE_ID}")
    print(f"{'═'*64}")

    from database import AsyncSessionLocal
    from models.release import Release, ReleaseStatus
    from models.scan import Scan, ScanStatus
    from models.scan_result import ScanResult
    from sqlalchemy import select

    # ── 1. Create a fresh scan row ─────────────────────────────────────────────
    async with AsyncSessionLocal() as db:
        release = await db.scalar(
            select(Release).where(Release.id == uuid.UUID(RELEASE_ID))
        )
        if not release:
            print(f"✗ Release {RELEASE_ID} not found in DB")
            sys.exit(1)

        # Reset release to ingesting so orchestrator accepts it
        release.status = ReleaseStatus.ingesting
        await db.commit()

        scan = Scan(
            id=uuid.uuid4(),
            release_id=uuid.UUID(RELEASE_ID),
            org_id=uuid.UUID(ORG_ID),
            status=ScanStatus.queued,
            layers_run=[],
            created_at=datetime.now(timezone.utc),
        )
        db.add(scan)
        await db.commit()
        await db.refresh(scan)
        scan_id = str(scan.id)

    log("POST /releases/{id}/scan → scan created (queued)", {
        "release_id": RELEASE_ID,
        "scan_id": scan_id,
        "status": "queued",
        "org_id": ORG_ID,
    })

    # ── 2. Run the orchestrator (same as background task in the HTTP handler) ──
    print(f"\n  ⟳  Running scan orchestrator (this takes ~5–15s)…")
    t0 = time.monotonic()

    from services.scan_orchestrator import ScanOrchestrator
    orchestrator = ScanOrchestrator()
    try:
        completed = await orchestrator.run_scan(
            release_id=RELEASE_ID,
            scan_id=scan_id,
            org_id=ORG_ID,
        )
    except Exception as exc:
        log(f"Orchestrator raised: {exc}", ok=False)
        sys.exit(1)

    elapsed = time.monotonic() - t0

    # ── 3. Poll result (simulate GET /scans/{id}) ──────────────────────────────
    async with AsyncSessionLocal() as db:
        scan_row = await db.scalar(
            select(Scan).where(Scan.id == uuid.UUID(scan_id))
        )
        results_rows = list((await db.execute(
            select(ScanResult)
            .where(ScanResult.scan_id == uuid.UUID(scan_id))
            .order_by(ScanResult.severity.desc(), ScanResult.layer)
        )).scalars().all())

    status_sym = "✓" if scan_row.status.value == "complete" else "✗"
    log(f"GET /scans/{{id}} → {scan_row.status.value} ({elapsed:.1f}s)", {
        "scan_id": scan_id,
        "status": scan_row.status.value,
        "started_at": str(scan_row.started_at),
        "completed_at": str(scan_row.completed_at),
    }, ok=(scan_row.status.value == "complete"))

    # ── 4. Score + grade ───────────────────────────────────────────────────────
    grade_color = {"PASS": "🟢", "WARN": "🟡", "FAIL": "🔴"}.get(
        scan_row.grade.value if scan_row.grade else "", "⚪"
    )
    log(f"Readiness Score  {grade_color} {scan_row.grade.value if scan_row.grade else 'N/A'}", {
        "readiness_score": scan_row.readiness_score,
        "grade": scan_row.grade.value if scan_row.grade else None,
        "total_issues": scan_row.total_issues,
        "critical_count": scan_row.critical_count,
        "warning_count": scan_row.warning_count,
        "info_count": scan_row.info_count,
    })

    # ── 5. Layers ──────────────────────────────────────────────────────────────
    all_layers = ["ddex", "metadata", "fraud", "audio", "artwork", "enrichment"]
    ran = set(scan_row.layers_run or [])
    layer_report = {}
    for layer in all_layers:
        layer_results = [r for r in results_rows if r.layer == layer]
        if layer in ran:
            issues = len([r for r in layer_results if r.status.value != "pass"])
            layer_report[layer] = f"ran  — {issues} issue(s)"
        else:
            layer_report[layer] = "skipped (tier)"
    log("Layers", layer_report)

    # ── 6. Issues ─────────────────────────────────────────────────────────────
    issues = [r for r in results_rows if r.status.value != "pass"]
    if not issues:
        log("Issues — none found")
    else:
        issues_out = []
        for r in issues:
            issues_out.append({
                "layer": r.layer,
                "rule_id": r.rule_id,
                "severity": r.severity,
                "status": r.status.value,
                "message": r.message,
                "field_path": r.field_path,
                "actual_value": r.actual_value,
                "fix_hint": r.fix_hint,
                "dsp_targets": r.dsp_targets or [],
            })
        log(f"Issues ({len(issues)} total)", issues_out)

    # ── Summary ────────────────────────────────────────────────────────────────
    print(f"\n{'═'*64}")
    print(f"  {'✅' if scan_row.status.value == 'complete' else '❌'}  Scan complete")
    print(f"  Score:   {scan_row.readiness_score}  |  Grade: {scan_row.grade.value if scan_row.grade else 'N/A'}")
    print(f"  Issues:  {scan_row.critical_count} critical  {scan_row.warning_count} warning  {scan_row.info_count} info")
    print(f"  Layers:  {', '.join(sorted(ran)) or 'none'}")
    print(f"  Elapsed: {elapsed:.1f}s")
    print(f"{'═'*64}\n")


if __name__ == "__main__":
    asyncio.run(main())
