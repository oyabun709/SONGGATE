"""
Rules engine — evaluates a list of Rule objects against an artifact payload.

Supported rule_type values:
  - xpath    : evaluate an XPath expression against an XML/HTML artifact
  - regex    : match a regular expression against raw artifact text
  - semver   : assert the artifact version satisfies a semver constraint
  - json_path: evaluate a JSONPath expression against a JSON artifact
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lxml import etree


@dataclass
class Finding:
    rule_id: str
    rule_name: str
    passed: bool
    detail: str = ""


@dataclass
class EvalContext:
    """Holds parsed representations of the artifact so rules don't re-parse."""

    raw: bytes = b""
    text: str = ""
    xml_tree: Any = None
    json_data: Any = None


def build_context(content: bytes) -> EvalContext:
    ctx = EvalContext(raw=content, text=content.decode("utf-8", errors="replace"))
    try:
        ctx.xml_tree = etree.fromstring(content)
    except etree.XMLSyntaxError:
        pass
    try:
        import json
        ctx.json_data = json.loads(content)
    except Exception:
        pass
    return ctx


def evaluate_rule(rule: Any, ctx: EvalContext) -> Finding:
    try:
        if rule.rule_type == "regex":
            passed = bool(re.search(rule.expression, ctx.text))
            detail = "pattern matched" if passed else "pattern not found"
        elif rule.rule_type == "xpath":
            if ctx.xml_tree is None:
                return Finding(rule.id, rule.name, False, "artifact is not valid XML")
            result = ctx.xml_tree.xpath(rule.expression)
            passed = bool(result)
            detail = f"xpath returned {len(result)} node(s)" if passed else "no nodes matched"
        elif rule.rule_type == "semver":
            # Lightweight semver constraint check — replace with `packaging` if needed
            passed = _check_semver(ctx.text.strip(), rule.expression)
            detail = "version satisfies constraint" if passed else "version does not satisfy constraint"
        elif rule.rule_type == "json_path":
            import jsonpath_ng.ext as jp  # optional dep — add to requirements if used
            expr = jp.parse(rule.expression)
            matches = expr.find(ctx.json_data or {})
            passed = bool(matches)
            detail = f"jsonpath returned {len(matches)} match(es)" if passed else "no matches"
        else:
            return Finding(rule.id, rule.name, False, f"unknown rule_type: {rule.rule_type}")
    except Exception as exc:
        return Finding(rule.id, rule.name, False, f"evaluation error: {exc}")

    return Finding(rule.id, rule.name, passed, detail)


def run_all(rules: list, content: bytes) -> list[Finding]:
    ctx = build_context(content)
    return [evaluate_rule(r, ctx) for r in rules if r.enabled]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_semver(version_str: str, constraint: str) -> bool:
    """
    Minimal semver range check.  Supports operators: >=, <=, >, <, ==, !=
    Example constraint: ">=1.2.0"
    """
    import operator as op_module
    ops = {">=": op_module.ge, "<=": op_module.le, ">": op_module.gt,
           "<": op_module.lt, "==": op_module.eq, "!=": op_module.ne}
    for sym, fn in ops.items():
        if constraint.startswith(sym):
            target = constraint[len(sym):].strip()
            return fn(_parse_ver(version_str), _parse_ver(target))
    return version_str == constraint


def _parse_ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.lstrip("v").split(".")[:3])
