# models/fixed_bills.py — Fixed monthly bills CRUD
#
# Fixed bills are recurring monthly obligations (Rent, Electricity, Water, Internet, etc.)
# They are stored in the DB and factored into:
#   - My Wallet  → True Disposable display
#   - Buy Advisor → Financial Snapshot & verdict
#   - Analytics  → Spending breakdown (counted as guaranteed monthly expense)

import logging
import pandas as pd
from db import get_connection
from db.connection import get_engine

logger = logging.getLogger(__name__)


def get_fixed_bills(user_id: int) -> list[dict]:
    """Return all fixed bills for a user as list of dicts."""
    try:
        sql = "SELECT id, name, amount, wallet FROM fixed_bills WHERE user_id = %(user_id)s ORDER BY name"
        engine = get_engine()
        if engine:
            df = pd.read_sql(sql, engine, params={"user_id": user_id})
        else:
            # Fallback: create a temporary SQLAlchemy engine
            from sqlalchemy import create_engine
            from db.connection import load_db_config
            cfg = load_db_config()
            try:
                engine = create_engine(
                    f"mysql+pymysql://{cfg['user']}:{cfg['password']}"
                    f"@{cfg['host']}:{int(cfg.get('port', 3306))}/{cfg['database']}",
                    pool_pre_ping=True
                )
                df = pd.read_sql(sql, engine, params={"user_id": user_id})
            except Exception:
                # Last resort: use raw connection
                with get_connection() as conn:
                    df = pd.read_sql(sql.replace("%(user_id)s", "%s"), conn, params=(user_id,))
        if df.empty:
            return []
        return df.to_dict("records")
    except Exception as e:
        logger.error("get_fixed_bills failed: %s", e)
        return []


def get_total_fixed_bills(user_id: int) -> float:
    """Sum of all fixed monthly bills for a user."""
    bills = get_fixed_bills(user_id)
    return sum(b["amount"] for b in bills)


def add_fixed_bill(user_id: int, name: str, amount: float, wallet: str = "") -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO fixed_bills (user_id, name, amount, wallet) VALUES (%s, %s, %s, %s)",
                (user_id, name, amount, wallet),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("add_fixed_bill failed: %s", e)
        return False


def update_fixed_bill(bill_id: int, name: str, amount: float, wallet: str = "") -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE fixed_bills SET name=%s, amount=%s, wallet=%s WHERE id=%s",
                (name, amount, wallet, bill_id),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("update_fixed_bill failed: %s", e)
        return False


def delete_fixed_bill(bill_id: int) -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM fixed_bills WHERE id=%s", (bill_id,))
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("delete_fixed_bill failed: %s", e)
        return False
