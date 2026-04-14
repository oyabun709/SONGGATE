#!/usr/bin/env python3
"""
Seed the rules table from YAML files in rules/dsp/.

Usage:
    python scripts/seed_rules.py [--dry-run] [--reset]

Options:
    --dry-run   Print parsed rules without writing to the database.
    --reset     Delete all existing rules before seeding (full replacement).

The script is idempotent by default: it upserts rules using the rule id as
the conflict target, so re-running after adding new YAML entries is safe.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import yaml
from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

# Make sure the api root is on the path when run from any cwd.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from database import AsyncSessionLocal  # noqa: E402
from models.rule import Rule  # noqa: E402

RULES_DIR = ROOT / "rules" / "dsp"

VALID_SEVERITIES = {"critical", "warning", "info"}
VALID_LAYERS = {"metadata", "audio", "artwork", "packaging", "fingerprint"}


def load_yaml_files() -> list[dict]:
    """
    Parse every *.yml and *.yaml file in rules/dsp/ and return a flat list
    of rule dicts, deduplicated by rule id.

    Loading order: *.yml first, then *.yaml.  When the same rule id appears
    in both a .yml and a .yaml file the .yaml version wins (it is the
    authoritative version with check expressions).
    """
    seen: dict[str, dict] = {}  # rule_id → rule dict (last write wins)

    all_files = sorted(RULES_DIR.glob("*.yml")) + sorted(RULES_DIR.glob("*.yaml"))

    for yaml_file in all_files:
        with yaml_file.open() as fh:
            doc = yaml.safe_load(fh)

        file_version = doc.get("version", "1.0.0")
        file_dsp = doc.get("dsp")  # may be null (universal)

        for entry in doc.get("rules", []):
            rule = {
                "id": entry["id"],
                "layer": entry["layer"],
                "dsp": entry.get("dsp", file_dsp),
                "title": entry["title"],
                "description": entry.get("description"),
                "severity": entry["severity"],
                "category": entry["category"],
                "fix_hint": entry.get("fix_hint"),
                "doc_url": entry.get("doc_url"),
                "active": entry.get("active", True),
                "version": entry.get("version", file_version),
            }
            _validate(rule, yaml_file.name)
            seen[rule["id"]] = rule

    return list(seen.values())


def _validate(rule: dict, source: str) -> None:
    errors = []
    if not rule["id"]:
        errors.append("id is required")
    if rule["severity"] not in VALID_SEVERITIES:
        errors.append(f"severity {rule['severity']!r} not in {VALID_SEVERITIES}")
    if rule["layer"] not in VALID_LAYERS:
        errors.append(f"layer {rule['layer']!r} not in {VALID_LAYERS}")
    if errors:
        raise ValueError(f"[{source}] rule {rule['id']!r}: {'; '.join(errors)}")


async def seed(dry_run: bool = False, reset: bool = False) -> None:
    rules = load_yaml_files()

    if not rules:
        print("No rules found in rules/dsp/ — nothing to seed.")
        return

    print(f"Loaded {len(rules)} rule(s) from {RULES_DIR}")

    if dry_run:
        for r in rules:
            print(f"  [{r['severity']:8s}] {r['id']}")
        print("Dry-run complete — database not modified.")
        return

    async with AsyncSessionLocal() as session:
        if reset:
            await session.execute(delete(Rule))
            await session.commit()
            print("Existing rules deleted (--reset).")

        stmt = pg_insert(Rule).values(rules)
        stmt = stmt.on_conflict_do_update(
            index_elements=["id"],
            set_={
                "layer": stmt.excluded.layer,
                "dsp": stmt.excluded.dsp,
                "title": stmt.excluded.title,
                "description": stmt.excluded.description,
                "severity": stmt.excluded.severity,
                "category": stmt.excluded.category,
                "fix_hint": stmt.excluded.fix_hint,
                "doc_url": stmt.excluded.doc_url,
                "active": stmt.excluded.active,
                "version": stmt.excluded.version,
                "updated_at": text("now()"),
            },
        )
        await session.execute(stmt)
        await session.commit()

    print(f"Upserted {len(rules)} rule(s) successfully.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Rule table from YAML files.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print rules without writing to DB"
    )
    parser.add_argument(
        "--reset", action="store_true", help="Delete all existing rules before seeding"
    )
    args = parser.parse_args()
    asyncio.run(seed(dry_run=args.dry_run, reset=args.reset))


if __name__ == "__main__":
    main()
