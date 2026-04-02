# models/budget.py — Budget goal management
#
# 💎 Dev: Simple get/set — budget is per-user, latest record wins.

import logging

from db import get_connection

logger = logging.getLogger(__name__)


def get_latest_budget(user_id: int) -> float | None:
    """Return the user's current monthly budget, or None if not set."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT amount FROM budgets WHERE user_id=%s ORDER BY id DESC LIMIT 1",
                (user_id,),
            )
            result = cursor.fetchone()
            cursor.close()
        return float(result[0]) if result else None
    except Exception as e:
        logger.error("get_latest_budget failed: %s", e)
        return None


def set_budget(user_id: int, amount: float) -> bool:
    """Insert a new budget record (latest always wins via ORDER BY id DESC)."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO budgets (user_id, amount) VALUES (%s, %s)",
                (user_id, amount),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("set_budget failed: %s", e)
        return False
