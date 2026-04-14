"""
PDF report generator for ROPQA scan results.

Produces a multi-page PDF suitable for sending to ops teams and labels:

  Page 1  — Cover: logo wordmark, release title/artist, scan date,
            giant readiness score, PASS/WARN/FAIL verdict, summary sentence.

  Page 2  — Score Breakdown: layer-by-layer score table, DSP readiness
            matrix, issue-count summary.

  Page 3+ — Issues Detail: one section per severity band (Critical → Warning
            → Info), rendered as dense reference tables with rule ID, message,
            affected layer, DSP targets, and fix hint.

  Final   — Enrichment Suggestions: missing metadata surfaced from
            MusicBrainz that could improve royalty collection.

Design principles
─────────────────
  • White background, #0F172A (slate-900) body text
  • Indigo (#4F46E5) accent for section headers and rule-ID chips
  • Severity colours: red (#DC2626 critical), amber (#D97706 warning),
    blue (#2563EB info), emerald (#059669 enrichment)
  • Tables over bullet points — easier to scan at a glance
  • No images or web fonts; ReportLab built-ins only for portability

Dependencies
────────────
  Python: reportlab
  System: none (ReportLab is pure-Python)
"""

from __future__ import annotations

import io
import re
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image,
    KeepTogether,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# ──────────────────────────────────────────────────────────────────────────────
# Palette
# ──────────────────────────────────────────────────────────────────────────────

C_BG         = colors.white
C_TEXT       = colors.HexColor("#0F172A")   # slate-900
C_MUTED      = colors.HexColor("#64748B")   # slate-500
C_BORDER     = colors.HexColor("#E2E8F0")   # slate-200
C_ACCENT     = colors.HexColor("#4F46E5")   # indigo-600
C_ACCENT_BG  = colors.HexColor("#EEF2FF")   # indigo-50
C_CRITICAL   = colors.HexColor("#DC2626")   # red-600
C_CRITICAL_BG= colors.HexColor("#FEF2F2")   # red-50
C_WARNING    = colors.HexColor("#D97706")   # amber-600
C_WARNING_BG = colors.HexColor("#FFFBEB")   # amber-50
C_INFO       = colors.HexColor("#2563EB")   # blue-600
C_INFO_BG    = colors.HexColor("#EFF6FF")   # blue-50
C_PASS       = colors.HexColor("#059669")   # emerald-600
C_PASS_BG    = colors.HexColor("#ECFDF5")   # emerald-50
C_WARN_GRADE = colors.HexColor("#B45309")   # amber-700
C_FAIL       = colors.HexColor("#B91C1C")   # red-700
C_ROW_ALT    = colors.HexColor("#F8FAFC")   # slate-50

# ──────────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ReportIssue:
    rule_id: str
    layer: str
    severity: str           # "critical" | "warning" | "info"
    message: str
    fix_hint: str | None
    actual_value: str | None
    field_path: str | None
    dsp_targets: list[str]
    resolved: bool

@dataclass
class ReportSuggestion:
    field: str
    message: str
    fix_hint: str | None
    confidence: str         # "high" | "medium" | "low"
    source_url: str

@dataclass
class ReportData:
    """
    All data needed to render a scan report.  Collected by the Celery task
    before calling ReportGenerator.build().
    """
    # Release info
    release_title: str
    release_artist: str
    release_upc: str | None
    release_date: str | None        # "YYYY-MM-DD" or None

    # Scan metadata
    scan_id: str
    scan_date: datetime
    org_name: str

    # Score
    readiness_score: float          # 0–100
    grade: str                      # "PASS" | "WARN" | "FAIL"
    critical_count: int
    warning_count: int
    info_count: int

    # Per-layer scores (layer → 0–100 float)
    layer_scores: dict[str, float] = field(default_factory=dict)

    # DSP readiness (dsp_slug → "ready" | "issues")
    dsp_readiness: dict[str, str] = field(default_factory=dict)

    # Issues (all non-pass, non-enrichment)
    issues: list[ReportIssue] = field(default_factory=list)

    # Enrichment suggestions
    suggestions: list[ReportSuggestion] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────────────
# Style registry
# ──────────────────────────────────────────────────────────────────────────────

