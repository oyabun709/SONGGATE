"""
DSP-specific metadata rules engine.

Architecture
────────────
1. YAML rule files in rules/dsp/ are the source of truth.
2. Each rule can carry an optional ``check`` expression — a small
   expression evaluated against a ReleaseMetadata object.
3. The safe evaluator uses Python's ``ast`` module to parse expressions
   and walks the AST with an explicit whitelist.  eval() is never called.
4. Rules without a ``check`` expression return status="skip".
5. File mtime is polled every 30 s so edits to YAML files take effect
   without a process restart.

Safe expression language
────────────────────────
  Literals:   "string", 42, 3.14, True, False, None, ['a', 'b']
  Variable:   metadata  (the only allowed top-level name)
  Access:     metadata.field_name
  Comparison: ==  !=  <  <=  >  >=  in  not in
  Boolean:    and  or  not
  Functions (whitelisted):
    has_value(x)              – truthy and not just whitespace
    regex_match(x, pattern)   – re.match(pattern, str(x)) is not None
    all_items_match(lst, pat) – every item in lst matches pattern
    no_duplicates(lst)        – no repeated values
    len(x)                    – standard len
    lower(x), upper(x)        – str case helpers
    abs(x)                    – absolute value
"""

from __future__ import annotations

import ast
import logging
import operator
import re
import time
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Data types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ReleaseMetadata:
    """
    Flat, DSP-agnostic metadata snapshot for a single release.

    Field semantics
    ───────────────
    - 0 / "" means "not provided / not yet measured".  Rules that depend on
      optional sub-systems (audio analysis, artwork decode) should guard
      against the zero value in their check expression if desired.
    - ``isrc_list``: one entry per track, in track-number order.
    - ``parental_warning``: "Explicit" | "NotExplicit" | "Clean" | "".
    - ``artwork_color_mode``: "RGB" | "CMYK" | "".
    - ``artwork_format``: "jpeg" | "png" | "".
    """

    # Core release metadata
    title: str = ""
    artist: str = ""
    upc: str = ""
    label: str = ""
    release_date: str = ""       # YYYY-MM-DD
    release_type: str = ""       # Album | Single | EP | …
    genre: str = ""
    language: str = ""           # ISO 639-1, e.g. "en"

    # Rights & publishing
    c_line: str = ""             # e.g. "2024 My Label LLC"
    p_line: str = ""             # e.g. "2024 My Label LLC"
    p_line_year: str = ""        # four-digit year extracted from p_line
    publisher: str = ""          # music publisher / rights holder
    composers: list[str] = field(default_factory=list)
    territory: str = ""          # "Worldwide" or ISO 3166 code list
    commercial_model: str = ""

    # Content advisory
    parental_warning: str = ""   # "Explicit" | "NotExplicit" | "Clean" | ""

    # Artwork (decoded by artwork pipeline; 0 = not yet available)
    artwork_width: int = 0
    artwork_height: int = 0
    artwork_format: str = ""
    artwork_color_mode: str = ""  # "RGB" | "CMYK" | ""

    # Audio (measured by audio analysis pipeline; 0 = not yet available)
    sample_rate: int = 0          # Hz, e.g. 44100
    bit_depth: int = 0            # bits, e.g. 16 or 24
    loudness_lufs: float = 0.0    # integrated loudness (LUFS, negative)
    true_peak_dbtp: float = 0.0   # true peak (dBTP, negative); 0 = not measured

    # Tracks
    tracks: list[dict] = field(default_factory=list)
    isrc_list: list[str] = field(default_factory=list)  # one ISRC per track

    # DSP-specific identifiers
    apple_id: str = ""
    iswc: str = ""                # composition identifier

    # Scheduling
    preorder_date: str = ""

    # Apple-specific
    preview_start_time: int = 0   # seconds into track for 30-s preview
    has_dolby_atmos: bool = False

    # Quality tier
    is_hi_res: bool = False       # 24-bit / 96 kHz+

    # Editorial / discovery
    artist_image_url: str = ""    # HTTPS URL to press photo

    # TikTok / video
    video_codec: str = ""         # "H.264" | "H.265" | ""
    video_width: int = 0
    video_height: int = 0


