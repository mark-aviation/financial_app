# models/income.py — Income CRUD operations
#
# 💎 Dev: Mirrors the expense model structure for consistency.

import logging
from datetime import datetime

import pandas as pd

from db import get_connection
from db.connection import get_engine

logger = logging.getLogger(__name__)


def get_income_df(user_id: int, filter_mode: str = "This Month") -> pd.DataFrame:
    try:
        sql = (
            "SELECT id, date, source, amount, "
            "COALESCE(is_transfer, 0) AS is_transfer "
            "FROM income WHERE user_id = %(user_id)s ORDER BY date DESC"
        )
        engine = get_engine()
        if engine:
            df = pd.read_sql(sql, engine, params={"user_id": user_id})
        else:
            # Fallback: use SQLAlchemy-compatible connection format
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
            return df

        df.rename(columns={
            "id": "ID", "date": "Date", "source": "Source",
            "amount": "Amount", "is_transfer": "IsTransfer",
        }, inplace=True)

        df["Date"] = pd.to_datetime(df["Date"])
        return _apply_date_filter(df, filter_mode)

    except Exception as e:
        logger.error("get_income_df failed: %s", e)
        return pd.DataFrame()


def add_income(user_id: int, date: str, source: str, amount: float) -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO income (user_id, date, source, amount) VALUES (%s, %s, %s, %s)",
                (user_id, date, source, amount),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("add_income failed: %s", e)
        return False


def update_income(income_id: int, date: str, source: str, amount: float) -> bool:
    """
    Update an income entry.
    Preserves the is_transfer flag to maintain transfer integrity.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            # Fetch existing is_transfer flag to preserve it
            cursor.execute(
                "SELECT COALESCE(is_transfer, 0) FROM income WHERE id=%s",
                (income_id,)
            )
            result = cursor.fetchone()
            is_transfer = result[0] if result else 0
            
            # Update while preserving is_transfer flag
            cursor.execute(
                "UPDATE income SET date=%s, source=%s, amount=%s, is_transfer=%s WHERE id=%s",
                (date, source, amount, is_transfer, income_id),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("update_income failed: %s", e)
        return False


def delete_income(income_id: int) -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM income WHERE id=%s", (income_id,))
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("delete_income failed: %s", e)
        return False


def get_income_metadata(income_id: int) -> dict | None:
    """
    Get complete metadata for an income entry including transfer status.
    Returns: {"id", "date", "source", "amount", "is_transfer"} or None if not found.
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, date, source, amount, COALESCE(is_transfer, 0) FROM income WHERE id=%s",
                (income_id,)
            )
            result = cursor.fetchone()
            cursor.close()
            if result:
                return {
                    "id": result[0],
                    "date": result[1],
                    "source": result[2],
                    "amount": result[3],
                    "is_transfer": result[4],
                }
        return None
    except Exception as e:
        logger.error("get_income_metadata failed: %s", e)
        return None


def transfer_funds(user_id: int, date: str, from_wallet: str, to_wallet: str, amount: float) -> bool:
    """
    Transfer funds between wallets with better validation.
    Creates two linked income entries: negative for source, positive for destination.
    Both marked with is_transfer=1 to hide from income log but properly update wallet balances.
    """
    # Validate inputs first
    if from_wallet == to_wallet:
        logger.error("transfer_funds: source and destination cannot be the same")
        return False
    
    if amount <= 0:
        logger.error("transfer_funds: amount must be positive")
        return False
    
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            
            # Create outflow entry: deduct from source wallet
            cursor.execute(
                "INSERT INTO income (user_id, date, source, amount, is_transfer) VALUES (%s, %s, %s, %s, 1)",
                (user_id, date, from_wallet, -amount),
            )
            
            # Create inflow entry: add to destination wallet
            cursor.execute(
                "INSERT INTO income (user_id, date, source, amount, is_transfer) VALUES (%s, %s, %s, %s, 1)",
                (user_id, date, to_wallet, amount),
            )
            
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("transfer_funds failed: %s", e)
        return False


def get_wallet_list(user_id: int) -> list[str]:
    """Return distinct income sources (wallets) for this user."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT source FROM income WHERE user_id = %s", (user_id,)
            )
            sources = [r[0] for r in cursor.fetchall()]
            cursor.close()
        return sorted(sources) if sources else ["Cash"]
    except Exception as e:
        logger.error("get_wallet_list failed: %s", e)
        return ["Cash"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply_date_filter(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    now = datetime.now()
    if mode == "This Month":
        return df[(df["Date"].dt.year == now.year) & (df["Date"].dt.month == now.month)]
    elif mode == "This Year":
        return df[df["Date"].dt.year == now.year]
    return df