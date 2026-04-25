"""
Bulk Registration PDF Report Generator

Produces a 5-page PDF for bulk registration scan results:

  Page 1 — Cover: org name, file summary, scan date, score + grade,
            total releases / issues breakdown
  Page 2 — Cross-Release Issues: EAN conflicts, artist variants, ISNI
            discrepancies across the submission (one table, critical first)
  Page 3 — Per-Release Issues: release-level validation problems grouped
            by row number (EAN / artist / title header + issues table)
  Page 4 — Identifier Coverage: ISNI/ISWC coverage stats + missing-
            identifier roster
  Page 5 — Clean Releases: releases with zero score-impacting issues
            (confirmation list for the ops team)

Uses the same ReportLab palette/typography as generator.py.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# ─── Palette (mirrors generator.py) ──────────────────────────────────────────

C_BG          = colors.white
C_TEXT        = colors.HexColor("#0F172A")
C_MUTED       = colors.HexColor("#64748B")
C_BORDER      = colors.HexColor("#E2E8F0")
C_ACCENT      = colors.HexColor("#4F46E5")
C_ACCENT_BG   = colors.HexColor("#EEF2FF")
C_CRITICAL    = colors.HexColor("#DC2626")
C_CRITICAL_BG = colors.HexColor("#FEF2F2")
C_WARNING     = colors.HexColor("#D97706")
C_WARNING_BG  = colors.HexColor("#FFFBEB")
C_INFO        = colors.HexColor("#2563EB")
C_INFO_BG     = colors.HexColor("#EFF6FF")
C_PASS        = colors.HexColor("#059669")
C_PASS_BG     = colors.HexColor("#ECFDF5")
C_ROW_ALT     = colors.HexColor("#F8FAFC")

PAGE_W, PAGE_H = A4
MARGIN_L = 18 * mm
MARGIN_R = 18 * mm
MARGIN_T = 16 * mm
MARGIN_B = 20 * mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R


# ─── Data model ──────────────────────────────────────────────────────────────

@dataclass
class BulkReportData:
    # Metadata
    org_name:        str
    scan_id:         str
    scan_date:       datetime
    filename:        str | None

    # Score
    score:           float
    grade:           str           # "PASS" | "WARN" | "FAIL"
    critical_count:  int
    warning_count:   int
    info_count:      int

    # Totals
    total_releases:       int
    releases_with_issues: int

    # Cross-release issues
    # [{id, severity, rule_id, rule_name, message, fix_hint, affected_ean, affected_rows}]
    cross_release_issues: list[dict[str, Any]] = field(default_factory=list)

    # Per-release issues
    # [{row_number, ean, artist, title, isni, iswc, issues:[{severity, rule_id, message, fix_hint}]}]
    per_release_issues: list[dict[str, Any]] = field(default_factory=list)

    # Identifier coverage
    # {total_releases, with_isni, with_isni_pct, with_iswc, with_iswc_pct,
    #  with_both, with_neither, isni_format_errors, iswc_format_errors}
    identifier_coverage: dict[str, Any] = field(default_factory=dict)

    # All releases (for clean-releases page)
    # [{row_number, ean, artist, title, isni, iswc}]
    all_releases: list[dict[str, Any]] = field(default_factory=list)


# ─── Styles ──────────────────────────────────────────────────────────────────

def _build_styles() -> dict[str, ParagraphStyle]:
    def s(name: str, **kw) -> ParagraphStyle:
        return ParagraphStyle(name=name, **kw)

    return {
        "wordmark": s("wordmark",
            fontName="Helvetica-Bold", fontSize=20, textColor=C_ACCENT,
            alignment=TA_LEFT, spaceAfter=2 * mm),
        "tagline": s("tagline",
            fontName="Helvetica", fontSize=9, textColor=C_MUTED,
            alignment=TA_LEFT, spaceAfter=10 * mm),
        "cover_title": s("cover_title",
            fontName="Helvetica-Bold", fontSize=24, textColor=C_TEXT,
            alignment=TA_LEFT, spaceAfter=2 * mm, leading=28),
        "cover_sub": s("cover_sub",
            fontName="Helvetica", fontSize=13, textColor=C_MUTED,
            alignment=TA_LEFT, spaceAfter=8 * mm),
        "cover_score": s("cover_score",
            fontName="Helvetica-Bold", fontSize=80, textColor=C_TEXT,
            alignment=TA_CENTER, leading=88),
        "cover_grade": s("cover_grade",
            fontName="Helvetica-Bold", fontSize=18, textColor=C_TEXT,
            alignment=TA_CENTER, spaceAfter=4 * mm),
        "cover_meta": s("cover_meta",
            fontName="Helvetica", fontSize=8, textColor=C_MUTED,
            alignment=TA_LEFT, leading=13),
        "section_header": s("section_header",
            fontName="Helvetica-Bold", fontSize=13, textColor=C_ACCENT,
            spaceBefore=6 * mm, spaceAfter=3 * mm),
        "subsection_header": s("subsection_header",
            fontName="Helvetica-Bold", fontSize=10, textColor=C_TEXT,
            spaceBefore=4 * mm, spaceAfter=2 * mm),
        "body": s("body",
            fontName="Helvetica", fontSize=9, textColor=C_TEXT,
            leading=14, spaceAfter=2 * mm),
        "caption": s("caption",
            fontName="Helvetica", fontSize=8, textColor=C_MUTED,
            leading=12, spaceAfter=3 * mm),
        "table_header": s("table_header",
            fontName="Helvetica-Bold", fontSize=8, textColor=C_TEXT,
            alignment=TA_LEFT),
        "table_cell": s("table_cell",
            fontName="Helvetica", fontSize=8, textColor=C_TEXT,
            leading=11, alignment=TA_LEFT),
        "table_cell_mono": s("table_cell_mono",
            fontName="Courier", fontSize=7.5, textColor=C_ACCENT,
            leading=10, alignment=TA_LEFT),
        "fix_hint": s("fix_hint",
            fontName="Helvetica-Oblique", fontSize=8, textColor=C_TEXT,
            leading=11, alignment=TA_LEFT),
        "page_footer": s("page_footer",
            fontName="Helvetica", fontSize=7.5, textColor=C_MUTED,
            alignment=TA_CENTER),
        "clean_cell": s("clean_cell",
            fontName="Helvetica", fontSize=8, textColor=C_PASS,
            leading=11, alignment=TA_LEFT),
    }


# ─── Page callbacks ───────────────────────────────────────────────────────────

def _on_cover(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(C_ACCENT)
    canvas.rect(0, PAGE_H - 5 * mm, PAGE_W, 5 * mm, fill=1, stroke=0)
    canvas.restoreState()


def _on_body(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(C_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_L, PAGE_H - MARGIN_T + 2 * mm, PAGE_W - MARGIN_R, PAGE_H - MARGIN_T + 2 * mm)

    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(C_ACCENT)
    canvas.drawString(MARGIN_L, PAGE_H - MARGIN_T + 4 * mm, "SONGGATE — BULK CATALOG QA")

    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(C_MUTED)
    scan_label = getattr(doc, "_scan_label", "")
    canvas.drawRightString(PAGE_W - MARGIN_R, PAGE_H - MARGIN_T + 4 * mm, scan_label)

    canvas.line(MARGIN_L, MARGIN_B - 4 * mm, PAGE_W - MARGIN_R, MARGIN_B - 4 * mm)
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(C_MUTED)
    canvas.drawCentredString(PAGE_W / 2, MARGIN_B - 9 * mm,
        f"Page {doc.page}  ·  Confidential — generated by SONGGATE · songgate.io")
    canvas.restoreState()


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _safe(s: Any) -> str:
    if s is None:
        return ""
    text = str(s)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    if len(text) > 100:
        text = text[:97] + "…"
    return text


def _th(text: str, ST: dict) -> Paragraph:
    return Paragraph(text, ST["table_header"])


def _tc(text: str, ST: dict, mono: bool = False) -> Paragraph:
    style = ST["table_cell_mono"] if mono else ST["table_cell"]
    return Paragraph(_safe(text), style)


def _sev_color(severity: str) -> colors.Color:
    return {"critical": C_CRITICAL, "warning": C_WARNING, "info": C_INFO}.get(severity, C_MUTED)


def _sev_bg(severity: str) -> colors.Color:
    return {"critical": C_CRITICAL_BG, "warning": C_WARNING_BG, "info": C_INFO_BG}.get(severity, C_ROW_ALT)


def _alt_rows(n_rows: int, n_cols: int, start_row: int = 1) -> list:
    cmds = []
    for i in range(start_row, n_rows):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), C_ROW_ALT))
    return cmds


BASE_TABLE_STYLE = [
    ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE",    (0, 0), (-1, 0), 8),
    ("BACKGROUND",  (0, 0), (-1, 0), C_ACCENT_BG),
    ("TEXTCOLOR",   (0, 0), (-1, 0), C_TEXT),
    ("ROWBACKGROUND", (0, 0), (-1, 0), C_ACCENT_BG),
    ("LINEBELOW",   (0, 0), (-1, 0), 0.5, C_BORDER),
    ("LINEBELOW",   (0, 1), (-1, -1), 0.3, C_BORDER),
    ("LEFTPADDING",  (0, 0), (-1, -1), 4),
    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ("TOPPADDING",   (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
    ("VALIGN",       (0, 0), (-1, -1), "TOP"),
]


# ─── Section builders ─────────────────────────────────────────────────────────

def _build_cover(data: BulkReportData, ST: dict) -> list:
    grade_color = {
        "PASS": C_PASS,
        "WARN": C_WARNING,
        "FAIL": C_CRITICAL,
    }.get(data.grade, C_TEXT)

    score_style = ParagraphStyle("cs", parent=ST["cover_score"], textColor=grade_color)
    grade_style = ParagraphStyle("cg", parent=ST["cover_grade"], textColor=grade_color)

    date_str = data.scan_date.strftime("%B %d, %Y")
    stories = [
        Paragraph("SONGGATE", ST["wordmark"]),
        Paragraph("Bulk Catalog QA Report", ST["tagline"]),
        HRFlowable(width=CONTENT_W, thickness=0.5, color=C_BORDER, spaceAfter=6 * mm),
        Paragraph(_safe(data.org_name or "Bulk Scan"), ST["cover_title"]),
        Paragraph(_safe(data.filename or "Bulk Registration File"), ST["cover_sub"]),
        Spacer(1, 8 * mm),
        Paragraph(f"{int(data.score)}", score_style),
        Paragraph(data.grade, grade_style),
        Spacer(1, 6 * mm),
    ]

    # Summary stats table
    stats_data = [
        [_th("Metric", ST), _th("Value", ST)],
        [_tc("Total Releases", ST), _tc(str(data.total_releases), ST)],
        [_tc("Releases with Issues", ST), _tc(str(data.releases_with_issues), ST)],
        [_tc("Critical Issues", ST), _tc(str(data.critical_count), ST)],
        [_tc("Warnings", ST),         _tc(str(data.warning_count), ST)],
        [_tc("Info Notices", ST),     _tc(str(data.info_count), ST)],
        [_tc("Cross-Release Issues", ST), _tc(str(len(data.cross_release_issues)), ST)],
        [_tc("Scan Date", ST),        _tc(date_str, ST)],
        [_tc("Scan ID", ST),          _tc(data.scan_id[:8], ST)],
    ]
    col_w = [CONTENT_W * 0.55, CONTENT_W * 0.45]
    stats_table = Table(stats_data, colWidths=col_w)
    stats_table.setStyle(TableStyle(BASE_TABLE_STYLE + _alt_rows(len(stats_data), 2)))
    stories.append(stats_table)

    # ISNI/ISWC quick stats
    cov = data.identifier_coverage
    if cov:
        stories.append(Spacer(1, 6 * mm))
        stories.append(Paragraph("Identifier Coverage", ST["subsection_header"]))
        cov_data = [
            [_th("Identifier", ST), _th("Count", ST), _th("Coverage", ST)],
            [_tc("ISNI", ST), _tc(str(cov.get("with_isni", 0)), ST),
             _tc(f'{cov.get("with_isni_pct", 0)}%', ST)],
            [_tc("ISWC", ST), _tc(str(cov.get("with_iswc", 0)), ST),
             _tc(f'{cov.get("with_iswc_pct", 0)}%', ST)],
        ]
        cov_table = Table(cov_data, colWidths=[CONTENT_W * 0.4, CONTENT_W * 0.3, CONTENT_W * 0.3])
        cov_table.setStyle(TableStyle(BASE_TABLE_STYLE + _alt_rows(3, 3)))
        stories.append(cov_table)

    stories.append(Spacer(1, 4 * mm))
    stories.append(Paragraph(
        "This report was generated by SONGGATE on-demand. It is confidential and intended "
        "for the account holder only.",
        ST["caption"],
    ))
    return stories


def _build_cross_release(data: BulkReportData, ST: dict) -> list:
    stories = [Paragraph("Cross-Release Issues", ST["section_header"])]
    issues = data.cross_release_issues

    if not issues:
        stories.append(Paragraph(
            "No cross-release issues detected. All EANs and artist identifiers "
            "are consistent across this submission.",
            ST["body"],
        ))
        return stories

    stories.append(Paragraph(
        f"{len(issues)} issue(s) span multiple releases in this submission.",
        ST["caption"],
    ))

    header = [
        _th("Sev", ST), _th("Rule", ST), _th("EAN", ST),
        _th("Message", ST), _th("Fix", ST),
    ]
    col_w = [
        CONTENT_W * 0.07,
        CONTENT_W * 0.14,
        CONTENT_W * 0.16,
        CONTENT_W * 0.36,
        CONTENT_W * 0.27,
    ]

    rows = [header]
    row_styles: list[tuple] = []
    # Sort critical first
    sorted_issues = sorted(issues, key=lambda x: 0 if x.get("severity") == "critical" else 1)

    for idx, issue in enumerate(sorted_issues, start=1):
        sev = issue.get("severity", "info")
        rows.append([
            _tc(sev[:4].upper(), ST),
            _tc(issue.get("rule_id", ""), ST, mono=True),
            _tc(issue.get("affected_ean") or "", ST, mono=True),
            _tc(issue.get("message", ""), ST),
            _tc(issue.get("fix_hint") or "", ST),
        ])
        row_styles.append(("TEXTCOLOR", (0, idx), (0, idx), _sev_color(sev)))
        row_styles.append(("FONTNAME",  (0, idx), (0, idx), "Helvetica-Bold"))

    table = Table(rows, colWidths=col_w, repeatRows=1)
    table.setStyle(TableStyle(BASE_TABLE_STYLE + _alt_rows(len(rows), len(col_w)) + row_styles))
    stories.append(table)
    return stories


def _build_per_release(data: BulkReportData, ST: dict) -> list:
    stories = [Paragraph("Per-Release Issues", ST["section_header"])]
    per_release = data.per_release_issues

    if not per_release:
        stories.append(Paragraph(
            "No per-release issues detected.",
            ST["body"],
        ))
        return stories

    stories.append(Paragraph(
        f"{len(per_release)} release(s) have individual validation issues.",
        ST["caption"],
    ))

    for entry in per_release:
        row_num = entry.get("row_number", "?")
        ean    = entry.get("ean", "")
        artist = entry.get("artist", "")
        title  = entry.get("title", "")
        entry_issues = entry.get("issues", [])

        header_text = (
            f"Row {row_num} — {_safe(artist)} · {_safe(title)}"
            + (f" ({_safe(ean)})" if ean else "")
        )

        header = [
            _th("Sev", ST), _th("Rule", ST),
            _th("Message", ST), _th("Fix Hint", ST),
        ]
        col_w = [
            CONTENT_W * 0.08,
            CONTENT_W * 0.17,
            CONTENT_W * 0.42,
            CONTENT_W * 0.33,
        ]

        rows = [header]
        row_styles: list[tuple] = []
        for idx, issue in enumerate(entry_issues, start=1):
            sev = issue.get("severity", "info")
            rows.append([
                _tc(sev[:4].upper(), ST),
                _tc(issue.get("rule_id", ""), ST, mono=True),
                _tc(issue.get("message", ""), ST),
                _tc(issue.get("fix_hint") or "—", ST),
            ])
            row_styles.append(("TEXTCOLOR", (0, idx), (0, idx), _sev_color(sev)))
            row_styles.append(("FONTNAME",  (0, idx), (0, idx), "Helvetica-Bold"))

        table = Table(rows, colWidths=col_w, repeatRows=1)
        table.setStyle(TableStyle(BASE_TABLE_STYLE + _alt_rows(len(rows), len(col_w)) + row_styles))

        stories.append(KeepTogether([
            Paragraph(header_text, ST["subsection_header"]),
            table,
            Spacer(1, 3 * mm),
        ]))

    return stories


def _build_identifier_coverage(data: BulkReportData, ST: dict) -> list:
    stories = [Paragraph("Identifier Coverage", ST["section_header"])]
    cov = data.identifier_coverage

    if not cov:
        stories.append(Paragraph("No identifier coverage data available.", ST["body"]))
        return stories

    total = cov.get("total_releases", 0)
    with_isni    = cov.get("with_isni", 0)
    with_iswc    = cov.get("with_iswc", 0)
    with_both    = cov.get("with_both", 0)
    with_neither = cov.get("with_neither", 0)
    isni_pct     = cov.get("with_isni_pct", 0)
    iswc_pct     = cov.get("with_iswc_pct", 0)
    isni_errs    = cov.get("isni_format_errors", 0)
    iswc_errs    = cov.get("iswc_format_errors", 0)

    stories.append(Paragraph(
        "ISNI and ISWC coverage across all releases in this submission. "
        "Higher coverage improves downstream chart tracking, royalty routing, "
        "and DSP delivery matching via Luminate Data Enrichment.",
        ST["body"],
    ))

    cov_data = [
        [_th("Identifier", ST), _th("Present", ST), _th("Coverage %", ST), _th("Format Errors", ST)],
        [_tc("ISNI", ST),        _tc(str(with_isni), ST),  _tc(f"{isni_pct}%", ST), _tc(str(isni_errs), ST)],
        [_tc("ISWC", ST),        _tc(str(with_iswc), ST),  _tc(f"{iswc_pct}%", ST), _tc(str(iswc_errs), ST)],
        [_tc("Both ISNI+ISWC", ST), _tc(str(with_both), ST), _tc("—", ST), _tc("—", ST)],
        [_tc("Neither", ST),     _tc(str(with_neither), ST), _tc("—", ST), _tc("—", ST)],
        [_tc("Total Releases", ST), _tc(str(total), ST), _tc("—", ST), _tc("—", ST)],
    ]
    col_w = [CONTENT_W * 0.30, CONTENT_W * 0.20, CONTENT_W * 0.25, CONTENT_W * 0.25]
    cov_table = Table(cov_data, colWidths=col_w)
    cov_table.setStyle(TableStyle(BASE_TABLE_STYLE + _alt_rows(len(cov_data), len(col_w))))
    stories.append(cov_table)

    # Missing ISNI roster (from per-release data)
    missing_isni = [
        r for r in data.per_release_issues
        if not r.get("isni")
    ]
    if missing_isni:
        stories.append(Spacer(1, 5 * mm))
        stories.append(Paragraph(
            f"Releases Missing ISNI ({len(missing_isni)})",
            ST["subsection_header"],
        ))
        mh = [_th("Row", ST), _th("EAN", ST), _th("Artist", ST), _th("Title", ST)]
        mrows = [mh] + [
            [
                _tc(str(r.get("row_number", "")), ST),
                _tc(r.get("ean", ""), ST, mono=True),
                _tc(r.get("artist", ""), ST),
                _tc(r.get("title", ""), ST),
            ]
            for r in missing_isni[:50]  # cap at 50 rows
        ]
        if len(missing_isni) > 50:
            mrows.append([
                _tc(f"… and {len(missing_isni) - 50} more", ST),
                _tc("", ST), _tc("", ST), _tc("", ST),
            ])
        mcol_w = [CONTENT_W * 0.08, CONTENT_W * 0.22, CONTENT_W * 0.35, CONTENT_W * 0.35]
        mtable = Table(mrows, colWidths=mcol_w, repeatRows=1)
        mtable.setStyle(TableStyle(BASE_TABLE_STYLE + _alt_rows(len(mrows), len(mcol_w))))
        stories.append(mtable)

    return stories


def _build_clean_releases(data: BulkReportData, ST: dict) -> list:
    stories = [Paragraph("Clean Releases", ST["section_header"])]

    # A release is clean if it has no per-release issues AND it's not in cross-release
    affected_eans: set[str] = set()
    for cr in data.cross_release_issues:
        if cr.get("affected_ean"):
            affected_eans.add(cr["affected_ean"])

    affected_rows: set[int] = {r.get("row_number") for r in data.per_release_issues if r.get("row_number") is not None}

    clean = [
        r for r in data.all_releases
        if r.get("row_number") not in affected_rows
        and r.get("ean") not in affected_eans
    ]

    if not clean:
        stories.append(Paragraph(
            "All releases in this submission have at least one issue. "
            "Resolve the issues listed in the previous sections.",
            ST["body"],
        ))
        return stories

    stories.append(Paragraph(
        f"{len(clean)} of {data.total_releases} releases passed all checks.",
        ST["caption"],
    ))

    header = [_th("Row", ST), _th("EAN", ST), _th("Artist", ST), _th("Title", ST), _th("ISNI", ST)]
    rows   = [header]
    for r in clean:
        rows.append([
            _tc(str(r.get("row_number", "")), ST),
            _tc(r.get("ean", ""), ST, mono=True),
            _tc(r.get("artist", ""), ST),
            _tc(r.get("title", ""), ST),
            _tc(r.get("isni") or "—", ST),
        ])

    col_w = [CONTENT_W * 0.07, CONTENT_W * 0.21, CONTENT_W * 0.30, CONTENT_W * 0.30, CONTENT_W * 0.12]
    table = Table(rows, colWidths=col_w, repeatRows=1)
    clean_styles = [
        ("TEXTCOLOR", (0, 1), (-1, -1), C_PASS),
    ]
    table.setStyle(TableStyle(BASE_TABLE_STYLE + _alt_rows(len(rows), len(col_w)) + clean_styles))
    stories.append(table)

    return stories


# ─── Main builder ─────────────────────────────────────────────────────────────

class BulkReportGenerator:
    def build(self, data: BulkReportData) -> bytes:
        buf = io.BytesIO()
        ST  = _build_styles()

        doc = BaseDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=MARGIN_L,
            rightMargin=MARGIN_R,
            topMargin=MARGIN_T + 6 * mm,
            bottomMargin=MARGIN_B + 2 * mm,
        )
        doc._scan_label = f"Scan {data.scan_id[:8]}"

        cover_frame = Frame(MARGIN_L, MARGIN_B, PAGE_W - MARGIN_L - MARGIN_R,
                            PAGE_H - MARGIN_T - MARGIN_B - 5 * mm, id="cover")
        body_frame  = Frame(MARGIN_L, MARGIN_B + 4 * mm, CONTENT_W,
                            PAGE_H - MARGIN_T - MARGIN_B - 4 * mm, id="body")

        doc.addPageTemplates([
            PageTemplate(id="cover", frames=[cover_frame], onPage=_on_cover),
            PageTemplate(id="body",  frames=[body_frame],  onPage=_on_body),
        ])

        story = []

        # Page 1 — Cover
        story += _build_cover(data, ST)
        story.append(PageBreak())

        # Page 2 — Cross-Release Issues
        story += _build_cross_release(data, ST)
        story.append(PageBreak())

        # Page 3 — Per-Release Issues
        story += _build_per_release(data, ST)
        story.append(PageBreak())

        # Page 4 — Identifier Coverage
        story += _build_identifier_coverage(data, ST)
        story.append(PageBreak())

        # Page 5 — Clean Releases
        story += _build_clean_releases(data, ST)

        doc.build(story)
        return buf.getvalue()
