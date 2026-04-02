# models/financial_profile.py — Salary CRUD
import logging
from db import get_connection

logger = logging.getLogger(__name__)


def get_salary(user_id: int) -> float:
    """Return the user's monthly net salary, or 0 if not set."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT monthly_salary FROM financial_profile WHERE user_id=%s",
                (user_id,),
            )
            row = cursor.fetchone()
            cursor.close()
        return float(row[0]) if row else 0.0
    except Exception as e:
        logger.error("get_salary failed: %s", e)
        return 0.0


def set_salary(user_id: int, amount: float) -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO financial_profile (user_id, monthly_salary) VALUES (%s, %s) "
                "ON DUPLICATE KEY UPDATE monthly_salary=%s",
                (user_id, amount, amount),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("set_salary failed: %s", e)
        return False
