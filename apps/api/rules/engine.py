"""
Rules engine — evaluates Rule objects against an artifact payload.

The engine uses a registry of handler functions keyed by rule_id (or
rule_id prefix).  Each handler receives the Rule row and an EvalContext
and returns a Finding.

Adding a new rule implementation:

    from rules.engine import register, EvalContext, Finding
    from models.rule import Rule

    @register("universal.audio.sample_rate_minimum")
    def check_sample_rate(rule: Rule, ctx: EvalContext) -> Finding:
        # ctx.metadata holds parsed audio metadata dict
        rate = ctx.metadata.get("sample_rate", 0)
        passed = rate >= 44100
        return Finding(
            rule_id=rule.id,
            rule_name=rule.title,
            passed=passed,
            detail=f"sample rate: {rate} Hz",
        )

If no handler is registered for a rule_id the engine records a
'not_implemented' finding (status = warn) rather than crashing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from models.rule import Rule


# ─── finding ─────────────────────────────────────────────────────────────────

@dataclass
class Finding:
    rule_id: str
    rule_name: str
    passed: bool
    detail: str = ""
    severity: str = "info"          # propagated from the Rule row


# ─── eval context ─────────────────────────────────────────────────────────────

@dataclass
class EvalContext:
    """
    Pre-parsed representations of the artifact.  Populated by build_context();
    individual handlers read only the fields they need.
    """
    raw: bytes = b""
    text: str = ""
    xml_tree: Any = None            # lxml ElementTree, or None
    json_data: Any = None           # parsed JSON object, or None
    metadata: dict = field(default_factory=dict)  # audio/image metadata


def build_context(content: bytes) -> EvalContext:
    ctx = EvalContext(raw=content, text=content.decode("utf-8", errors="replace"))
    try:
        from lxml import etree
        ctx.xml_tree = etree.fromstring(content)
    except Exception:
        pass
    try:
        import json
        ctx.json_data = json.loads(content)
    except Exception:
        pass
    return ctx


# ─── handler registry ─────────────────────────────────────────────────────────

_HandlerFn = Callable[["Rule", EvalContext], Finding]
_REGISTRY: dict[str, _HandlerFn] = {}


def register(rule_id: str) -> Callable[[_HandlerFn], _HandlerFn]:
    """Decorator: register a handler for a specific rule_id."""
    def decorator(fn: _HandlerFn) -> _HandlerFn:
        _REGISTRY[rule_id] = fn
        return fn
    return decorator


def _find_handler(rule_id: str) -> _HandlerFn | None:
    """Exact match, then longest-prefix match."""
    if rule_id in _REGISTRY:
        return _REGISTRY[rule_id]
    # Prefix match: 'universal.audio' would match 'universal.audio.sample_rate_minimum'
    best: tuple[int, _HandlerFn | None] = (0, None)
    for key, fn in _REGISTRY.items():
        if rule_id.startswith(key) and len(key) > best[0]:
            best = (len(key), fn)
    return best[1]


# ─── public API ───────────────────────────────────────────────────────────────

def evaluate_rule(rule: Rule, ctx: EvalContext) -> Finding:
    """
    Evaluate a single rule against ctx.

    Never raises — unregistered rules return a not_implemented finding,
    handler exceptions are caught and returned as error findings.
    """
    handler = _find_handler(rule.id)

    if handler is None:
        return Finding(
            rule_id=rule.id,
            rule_name=rule.title,
            passed=False,
            severity=rule.severity,
            detail="rule handler not yet implemented",
        )

    try:
        finding = handler(rule, ctx)
        finding.severity = rule.severity   # always use the DB value
        return finding
    except Exception as exc:
        return Finding(
            rule_id=rule.id,
            rule_name=rule.title,
            passed=False,
            severity=rule.severity,
            detail=f"evaluation error: {exc}",
        )


def run_all(rules: list[Rule], content: bytes) -> list[Finding]:
    """Run all active rules and return one Finding per rule."""
    ctx = build_context(content)
    return [evaluate_rule(r, ctx) for r in rules if r.active]
