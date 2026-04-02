# models/goal.py — Goal Tracker CRUD operations
#
# All DB logic for project_goals and goal_completions.
# No UI imports. Fully testable in isolation.

import csv
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Optional

from db import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Goal:
    id: int
    deadline_id: int
    user_id: int
    goal_name: str
    created_at: datetime


@dataclass
class WeekCompletion:
    """Completion state for one goal across a Mon-Sun week."""
    goal_id:  int
    goal_name: str
    # dict keyed by date object → bool
    days: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Week helpers
# ---------------------------------------------------------------------------

def week_start(d: date) -> date:
    """Return the Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def week_days(start: date) -> list[date]:
    """Return [Mon, Tue, Wed, Thu, Fri, Sat, Sun] for the given week start."""
    return [start + timedelta(days=i) for i in range(7)]


# ---------------------------------------------------------------------------
# Goals CRUD
# ---------------------------------------------------------------------------

def get_goals(deadline_id: int, user_id: int) -> list[Goal]:
    """All goals for a project, ordered by creation time."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, deadline_id, user_id, goal_name, created_at "
                "FROM project_goals "
                "WHERE deadline_id=%s AND user_id=%s "
                "ORDER BY created_at ASC",
                (deadline_id, user_id),
            )
            rows = cursor.fetchall()
            cursor.close()
        return [Goal(**r) for r in rows]
    except Exception as e:
        logger.error("get_goals failed: %s", e)
        return []


def add_goal(deadline_id: int, user_id: int, goal_name: str) -> Optional[Goal]:
    """Insert a new goal. Returns the created Goal or None on failure."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO project_goals (deadline_id, user_id, goal_name) "
                "VALUES (%s, %s, %s)",
                (deadline_id, user_id, goal_name.strip()),
            )
            conn.commit()
            new_id = cursor.lastrowid
            cursor.close()
        return Goal(
            id=new_id,
            deadline_id=deadline_id,
            user_id=user_id,
            goal_name=goal_name.strip(),
            created_at=datetime.now(),
        )
    except Exception as e:
        logger.error("add_goal failed: %s", e)
        return None


def delete_goal(goal_id: int, user_id: int) -> bool:
    """Delete a goal and all its completions (CASCADE)."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM project_goals WHERE id=%s AND user_id=%s",
                (goal_id, user_id),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("delete_goal failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Completions
# ---------------------------------------------------------------------------

def get_completions_for_week(
    deadline_id: int,
    user_id: int,
    week_start_date: date,
) -> dict[tuple, bool]:
    """
    Returns dict keyed by (goal_id, date) → is_completed bool.
    Covers Mon–Sun of the given week.
    """
    end = week_start_date + timedelta(days=6)
    try:
        with get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT gc.goal_id, gc.completion_date, gc.is_completed "
                "FROM goal_completions gc "
                "JOIN project_goals pg ON gc.goal_id = pg.id "
                "WHERE pg.deadline_id=%s AND gc.user_id=%s "
                "  AND gc.completion_date BETWEEN %s AND %s",
                (deadline_id, user_id, week_start_date, end),
            )
            rows = cursor.fetchall()
            cursor.close()
        return {
            (r["goal_id"], r["completion_date"]): bool(r["is_completed"])
            for r in rows
        }
    except Exception as e:
        logger.error("get_completions_for_week failed: %s", e)
        return {}