@dataclass
class RuleDefinition:
    """A rule loaded from a YAML file."""
    id: str
    layer: str
    dsp: str | None            # None → universal
    title: str
    description: str = ""
    severity: str = "warning"  # critical | warning | info
    category: str = ""
    fix_hint: str | None = None
    doc_url: str | None = None
    active: bool = True
    version: str = "1.0.0"
    check: str | None = None   # expression string; None → skip


@dataclass
class RuleResult:
    """Result of evaluating a single rule against a ReleaseMetadata."""
    rule_id: str
    status: str                 # "pass" | "fail" | "skip"
    severity: str               # mirrors rule.severity
    message: str
    fix_hint: str | None = None
    checked_value: Any = None   # the actual value that was evaluated


# ──────────────────────────────────────────────────────────────────────────────
# Safe expression evaluator
# ──────────────────────────────────────────────────────────────────────────────

class EvalError(ValueError):
    """Raised when the expression contains a disallowed construct."""


def _safe_eval(expr: str, metadata: ReleaseMetadata) -> bool:
    """
    Parse and evaluate a check expression against ``metadata``.

    Returns a bool.  Raises EvalError on any disallowed AST node.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:
        raise EvalError(f"Syntax error in expression {expr!r}: {exc}") from exc

    return bool(_eval_node(tree.body, metadata))


# Comparison operator map (ast op type → callable)
_CMP_OPS: dict[type, Callable[[Any, Any], bool]] = {
    ast.Eq:    operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt:    operator.lt,
    ast.LtE:   operator.le,
    ast.Gt:    operator.gt,
    ast.GtE:   operator.ge,
    ast.In:    lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}

# Arithmetic binary operator map (used rarely in expressions)
_BIN_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add:  operator.add,
    ast.Sub:  operator.sub,
    ast.Mult: operator.mul,
    ast.Div:  operator.truediv,
    ast.Mod:  operator.mod,
}

# Whitelisted functions callable from expressions
def _fn_has_value(val: Any) -> bool:
    if val is None:
        return False
    if isinstance(val, str):
        return bool(val.strip())
    if isinstance(val, (list, dict)):
        return len(val) > 0
    return bool(val)


def _fn_regex_match(val: Any, pattern: str) -> bool:
    if not val:
        return False
    return bool(re.match(pattern, str(val)))


def _fn_all_items_match(lst: Any, pattern: str) -> bool:
    if not isinstance(lst, list) or len(lst) == 0:
        return False
    return all(bool(re.match(pattern, str(item))) for item in lst)


def _fn_no_duplicates(lst: Any) -> bool:
    if not isinstance(lst, list):
        return True
    return len(lst) == len(set(lst))


def _fn_contains(val: Any, sub: str) -> bool:
    return sub.lower() in str(val).lower()


_SAFE_FUNCTIONS: dict[str, Callable] = {
    "has_value":        _fn_has_value,
    "regex_match":      _fn_regex_match,
    "all_items_match":  _fn_all_items_match,
    "no_duplicates":    _fn_no_duplicates,
    "contains":         _fn_contains,
    "len":              len,
    "abs":              abs,
    "lower":            lambda x: str(x).lower(),
    "upper":            lambda x: str(x).upper(),
    "str":              str,
    "int":              int,
    "bool":             bool,
}

# Allowed top-level variable names
_ALLOWED_NAMES = {"metadata", "True", "False", "None"}


def _eval_node(node: ast.AST, metadata: ReleaseMetadata) -> Any:  # noqa: PLR0911
    """Recursively evaluate an AST node against the metadata context."""

    # ── Literals ──────────────────────────────────────────────────────────────
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, ast.List):
        return [_eval_node(el, metadata) for el in node.elts]

    if isinstance(node, ast.Tuple):
        return tuple(_eval_node(el, metadata) for el in node.elts)

    # ── Names ─────────────────────────────────────────────────────────────────
    if isinstance(node, ast.Name):
        if node.id == "metadata":
            return metadata
        if node.id == "True":
            return True
        if node.id == "False":
            return False
        if node.id == "None":
            return None
        raise EvalError(f"Unknown variable: {node.id!r}")

    # ── Attribute access (metadata.field) ────────────────────────────────────
    if isinstance(node, ast.Attribute):
        obj = _eval_node(node.value, metadata)
        if obj is not metadata:
            raise EvalError(
                f"Attribute access is only allowed on 'metadata', not {type(obj).__name__!r}"
            )
        attr = node.attr
        if not hasattr(metadata, attr):
            raise EvalError(f"ReleaseMetadata has no field {attr!r}")
        return getattr(metadata, attr)

    # ── Comparisons ──────────────────────────────────────────────────────────
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, metadata)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval_node(comparator, metadata)
            op_fn = _CMP_OPS.get(type(op))
            if op_fn is None:
                raise EvalError(f"Unsupported comparison operator: {type(op).__name__}")
            left = op_fn(left, right)
            if left is False:
                return False
        return left

    # ── Boolean ops ──────────────────────────────────────────────────────────
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            return all(_eval_node(v, metadata) for v in node.values)
        if isinstance(node.op, ast.Or):
            return any(_eval_node(v, metadata) for v in node.values)
        raise EvalError(f"Unsupported boolean op: {type(node.op).__name__}")

    # ── Unary ops ────────────────────────────────────────────────────────────
    if isinstance(node, ast.UnaryOp):
        operand = _eval_node(node.operand, metadata)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        raise EvalError(f"Unsupported unary op: {type(node.op).__name__}")

    # ── Binary ops ───────────────────────────────────────────────────────────
    if isinstance(node, ast.BinOp):
        left = _eval_node(node.left, metadata)
        right = _eval_node(node.right, metadata)
        op_fn = _BIN_OPS.get(type(node.op))
        if op_fn is None:
            raise EvalError(f"Unsupported binary op: {type(node.op).__name__}")
        return op_fn(left, right)

    # ── Whitelisted function calls ────────────────────────────────────────────
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise EvalError("Only simple function calls are allowed (no method calls)")
        fn_name = node.func.id
        fn = _SAFE_FUNCTIONS.get(fn_name)
        if fn is None:
            raise EvalError(
                f"Function {fn_name!r} is not in the allowed function list: "
                f"{sorted(_SAFE_FUNCTIONS)}"
            )
        if node.keywords:
            raise EvalError("Keyword arguments are not allowed in check expressions")
        args = [_eval_node(a, metadata) for a in node.args]
        return fn(*args)

    # ── Anything else is disallowed ───────────────────────────────────────────
    raise EvalError(
        f"Disallowed AST node type: {type(node).__name__}. "
        "Only comparisons, boolean ops, attribute access, literals, and whitelisted "
        "functions are allowed."
    )


# ──────────────────────────────────────────────────────────────────────────────
# YAML loading
# ──────────────────────────────────────────────────────────────────────────────

_RULES_DIR = Path(__file__).resolve().parent.parent.parent / "rules" / "dsp"

_VALID_SEVERITIES = {"critical", "warning", "info"}
_VALID_LAYERS = {"metadata", "audio", "artwork", "packaging", "fingerprint"}


def _load_yaml_rules(rules_dir: Path) -> dict[str, RuleDefinition]:
    """
    Load all *.yml and *.yaml files from rules_dir.

    Returns a dict keyed by rule_id.  When the same rule_id appears in
    multiple files, the .yaml file wins over .yml (*.yaml sorted last).
    """
    rules: dict[str, RuleDefinition] = {}

    # Load .yml first, then .yaml (so .yaml overrides .yml for same rule IDs)
    all_files = sorted(_rules_dir_files(rules_dir, "*.yml")) + sorted(
        _rules_dir_files(rules_dir, "*.yaml")
    )

    for yaml_path in all_files:
        try:
            with yaml_path.open() as fh:
                doc = yaml.safe_load(fh)
        except Exception as exc:
            logger.warning("Failed to load %s: %s", yaml_path, exc)
            continue

        file_version = doc.get("version", "1.0.0")
        file_dsp = doc.get("dsp")  # None for universal

        for entry in doc.get("rules", []):
            try:
                rule_id = entry["id"]
                severity = entry.get("severity", "warning")
                layer = entry.get("layer", "metadata")

                if severity not in _VALID_SEVERITIES:
                    logger.warning(
                        "[%s] rule %r: unknown severity %r — defaulting to 'warning'",
                        yaml_path.name, rule_id, severity
                    )
                    severity = "warning"

                rules[rule_id] = RuleDefinition(
                    id=rule_id,
                    layer=layer,
                    dsp=entry.get("dsp", file_dsp),
                    title=entry.get("title", rule_id),
                    description=entry.get("description", ""),
                    severity=severity,
                    category=entry.get("category", ""),
                    fix_hint=entry.get("fix_hint") or None,
                    doc_url=entry.get("doc_url") or None,
                    active=entry.get("active", True),
                    version=entry.get("version", file_version),
                    check=entry.get("check") or None,
                )
            except Exception as exc:
                logger.warning(
                    "[%s] failed to parse rule entry: %s — %s",
                    yaml_path.name, entry.get("id", "?"), exc
                )

    return rules


def _rules_dir_files(rules_dir: Path, pattern: str):
    if rules_dir.exists():
        yield from rules_dir.glob(pattern)


def _snapshot_mtimes(rules_dir: Path) -> dict[Path, float]:
    mtimes: dict[Path, float] = {}
    for pattern in ("*.yml", "*.yaml"):
        for f in rules_dir.glob(pattern):
            try:
                mtimes[f] = f.stat().st_mtime
            except OSError:
                pass
    return mtimes


# ──────────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────────

_DEFAULT_DSPS = ["spotify", "apple", "youtube", "amazon", "tiktok"]
_HOT_RELOAD_INTERVAL = 30.0  # seconds between mtime checks


class DSPRulesEngine:
    """
    Load YAML rule definitions and evaluate them against ReleaseMetadata.

    Thread-safety: rule evaluation is read-only after load; hot-reload is
    single-threaded (not safe for concurrent writes, fine for async FastAPI).

    Usage::

        engine = DSPRulesEngine()
        results = engine.evaluate(metadata, dsps=["spotify", "apple"])
    """

    def __init__(self, rules_dir: Path | None = None) -> None:
        self._rules_dir = rules_dir or _RULES_DIR
        self._rules: dict[str, RuleDefinition] = {}
        self._file_mtimes: dict[Path, float] = {}
        self._last_reload_check: float = 0.0
        self._load_rules()

    # ── Rule loading ──────────────────────────────────────────────────────────

    def _load_rules(self) -> None:
        self._rules = _load_yaml_rules(self._rules_dir)
        self._file_mtimes = _snapshot_mtimes(self._rules_dir)
        self._last_reload_check = time.monotonic()
        logger.debug("Loaded %d rules from %s", len(self._rules), self._rules_dir)

    def _maybe_reload(self) -> None:
        """Hot-reload: re-read YAML files if any have changed since last check."""
        now = time.monotonic()
        if now - self._last_reload_check < _HOT_RELOAD_INTERVAL:
            return
        self._last_reload_check = now
        current = _snapshot_mtimes(self._rules_dir)
        if current != self._file_mtimes:
            logger.info("YAML rule files changed — reloading")
            self._load_rules()

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def rule_count(self) -> int:
        return len(self._rules)

    def get_rule(self, rule_id: str) -> RuleDefinition | None:
        self._maybe_reload()
        return self._rules.get(rule_id)

    def list_rules(
        self,
        dsp: str | None = None,
        layer: str | None = None,
        active_only: bool = True,
    ) -> list[RuleDefinition]:
        """Return filtered rule definitions."""
        self._maybe_reload()
        out: list[RuleDefinition] = []
        for rule in self._rules.values():
            if active_only and not rule.active:
                continue
            if dsp is not None and rule.dsp != dsp and rule.dsp is not None:
                continue
            if layer is not None and rule.layer != layer:
                continue
            out.append(rule)
        return out

    def evaluate(
        self,
        metadata: ReleaseMetadata,
        dsps: list[str] | None = None,
    ) -> list[RuleResult]:
        """
        Evaluate all active rules for the specified DSPs plus universal rules.

        Args:
            metadata: Release metadata to evaluate against.
            dsps: DSP slugs to include (e.g. ["spotify", "apple"]).
                  Defaults to all five primary DSPs.
                  Universal rules (dsp=null) are always included.

        Returns:
            List of RuleResult — one per evaluated rule (pass/fail/skip).
        """
        self._maybe_reload()
        target_dsps = set(dsps) if dsps is not None else set(_DEFAULT_DSPS)

        results: list[RuleResult] = []
        for rule in self._rules.values():
            if not rule.active:
                continue
            # Include: universal (dsp=None) OR matches a requested DSP
            if rule.dsp is not None and rule.dsp not in target_dsps:
                continue
            results.append(self.evaluate_rule(rule, metadata))

        return results

    def evaluate_rule(
        self,
        rule: RuleDefinition,
        metadata: ReleaseMetadata,
    ) -> RuleResult:
        """
        Safely evaluate a single rule against metadata.

        Never raises — all exceptions are caught and surfaced as
        ``status="fail"`` results with the error in ``message``.
        """
        if not rule.check:
            return RuleResult(
                rule_id=rule.id,
                status="skip",
                severity=rule.severity,
                message=f"{rule.title} — no automated check (manual review required)",
                fix_hint=rule.fix_hint,
            )

        # Extract the checked value for diagnostics
        checked_value = _extract_checked_value(rule.check, metadata)

        try:
            passed = _safe_eval(rule.check, metadata)
        except EvalError as exc:
            return RuleResult(
                rule_id=rule.id,
                status="fail",
                severity=rule.severity,
                message=f"{rule.title} — expression error: {exc}",
                fix_hint=rule.fix_hint,
                checked_value=checked_value,
            )
        except Exception as exc:
            return RuleResult(
                rule_id=rule.id,
                status="fail",
                severity=rule.severity,
                message=f"{rule.title} — evaluation error: {exc}",
                fix_hint=rule.fix_hint,
                checked_value=checked_value,
            )

        return RuleResult(
            rule_id=rule.id,
            status="pass" if passed else "fail",
            severity=rule.severity,
            message=rule.title if passed else f"{rule.title} — check failed",
            fix_hint=None if passed else rule.fix_hint,
            checked_value=checked_value,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Diagnostics helper
# ──────────────────────────────────────────────────────────────────────────────

def _extract_checked_value(expr: str, metadata: ReleaseMetadata) -> Any:
    """
    Best-effort: extract the primary checked value for display in the UI.

    Walks the top-level expression looking for a metadata.field access and
    returns its current value.  Falls back to None on any error.
    """
    try:
        tree = ast.parse(expr, mode="eval")
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "metadata"
                and hasattr(metadata, node.attr)
            ):
                return getattr(metadata, node.attr)
    except Exception:
        pass
    return None
