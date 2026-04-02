# models/deadline.py — Deadline/Project tracker CRUD
#
# v4 changes:
#   BUG 1 FIX: get_deadlines() now also fetches allocations in one query
#              (the fix itself is in deadlines_tab.py — subscribe to filter.changed)
#   BUG 2 FIX: reactivate_deadline() added — reverses complete_deadline()
#   FEATURE:   Multi-wallet support via project_wallet_allocations join table.
#              add_deadline() / update_deadline() write allocations atomically.
#              DeadlineItem.allocations = list of {wallet, amount} dicts.

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from db import get_connection

logger = logging.getLogger(__name__)


@dataclass
class DeadlineItem:
    id: int
    project_name: str
    start_date: date
    end_date: date
    status: str
    days_left: int
    progress: float
    triage: str
    status_text: str
    bar_color: str
    estimated_cost: Optional[float] = None
    priority_level: Optional[str] = None
    # Multi-wallet allocations: [{"wallet": "GCash", "amount": 3000.0}, ...]
    allocations: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_deadlines(user_id: int) -> list[DeadlineItem]:
    """
    Return all deadlines for user with allocations pre-loaded.
    Uses two queries (deadlines + allocations) to avoid N+1.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM deadlines WHERE user_id=%s ORDER BY end_date ASC",
                (user_id,),
            )
            rows = cursor.fetchall()

            # Fetch all allocations for this user's deadlines in one shot
            if rows:
                ids = tuple(r["id"] for r in rows)
                placeholders = ",".join(["%s"] * len(ids))
                cursor.execute(
                    f"SELECT deadline_id, wallet_name, allocated_cost "
                    f"FROM project_wallet_allocations WHERE deadline_id IN ({placeholders})",
                    ids,
                )
                alloc_rows = cursor.fetchall()
            else:
                alloc_rows = []
            cursor.close()
    except Exception as e:
        logger.error("get_deadlines failed: %s", e)
        import traceback; traceback.print_exc()
        print(f"[DEADLINES ERROR] {e}")
        return []

    # Group allocations by deadline_id
    alloc_map: dict[int, list] = {}
    for a in alloc_rows:
        alloc_map.setdefault(a["deadline_id"], []).append({
            "wallet": a["wallet_name"],
            "amount": float(a["allocated_cost"]),
        })

    today = date.today()
    items = []
    for row in rows:
        end_d   = row["end_date"]
        start_d = row["start_date"]
        days_left  = (end_d - today).days
        total_days = (end_d - start_d).days

        if total_days > 0:
            progress = max(0.0, min(1.0 - (days_left / total_days), 1.0))
        else:
            progress = 1.0

        if row["status"] == "Completed":
            triage = "completed"
            status_text = "Completed"
            bar_color = "#3498db"
        elif days_left < 0:
            triage = "overdue"
            status_text = f"Overdue by {abs(days_left)} day{'s' if abs(days_left) != 1 else ''}"
            bar_color = "#8e44ad"
        elif days_left < 7:
            triage = "high"
            status_text = f"{days_left} Day{'s' if days_left != 1 else ''} Left!"
            bar_color = "#e74c3c"
        elif days_left <= 14:
            triage = "medium"
            status_text = f"{days_left} Days Left"
            bar_color = "#f1c40f"
        else:
            triage = "low"
            status_text = f"{days_left} Days Left"
            bar_color = "#2ecc71"

        items.append(DeadlineItem(
            id=row["id"],
            project_name=row["project_name"],
            start_date=start_d,
            end_date=end_d,
            status=row["status"],
            days_left=days_left,
            progress=progress,
            triage=triage,
            status_text=status_text,
            bar_color=bar_color,
            estimated_cost=float(row["estimated_cost"]) if row.get("estimated_cost") is not None else None,
            priority_level=row.get("priority_level"),
            allocations=alloc_map.get(row["id"], []),
        ))

    return items


def get_budgeted_deadlines(user_id: int) -> list[DeadlineItem]:
    """Active (non-completed) deadlines that have at least one wallet allocation."""
    return [
        item for item in get_deadlines(user_id)
        if item.allocations and item.status != "Completed"
    ]


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------

def _write_allocations(cursor, deadline_id: int, allocations: list[dict]) -> None:
    """
    Replace all allocations for a deadline atomically.
    allocations: [{"wallet": str, "amount": float}, ...]
    """
    cursor.execute(
        "DELETE FROM project_wallet_allocations WHERE deadline_id=%s",
        (deadline_id,),
    )
    for alloc in allocations:
        cursor.execute(
            "INSERT INTO project_wallet_allocations (deadline_id, wallet_name, allocated_cost) "
            "VALUES (%s, %s, %s)",
            (deadline_id, alloc["wallet"], alloc["amount"]),
        )


# ---------------------------------------------------------------------------
# Create / Update / Complete / Reactivate
# ---------------------------------------------------------------------------

def add_deadline(
    user_id: int,
    project_name: str,
    start_date: str,
    end_date: str,
    estimated_cost: Optional[float] = None,
    priority_level: Optional[str] = None,
    allocations: Optional[list[dict]] = None,
) -> tuple:
    """
    Insert a new deadline and its wallet allocations in one transaction.
    Returns (True, "") on success or (False, error_message) on failure.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO deadlines "
                "(user_id, project_name, start_date, end_date, estimated_cost, priority_level) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, project_name, start_date, end_date, estimated_cost, priority_level),
            )
            new_id = cursor.lastrowid
            if allocations:
                _write_allocations(cursor, new_id, allocations)
            conn.commit()
            cursor.close()
        return True, ""
    except Exception as e:
        logger.error("add_deadline failed: %s", e)
        return False, str(e)


def update_deadline(
    task_id: int,
    project_name: str,
    start_date: str,
    end_date: str,
    estimated_cost: Optional[float] = None,
    priority_level: Optional[str] = None,
    allocations: Optional[list[dict]] = None,
) -> bool:
    """Update a deadline and replace its allocations atomically."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE deadlines "
                "SET project_name=%s, start_date=%s, end_date=%s, "
                "    estimated_cost=%s, priority_level=%s "
                "WHERE id=%s",
                (project_name, start_date, end_date, estimated_cost, priority_level, task_id),
            )
            _write_allocations(cursor, task_id, allocations or [])
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("update_deadline failed: %s", e)
        return False


def complete_deadline(task_id: int) -> bool:
    """
    Mark as Completed. Allocations are KEPT in the DB so reactivate
    can restore them — they just stop counting because we filter
    get_budgeted_deadlines() by status != Completed.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE deadlines SET status='Completed' WHERE id=%s",
                (task_id,),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("complete_deadline failed: %s", e)
        return False


def reactivate_deadline(task_id: int) -> bool:
    """
    BUG 2 FIX — Reverse a Completed deadline back to Active.
    Allocations were preserved on complete, so budget is automatically
    re-reserved when the status returns to Active.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE deadlines SET status='Active' WHERE id=%s",
                (task_id,),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("reactivate_deadline failed: %s", e)
        return False


def delete_deadline(task_id: int) -> bool:
    """
    Permanently delete a deadline and all its wallet allocations.
    ON DELETE CASCADE handles the project_wallet_allocations rows automatically.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM deadlines WHERE id=%s", (task_id,))
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("delete_deadline failed: %s", e)
        return False