def _build_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()

    def s(name: str, **kw) -> ParagraphStyle:
        return ParagraphStyle(name=name, **kw)

    return {
        # Cover
        "cover_wordmark": s("cover_wordmark",
            fontName="Helvetica-Bold", fontSize=22, textColor=C_ACCENT,
            alignment=TA_LEFT, spaceAfter=2*mm),
        "cover_tagline": s("cover_tagline",
            fontName="Helvetica", fontSize=9, textColor=C_MUTED,
            alignment=TA_LEFT, spaceAfter=10*mm),
        "cover_title": s("cover_title",
            fontName="Helvetica-Bold", fontSize=28, textColor=C_TEXT,
            alignment=TA_LEFT, spaceAfter=2*mm, leading=32),
        "cover_artist": s("cover_artist",
            fontName="Helvetica", fontSize=16, textColor=C_MUTED,
            alignment=TA_LEFT, spaceAfter=8*mm),
        "cover_score": s("cover_score",
            fontName="Helvetica-Bold", fontSize=96, textColor=C_TEXT,
            alignment=TA_CENTER, leading=100),
        "cover_grade": s("cover_grade",
            fontName="Helvetica-Bold", fontSize=22, textColor=C_TEXT,
            alignment=TA_CENTER, spaceAfter=4*mm),
        "cover_summary": s("cover_summary",
            fontName="Helvetica", fontSize=10, textColor=C_MUTED,
            alignment=TA_CENTER, spaceAfter=8*mm, leading=15),
        "cover_meta": s("cover_meta",
            fontName="Helvetica", fontSize=8, textColor=C_MUTED,
            alignment=TA_LEFT, leading=13),

        # Body
        "section_header": s("section_header",
            fontName="Helvetica-Bold", fontSize=13, textColor=C_ACCENT,
            spaceBefore=6*mm, spaceAfter=3*mm),
        "subsection_header": s("subsection_header",
            fontName="Helvetica-Bold", fontSize=10, textColor=C_TEXT,
            spaceBefore=4*mm, spaceAfter=2*mm),
        "body": s("body",
            fontName="Helvetica", fontSize=9, textColor=C_TEXT,
            leading=14, spaceAfter=2*mm),
        "caption": s("caption",
            fontName="Helvetica", fontSize=8, textColor=C_MUTED,
            leading=12, spaceAfter=3*mm),
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
    }


# ──────────────────────────────────────────────────────────────────────────────
# Page templates
# ──────────────────────────────────────────────────────────────────────────────

PAGE_W, PAGE_H = A4
MARGIN_L = 18*mm
MARGIN_R = 18*mm
MARGIN_T = 16*mm
MARGIN_B = 20*mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R


def _on_cover_page(canvas, doc):
    """Draw subtle top accent bar on cover page."""
    canvas.saveState()
    canvas.setFillColor(C_ACCENT)
    canvas.rect(0, PAGE_H - 5*mm, PAGE_W, 5*mm, fill=1, stroke=0)
    canvas.restoreState()


def _on_body_page(canvas, doc):
    """Draw header bar + page footer on body pages."""
    canvas.saveState()

    # Top rule
    canvas.setStrokeColor(C_BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN_L, PAGE_H - MARGIN_T + 2*mm, PAGE_W - MARGIN_R, PAGE_H - MARGIN_T + 2*mm)

    # Header wordmark
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(C_ACCENT)
    canvas.drawString(MARGIN_L, PAGE_H - MARGIN_T + 4*mm, "ROPQA")

    # Header — scan ID (right-aligned)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(C_MUTED)
    scan_label = getattr(doc, "_scan_label", "")
    canvas.drawRightString(PAGE_W - MARGIN_R, PAGE_H - MARGIN_T + 4*mm, scan_label)

    # Bottom rule
    canvas.line(MARGIN_L, MARGIN_B - 4*mm, PAGE_W - MARGIN_R, MARGIN_B - 4*mm)

    # Footer
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(C_MUTED)
    canvas.drawCentredString(PAGE_W / 2, MARGIN_B - 9*mm,
        f"Page {doc.page}  ·  Confidential — generated by ROPQA")
    canvas.restoreState()


# ──────────────────────────────────────────────────────────────────────────────
# Table helpers
# ──────────────────────────────────────────────────────────────────────────────