def toggle_completion(
    goal_id: int,
    user_id: int,
    completion_date: date,
    is_completed: bool,
) -> bool:
    """Upsert completion state for a single (goal, date) cell."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO goal_completions "
                "  (goal_id, user_id, completion_date, is_completed) "
                "VALUES (%s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE is_completed=%s",
                (goal_id, user_id, completion_date,
                 int(is_completed), int(is_completed)),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("toggle_completion failed: %s", e)
        return False


def get_weekly_history(
    deadline_id: int,
    user_id: int,
    weeks: int = 8,
) -> list[dict]:
    """
    Returns list of dicts for the past N weeks (oldest first):
      {week_start: date, total: int, completed: int, pct: float}
    Used by the line chart.
    """
    today = date.today()
    current_monday = week_start(today)
    results = []

    for offset in range(weeks - 1, -1, -1):
        ws = current_monday - timedelta(weeks=offset)
        we = ws + timedelta(days=6)
        try:
            with get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                # Count total possible: goals × 7 days
                cursor.execute(
                    "SELECT COUNT(*) AS cnt FROM project_goals "
                    "WHERE deadline_id=%s AND user_id=%s",
                    (deadline_id, user_id),
                )
                total_goals = cursor.fetchone()["cnt"]

                cursor.execute(
                    "SELECT SUM(gc.is_completed) AS done "
                    "FROM goal_completions gc "
                    "JOIN project_goals pg ON gc.goal_id = pg.id "
                    "WHERE pg.deadline_id=%s AND gc.user_id=%s "
                    "  AND gc.completion_date BETWEEN %s AND %s",
                    (deadline_id, user_id, ws, we),
                )
                row = cursor.fetchone()
                cursor.close()

            done = int(row["done"] or 0)
            total = total_goals * 7
            pct = (done / total * 100) if total > 0 else 0.0
            results.append({
                "week_start": ws,
                "total": total,
                "completed": done,
                "pct": pct,
            })
        except Exception as e:
            logger.error("get_weekly_history week offset %d failed: %s", offset, e)

    return results


def get_daily_completions_for_week(
    deadline_id: int,
    user_id: int,
    week_start_date: date,
) -> list[dict]:
    """
    Returns list of 7 dicts (Mon–Sun):
      {date, total_goals, completed, pct}
    Used for the summary row and per-day line chart.
    """
    goals = get_goals(deadline_id, user_id)
    total_goals = len(goals)
    goal_ids = [g.id for g in goals]
    days = week_days(week_start_date)

    if not goal_ids:
        return [{"date": d, "total_goals": 0, "completed": 0, "pct": 0.0}
                for d in days]

    completions = get_completions_for_week(deadline_id, user_id, week_start_date)
    result = []
    for d in days:
        done = sum(
            1 for gid in goal_ids
            if completions.get((gid, d), False)
        )
        pct = (done / total_goals * 100) if total_goals > 0 else 0.0
        result.append({
            "date": d,
            "total_goals": total_goals,
            "completed": done,
            "pct": pct,
        })
    return result


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def export_goals_csv(deadline_id: int, user_id: int, project_name: str) -> str:
    """
    Export full goal completion history to CSV.
    Returns the file path on success.
    """
    import platform
    if platform.system() == "Windows":
        export_dir = os.path.join(os.path.expanduser("~"), "Documents",
                                  "Expensis Exports")
    else:
        export_dir = os.path.join(os.path.expanduser("~"), "Expensis Exports")
    os.makedirs(export_dir, exist_ok=True)

    safe_name = "".join(c for c in project_name if c.isalnum() or c in " _-")
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename   = f"Goals_{safe_name}_{timestamp}.csv"
    filepath   = os.path.join(export_dir, filename)

    goals = get_goals(deadline_id, user_id)
    if not goals:
        raise ValueError("No goals to export.")

    # Fetch all completions for this project
    try:
        with get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT gc.goal_id, gc.completion_date, gc.is_completed "
                "FROM goal_completions gc "
                "JOIN project_goals pg ON gc.goal_id = pg.id "
                "WHERE pg.deadline_id=%s AND gc.user_id=%s "
                "ORDER BY gc.completion_date ASC",
                (deadline_id, user_id),
            )
            rows = cursor.fetchall()
            cursor.close()
    except Exception as e:
        raise RuntimeError(f"DB error during export: {e}")

    # Build lookup
    comp_map: dict[tuple, bool] = {
        (r["goal_id"], r["completion_date"]): bool(r["is_completed"])
        for r in rows
    }

    # Collect all unique dates
    all_dates = sorted({r["completion_date"] for r in rows})

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Project", "Goal"] + [str(d) for d in all_dates])
        for g in goals:
            row = [project_name, g.goal_name]
            for d in all_dates:
                done = comp_map.get((g.id, d), False)
                row.append("✓" if done else "")
            writer.writerow(row)

    return filepath


def export_goals_pdf(deadline_id: int, user_id: int, project_name: str) -> str:
    """
    Export full goal completion history to PDF using reportlab.
    Returns the file path on success.
    """
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
    except ImportError:
        raise ImportError("reportlab is required for PDF export. Run: pip install reportlab")

    import platform
    if platform.system() == "Windows":
        export_dir = os.path.join(os.path.expanduser("~"), "Documents",
                                  "Expensis Exports")
    else:
        export_dir = os.path.join(os.path.expanduser("~"), "Expensis Exports")
    os.makedirs(export_dir, exist_ok=True)

    safe_name = "".join(c for c in project_name if c.isalnum() or c in " _-")
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename   = f"Goals_{safe_name}_{timestamp}.pdf"
    filepath   = os.path.join(export_dir, filename)

    goals = get_goals(deadline_id, user_id)
    if not goals:
        raise ValueError("No goals to export.")

    try:
        with get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT gc.goal_id, gc.completion_date, gc.is_completed "
                "FROM goal_completions gc "
                "JOIN project_goals pg ON gc.goal_id = pg.id "
                "WHERE pg.deadline_id=%s AND gc.user_id=%s "
                "ORDER BY gc.completion_date ASC",
                (deadline_id, user_id),
            )
            rows = cursor.fetchall()
            cursor.close()
    except Exception as e:
        raise RuntimeError(f"DB error during export: {e}")

    comp_map = {
        (r["goal_id"], r["completion_date"]): bool(r["is_completed"])
        for r in rows
    }
    all_dates = sorted({r["completion_date"] for r in rows})

    doc    = SimpleDocTemplate(filepath, pagesize=landscape(A4),
                               leftMargin=15*mm, rightMargin=15*mm,
                               topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    story  = []

    story.append(Paragraph(f"Goal Tracker — {project_name}", styles["Title"]))
    story.append(Paragraph(
        f"Exported: {datetime.now().strftime('%B %d, %Y %H:%M')}",
        styles["Normal"],
    ))
    story.append(Spacer(1, 8*mm))

    # Table
    header = ["Goal"] + [str(d) for d in all_dates]
    data   = [header]
    for g in goals:
        row = [g.goal_name]
        for d in all_dates:
            row.append("✓" if comp_map.get((g.id, d), False) else "")
        data.append(row)

    col_w = [60*mm] + [12*mm] * len(all_dates)
    t = Table(data, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f6aa5")),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 8),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.HexColor("#f9f9f9"), colors.white]),
        ("ALIGN",  (1, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID",   (0, 0), (-1, -1), 0.3, colors.HexColor("#cccccc")),
        ("ROWHEIGHT", (0, 0), (-1, -1), 7*mm),
    ]))
    story.append(t)
    doc.build(story)
    return filepath
