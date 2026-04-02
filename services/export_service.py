# services/export_service.py — CSV and PDF export (new feature)
#
# 💎 Dev: Implements Priority 6 — export feature.
#   CSV uses pandas. PDF uses reportlab (pip install reportlab).
#   Both methods return the output filepath on success.

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

from models import get_expenses_df, get_income_df

logger = logging.getLogger(__name__)

EXPORT_DIR = Path.home() / "Documents" / "Expensis Exports"


def _ensure_export_dir() -> Path:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    return EXPORT_DIR


def export_expenses_csv(user_id: int, filter_mode: str = "This Month") -> str:
    """Export expenses to CSV. Returns filepath string."""
    df = get_expenses_df(user_id, filter_mode)
    if df.empty:
        raise ValueError("No expense data to export for the selected period.")

    out_dir = _ensure_export_dir()
    filename = f"expenses_{filter_mode.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    filepath = out_dir / filename

    df.to_csv(filepath, index=False)
    logger.info("Exported expenses CSV to %s", filepath)
    return str(filepath)


def export_income_csv(user_id: int, filter_mode: str = "This Month") -> str:
    """Export income to CSV. Returns filepath string."""
    df = get_income_df(user_id, filter_mode)
    if df.empty:
        raise ValueError("No income data to export for the selected period.")

    out_dir = _ensure_export_dir()
    filename = f"income_{filter_mode.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    filepath = out_dir / filename

    df.to_csv(filepath, index=False)
    logger.info("Exported income CSV to %s", filepath)
    return str(filepath)


def export_summary_pdf(user_id: int, username: str, filter_mode: str = "This Month") -> str:
    """
    Export a summary PDF report.
    Requires: pip install reportlab
    Returns filepath string.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib import colors as rl_colors
    except ImportError:
        raise ImportError(
            "reportlab is required for PDF export. Install it with: pip install reportlab"
        )

    df_exp = get_expenses_df(user_id, filter_mode)
    df_inc = get_income_df(user_id, filter_mode)

    out_dir = _ensure_export_dir()
    filename = f"summary_{filter_mode.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    filepath = out_dir / filename

    doc = SimpleDocTemplate(str(filepath), pagesize=A4)
    styles = getSampleStyleSheet()
    story = []

    # Title
    story.append(Paragraph(f"Expensis Pro — {filter_mode} Summary", styles["Title"]))
    story.append(Paragraph(f"User: {username} | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]))
    story.append(Spacer(1, 0.5 * cm))

    # Totals
    total_in = df_inc["Amount"].sum() if not df_inc.empty else 0
    total_out = df_exp["Amount"].sum() if not df_exp.empty else 0
    story.append(Paragraph(f"Total Income: ₱{total_in:,.2f}", styles["Heading2"]))
    story.append(Paragraph(f"Total Expenses: ₱{total_out:,.2f}", styles["Heading2"]))
    story.append(Paragraph(f"Net Balance: ₱{total_in - total_out:,.2f}", styles["Heading2"]))
    story.append(Spacer(1, 0.5 * cm))

    # Expenses table
    if not df_exp.empty:
        story.append(Paragraph("Expenses", styles["Heading2"]))
        data = [["Date", "Category", "Source", "Description", "Amount"]]
        for _, row in df_exp.iterrows():
            data.append([
                str(row["Date"].strftime("%Y-%m-%d")),
                str(row["Category"]),
                str(row["Source"]),
                str(row["Description"])[:40],
                f"₱{row['Amount']:,.2f}",
            ])
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), rl_colors.HexColor("#3B8ED0")),
            ("TEXTCOLOR", (0, 0), (-1, 0), rl_colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [rl_colors.white, rl_colors.HexColor("#f0f0f0")]),
            ("GRID", (0, 0), (-1, -1), 0.5, rl_colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
        ]))
        story.append(t)

    doc.build(story)
    logger.info("Exported summary PDF to %s", filepath)
    return str(filepath)