def _th(text: str, styles: dict) -> Paragraph:
    return Paragraph(text, styles["table_header"])

def _tc(text: str, styles: dict) -> Paragraph:
    return Paragraph(_safe(text), styles["table_cell"])

def _tm(text: str, styles: dict) -> Paragraph:
    return Paragraph(_safe(text), styles["table_cell_mono"])

def _safe(s: Any) -> str:
    """Escape XML special chars and truncate very long strings."""
    if s is None:
        return ""
    text = str(s)
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Wrap long values so cells don't overflow
    if len(text) > 120:
        text = text[:117] + "…"
    return text

def _alt_rows(n_rows: int, n_cols: int, start_row: int = 1) -> list:
    """Return TableStyle commands for alternating row fills."""
    cmds = []
    for i in range(start_row, n_rows):
        if i % 2 == 0:
            cmds.append(("BACKGROUND", (0, i), (-1, i), C_ROW_ALT))
    return cmds


def _severity_color(severity: str) -> colors.Color:
    return {
        "critical": C_CRITICAL,
        "warning": C_WARNING,
        "info": C_INFO,
    }.get(severity, C_MUTED)


def _severity_bg(severity: str) -> colors.Color:
    return {
        "critical": C_CRITICAL_BG,
        "warning": C_WARNING_BG,
        "info": C_INFO_BG,
    }.get(severity, C_ROW_ALT)


# ──────────────────────────────────────────────────────────────────────────────
# Generator
# ──────────────────────────────────────────────────────────────────────────────

LAYER_LABELS = {
    "ddex":       "DDEX / Format",
    "metadata":   "DSP Metadata",
    "fraud":      "Fraud Screening",
    "audio":      "Audio QA",
    "artwork":    "Artwork",
    "enrichment": "Enrichment",
}

DSP_LABELS = {
    "spotify": "Spotify",
    "apple":   "Apple Music",
    "youtube": "YouTube Music",
    "amazon":  "Amazon Music",
    "tiktok":  "TikTok",
}

SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
LAYER_ORDER = ["ddex", "metadata", "fraud", "audio", "artwork"]


class ReportGenerator:
    """
    Builds a professional PDF from a ReportData snapshot.

    Usage::

        gen = ReportGenerator()
        pdf_bytes = gen.build(report_data)
        # then upload pdf_bytes to S3
    """

    def build(self, data: ReportData) -> bytes:
        """Render the full PDF and return as bytes."""
        buf = io.BytesIO()
        styles = _build_styles()

        # DocTemplate with two named page layouts
        doc = BaseDocTemplate(
            buf,
            pagesize=A4,
            leftMargin=MARGIN_L,
            rightMargin=MARGIN_R,
            topMargin=MARGIN_T,
            bottomMargin=MARGIN_B,
            title=f"ROPQA Report — {data.release_title}",
            author="ROPQA",
        )
        doc._scan_label = f"Scan {data.scan_id[:8]}  ·  {data.scan_date.strftime('%Y-%m-%d')}"

        cover_frame = Frame(MARGIN_L, MARGIN_B, CONTENT_W, PAGE_H - MARGIN_T - MARGIN_B,
                            id="cover")
        body_frame  = Frame(MARGIN_L, MARGIN_B, CONTENT_W, PAGE_H - MARGIN_T - MARGIN_B - 8*mm,
                            id="body")

        doc.addPageTemplates([
            PageTemplate(id="Cover", frames=[cover_frame], onPage=_on_cover_page),
            PageTemplate(id="Body",  frames=[body_frame],  onPage=_on_body_page),
        ])

        story: list = []

        # ── Page 1: Cover ──────────────────────────────────────────────────
        story += self._cover_page(data, styles)

        # ── Page 2: Score Breakdown ────────────────────────────────────────
        story += [NextPageTemplate("Body"), PageBreak()]
        story += self._score_breakdown_page(data, styles)

        # ── Page 3+: Issues Detail ─────────────────────────────────────────
        active_issues = [i for i in data.issues if not i.resolved]
        if active_issues:
            story += [PageBreak()]
            story += self._issues_pages(active_issues, styles)

        # ── Final: Enrichment Suggestions ─────────────────────────────────
        if data.suggestions:
            story += [PageBreak()]
            story += self._enrichment_page(data.suggestions, styles)

        doc.build(story)
        return buf.getvalue()

    # ── Cover page ────────────────────────────────────────────────────────────

    def _cover_page(self, data: ReportData, styles: dict) -> list:
        story = []

        # Vertical padding to push score to visual center
        story.append(Spacer(1, 20*mm))

        # Wordmark
        story.append(Paragraph("ROPQA", styles["cover_wordmark"]))
        story.append(Paragraph("Release QA Autopilot", styles["cover_tagline"]))
        story.append(HRFlowable(width=CONTENT_W, thickness=1, color=C_BORDER,
                                spaceBefore=0, spaceAfter=6*mm))

        # Release info
        story.append(Paragraph(_safe(data.release_title), styles["cover_title"]))
        story.append(Paragraph(_safe(data.release_artist), styles["cover_artist"]))

        # Meta row
        meta_parts = [f"Scan date: {data.scan_date.strftime('%B %d, %Y')}"]
        if data.release_upc:
            meta_parts.append(f"UPC: {data.release_upc}")
        if data.release_date:
            meta_parts.append(f"Release date: {data.release_date}")
        meta_parts.append(f"Organisation: {_safe(data.org_name)}")
        story.append(Paragraph("  ·  ".join(meta_parts), styles["cover_meta"]))

        story.append(Spacer(1, 16*mm))
        story.append(HRFlowable(width=CONTENT_W, thickness=0.5, color=C_BORDER,
                                spaceBefore=0, spaceAfter=14*mm))

        # Giant score
        score_text = str(round(data.readiness_score))
        grade_color = {
            "PASS": C_PASS, "WARN": C_WARNING, "FAIL": C_FAIL
        }.get(data.grade, C_TEXT)
        score_style = ParagraphStyle(
            "score_big",
            parent=styles["cover_score"],
            textColor=grade_color,
        )
        story.append(Paragraph(score_text, score_style))
        story.append(Paragraph("/100", ParagraphStyle(
            "score_denom", fontName="Helvetica", fontSize=18,
            textColor=C_MUTED, alignment=TA_CENTER, spaceAfter=2*mm)))

        # Grade badge
        grade_bg = {
            "PASS": C_PASS_BG, "WARN": C_WARNING_BG, "FAIL": C_CRITICAL_BG
        }.get(data.grade, C_ROW_ALT)
        grade_style = ParagraphStyle(
            "grade_cover",
            parent=styles["cover_grade"],
            textColor=grade_color,
            backColor=grade_bg,
            borderPadding=(3, 12, 3, 12),
            borderRadius=4,
        )
        story.append(Paragraph(data.grade, grade_style))
        story.append(Spacer(1, 6*mm))

        # Summary sentence
        summary = self._summary_sentence(data)
        story.append(Paragraph(summary, styles["cover_summary"]))

        story.append(Spacer(1, 10*mm))
        story.append(HRFlowable(width=CONTENT_W, thickness=0.5, color=C_BORDER,
                                spaceBefore=0, spaceAfter=4*mm))

        # Bottom issue counts
        counts_data = [
            [
                Paragraph(f"<b>{data.critical_count}</b>", ParagraphStyle(
                    "cc", fontName="Helvetica-Bold", fontSize=20, textColor=C_CRITICAL,
                    alignment=TA_CENTER)),
                Paragraph(f"<b>{data.warning_count}</b>", ParagraphStyle(
                    "wc", fontName="Helvetica-Bold", fontSize=20, textColor=C_WARNING,
                    alignment=TA_CENTER)),
                Paragraph(f"<b>{data.info_count}</b>", ParagraphStyle(
                    "ic", fontName="Helvetica-Bold", fontSize=20, textColor=C_INFO,
                    alignment=TA_CENTER)),
            ],
            [
                Paragraph("Critical", ParagraphStyle("cl", fontName="Helvetica", fontSize=9,
                    textColor=C_MUTED, alignment=TA_CENTER)),
                Paragraph("Warnings", ParagraphStyle("wl", fontName="Helvetica", fontSize=9,
                    textColor=C_MUTED, alignment=TA_CENTER)),
                Paragraph("Info", ParagraphStyle("il", fontName="Helvetica", fontSize=9,
                    textColor=C_MUTED, alignment=TA_CENTER)),
            ],
        ]
        col_w = CONTENT_W / 3
        counts_table = Table(counts_data, colWidths=[col_w, col_w, col_w])
        counts_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(counts_table)

        # Footer disclaimer
        story.append(Spacer(1, 8*mm))
        story.append(Paragraph(
            "This report is confidential and intended for the named recipient only. "
            "Generated automatically by ROPQA — Release QA Autopilot.",
            ParagraphStyle("disc", fontName="Helvetica", fontSize=7,
                           textColor=C_MUTED, alignment=TA_CENTER)
        ))

        return story

    def _summary_sentence(self, data: ReportData) -> str:
        """One-sentence plain-English verdict."""
        score = round(data.readiness_score)
        if data.grade == "PASS":
            return (
                f"This release scored {score}/100 and meets all critical requirements "
                f"across the {len(data.dsp_readiness)} checked DSPs — it is ready for delivery."
            )
        elif data.grade == "WARN":
            return (
                f"This release scored {score}/100. While no blocking issues were found, "
                f"{data.warning_count} warning{'s' if data.warning_count != 1 else ''} should be "
                f"addressed before delivery to maximise platform acceptance."
            )
        else:
            return (
                f"This release scored {score}/100 and has {data.critical_count} critical "
                f"issue{'s' if data.critical_count != 1 else ''} that must be resolved before "
                f"delivery. See the Issues Detail section for fix guidance."
            )

    # ── Score breakdown page ──────────────────────────────────────────────────

    def _score_breakdown_page(self, data: ReportData, styles: dict) -> list:
        story = []
        story.append(Paragraph("Score Breakdown", styles["section_header"]))
        story.append(Paragraph(
            f"Scan completed {data.scan_date.strftime('%B %d, %Y at %H:%M UTC')}  ·  "
            f"Scan ID: {data.scan_id[:8]}",
            styles["caption"]
        ))

        # ── Layer scores table ─────────────────────────────────────────────
        story.append(Paragraph("Layer Scores", styles["subsection_header"]))

        headers = ["Layer", "Score", "Issues", "Status"]
        col_w = [60*mm, 28*mm, 28*mm, CONTENT_W - 60*mm - 28*mm - 28*mm]

        rows = [[_th(h, styles) for h in headers]]
        for layer in LAYER_ORDER + ["enrichment"]:
            score = data.layer_scores.get(layer, 100.0)
            layer_issues = [i for i in data.issues
                            if i.layer == layer and not i.resolved]
            issues_str = str(len(layer_issues)) if layer_issues else "—"
            if layer == "enrichment":
                status_str = f"{len(data.suggestions)} suggestion{'s' if len(data.suggestions) != 1 else ''}"
                bar_color = C_PASS
            elif score >= 80:
                status_str = "PASS"
                bar_color = C_PASS
            elif score >= 60:
                status_str = "WARN"
                bar_color = C_WARNING
            else:
                status_str = "FAIL"
                bar_color = C_FAIL

            rows.append([
                _tc(LAYER_LABELS.get(layer, layer.title()), styles),
                Paragraph(f"<b>{round(score)}</b>", ParagraphStyle(
                    "ls", fontName="Helvetica-Bold", fontSize=9,
                    textColor=bar_color, alignment=TA_LEFT)),
                _tc(issues_str, styles),
                Paragraph(f"<b>{status_str}</b>", ParagraphStyle(
                    "st", fontName="Helvetica-Bold", fontSize=8,
                    textColor=bar_color, alignment=TA_LEFT)),
            ])

        layer_table = Table(rows, colWidths=col_w)
        layer_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_ACCENT),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, 0), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_ROW_ALT]),
            ("GRID", (0, 0), (-1, -1), 0.25, C_BORDER),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.append(layer_table)
        story.append(Spacer(1, 6*mm))

        # ── DSP readiness matrix ───────────────────────────────────────────
        story.append(Paragraph("DSP Readiness Matrix", styles["subsection_header"]))
        story.append(Paragraph(
            "Indicates whether this release currently meets each platform's requirements. "
            "'Ready' means no critical issues found for that DSP.",
            styles["caption"]
        ))

        if data.dsp_readiness:
            dsp_headers = ["Platform", "Status", "Blocking Issues"]
            # Count critical issues per DSP
            dsp_critical: dict[str, int] = {}
            for issue in data.issues:
                if issue.severity == "critical" and not issue.resolved:
                    for dsp in (issue.dsp_targets or []):
                        dsp_critical[dsp] = dsp_critical.get(dsp, 0) + 1

            dsp_col_w = [55*mm, 35*mm, CONTENT_W - 55*mm - 35*mm]
            dsp_rows = [[_th(h, styles) for h in dsp_headers]]

            for dsp_slug, readiness in sorted(data.dsp_readiness.items()):
                is_ready = readiness == "ready"
                status_color = C_PASS if is_ready else C_FAIL
                critical_n = dsp_critical.get(dsp_slug, 0)
                dsp_rows.append([
                    _tc(DSP_LABELS.get(dsp_slug, dsp_slug.title()), styles),
                    Paragraph(
                        f"<b>{'✓  Ready' if is_ready else '✗  Needs fixes'}</b>",
                        ParagraphStyle("dsp_s", fontName="Helvetica-Bold", fontSize=8,
                                       textColor=status_color, alignment=TA_LEFT)
                    ),
                    _tc(str(critical_n) + " critical issue" + ("s" if critical_n != 1 else "")
                        if critical_n else "None", styles),
                ])

            dsp_table = Table(dsp_rows, colWidths=dsp_col_w)
            dsp_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), C_ACCENT),
                ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
                ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",   (0, 0), (-1, 0), 8),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_ROW_ALT]),
                ("GRID", (0, 0), (-1, -1), 0.25, C_BORDER),
                ("LEFTPADDING",  (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING",   (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]))
            story.append(dsp_table)
        else:
            story.append(Paragraph("No DSP-specific data available.", styles["caption"]))

        story.append(Spacer(1, 6*mm))

        # ── Issue count summary ────────────────────────────────────────────
        story.append(Paragraph("Issue Count Summary", styles["subsection_header"]))

        sum_data = [
            [_th("Severity", styles), _th("Open", styles),
             _th("Resolved", styles), _th("Total", styles)],
        ]
        for sev in ("critical", "warning", "info"):
            all_sev = [i for i in data.issues if i.severity == sev]
            open_sev = [i for i in all_sev if not i.resolved]
            sum_data.append([
                Paragraph(sev.title(), ParagraphStyle(
                    f"sev_{sev}", fontName="Helvetica-Bold", fontSize=8,
                    textColor=_severity_color(sev), alignment=TA_LEFT)),
                _tc(str(len(open_sev)), styles),
                _tc(str(len(all_sev) - len(open_sev)), styles),
                _tc(str(len(all_sev)), styles),
            ])

        sum_col_w = [60*mm, 30*mm, 30*mm, CONTENT_W - 60*mm - 30*mm - 30*mm]
        sum_table = Table(sum_data, colWidths=sum_col_w)
        sum_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_ACCENT),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, 0), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_ROW_ALT]),
            ("GRID", (0, 0), (-1, -1), 0.25, C_BORDER),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING",   (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ]))
        story.append(sum_table)

        return story

    # ── Issues detail pages ───────────────────────────────────────────────────

    def _issues_pages(self, issues: list[ReportIssue], styles: dict) -> list:
        story = []
        story.append(Paragraph("Issues Detail", styles["section_header"]))
        story.append(Paragraph(
            "All open (unresolved) issues, grouped by severity. "
            "Address Critical issues before delivery. Warnings and Info items are advisory.",
            styles["caption"]
        ))

        # Group by severity
        for sev in ("critical", "warning", "info"):
            sev_issues = [i for i in issues if i.severity == sev]
            if not sev_issues:
                continue

            sev_color = _severity_color(sev)
            sev_bg = _severity_bg(sev)

            story.append(Paragraph(
                f"{sev.upper()}  ({len(sev_issues)} issue{'s' if len(sev_issues) != 1 else ''})",
                ParagraphStyle(f"sev_hdr_{sev}",
                    fontName="Helvetica-Bold", fontSize=11,
                    textColor=sev_color, spaceBefore=5*mm, spaceAfter=2*mm,
                    backColor=sev_bg, borderPadding=(3, 6, 3, 6))
            ))

            # Column widths: rule_id | layer | DSPs | message+fix
            col_w = [46*mm, 22*mm, 30*mm, CONTENT_W - 46*mm - 22*mm - 30*mm]
            headers = ["Rule ID", "Layer", "DSP Targets", "Message / Fix Hint"]
            rows = [[_th(h, styles) for h in headers]]

            for issue in sev_issues:
                # Message cell: message on top, fix hint in italic below
                msg_cell = [Paragraph(_safe(issue.message), styles["table_cell"])]
                if issue.fix_hint:
                    msg_cell.append(Spacer(1, 1.5*mm))
                    msg_cell.append(Paragraph(
                        f"→ {_safe(issue.fix_hint)}", styles["fix_hint"]
                    ))

                dsp_str = ", ".join(issue.dsp_targets) if issue.dsp_targets else "Universal"
                rows.append([
                    _tm(issue.rule_id.replace(".", ".\u200b"), styles),   # zero-width break after dots
                    _tc(LAYER_LABELS.get(issue.layer, issue.layer.title()), styles),
                    _tc(dsp_str, styles),
                    msg_cell,
                ])

            t = Table(rows, colWidths=col_w, repeatRows=1)
            cmd = [
                ("BACKGROUND", (0, 0), (-1, 0), C_ACCENT),
                ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
                ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE",   (0, 0), (-1, 0), 8),
                ("GRID", (0, 0), (-1, -1), 0.25, C_BORDER),
                ("LEFTPADDING",  (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING",   (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ] + _alt_rows(len(rows), len(col_w))
            t.setStyle(TableStyle(cmd))
            story.append(t)
            story.append(Spacer(1, 4*mm))

        return story

    # ── Enrichment page ───────────────────────────────────────────────────────

    def _enrichment_page(self, suggestions: list[ReportSuggestion], styles: dict) -> list:
        story = []
        story.append(Paragraph("Enrichment Suggestions", styles["section_header"]))
        story.append(Paragraph(
            "The following metadata fields were found in MusicBrainz but are missing or "
            "differ from the submitted release. Adding them can improve royalty collection "
            "accuracy, playlist eligibility, and publishing administration.",
            styles["caption"]
        ))

        col_w = [32*mm, 24*mm, CONTENT_W - 32*mm - 24*mm]
        headers = ["Field", "Confidence", "Suggestion / Source"]
        rows = [[_th(h, styles) for h in headers]]

        for sug in suggestions:
            conf_color = C_PASS if sug.confidence == "high" else (
                C_WARNING if sug.confidence == "medium" else C_MUTED)

            detail_cell = [Paragraph(_safe(sug.message), styles["table_cell"])]
            if sug.fix_hint:
                detail_cell.append(Spacer(1, 1.5*mm))
                detail_cell.append(Paragraph(f"→ {_safe(sug.fix_hint)}", styles["fix_hint"]))
            if sug.source_url:
                detail_cell.append(Spacer(1, 1.5*mm))
                detail_cell.append(Paragraph(
                    f"<font color='#4F46E5'>{_safe(sug.source_url)}</font>",
                    styles["table_cell_mono"]
                ))

            rows.append([
                _tc(sug.field.replace("_", " ").title(), styles),
                Paragraph(sug.confidence.upper(), ParagraphStyle(
                    "conf", fontName="Helvetica-Bold", fontSize=8,
                    textColor=conf_color, alignment=TA_LEFT)),
                detail_cell,
            ])

        t = Table(rows, colWidths=col_w, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), C_PASS),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE",   (0, 0), (-1, 0), 8),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, C_PASS_BG]),
            ("GRID", (0, 0), (-1, -1), 0.25, C_BORDER),
            ("LEFTPADDING",  (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(t)

        story.append(Spacer(1, 8*mm))
        story.append(HRFlowable(width=CONTENT_W, thickness=0.5, color=C_BORDER,
                                spaceBefore=0, spaceAfter=4*mm))
        story.append(Paragraph(
            "End of Report  ·  ROPQA Release QA Autopilot",
            ParagraphStyle("eor", fontName="Helvetica", fontSize=8,
                           textColor=C_MUTED, alignment=TA_CENTER)
        ))
        return story
