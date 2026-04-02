# models/expense.py — Expense CRUD operations
#
# 🏛️ Architect: All expense DB logic lives here.
#   UI tabs call these functions — they never write SQL themselves.
#
# 💎 Dev: Parameterized queries throughout. No f-string SQL.

import logging
from datetime import datetime

import pandas as pd

from config import ALLOWED_TABLES, DATE_FORMAT
from db import get_connection
from db.connection import get_engine

logger = logging.getLogger(__name__)


def get_expenses_df(user_id: int, filter_mode: str = "This Month", search: str = "") -> pd.DataFrame:
    """
    Return a filtered DataFrame of expenses for the given user.

    filter_mode: "This Month" | "This Year" | "All Time"
    search: optional description substring filter
    """
    try:
        sql = ("SELECT id, date, source, category, description, amount "
               "FROM expenses WHERE user_id = %(user_id)s ORDER BY date DESC")
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
            return df

        df.rename(columns={
            "id": "ID", "date": "Date", "source": "Source",
            "category": "Category", "description": "Description", "amount": "Amount",
        }, inplace=True)

        df["Date"] = pd.to_datetime(df["Date"])
        df = _apply_date_filter(df, filter_mode)

        if search:
            df = df[df["Description"].str.lower().str.contains(search.lower(), na=False)]

        return df

    except Exception as e:
        logger.error("get_expenses_df failed: %s", e)
        return pd.DataFrame()


def add_expense(user_id: int, date: str, source: str, category: str,
                description: str, amount: float) -> bool:
    """Insert a new expense row. Returns True on success."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO expenses (user_id, date, source, category, description, amount) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, date, source, category, description, amount),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("add_expense failed: %s", e)
        return False


def update_expense(expense_id: int, user_id: int, date: str, source: str,
                   description: str, amount: float) -> bool:
    """Update an existing expense. Scoped to user_id for safety."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE expenses SET date=%s, source=%s, description=%s, amount=%s "
                "WHERE id=%s AND user_id=%s",
                (date, source, description, amount, expense_id, user_id),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("update_expense failed: %s", e)
        return False


def delete_expenses(expense_ids: list[int], user_id: int) -> bool:
    """Delete one or more expenses. Always scoped to user_id."""
    if not expense_ids:
        return False
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            for eid in expense_ids:
                cursor.execute(
                    "DELETE FROM expenses WHERE id=%s AND user_id=%s",
                    (eid, user_id),
                )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("delete_expenses failed: %s", e)
        return False


def get_category_totals(user_id: int, filter_mode: str = "This Month") -> pd.Series:
    """Return a Series of {category: total_amount} for pie chart use."""
    df = get_expenses_df(user_id, filter_mode)
    if df.empty:
        return pd.Series(dtype=float)
    return df.groupby("Category")["Amount"].sum()


# ---------------------------------------------------------------------------
# Time-filter aware query (additive — existing functions untouched)
# ---------------------------------------------------------------------------

def get_expenses_df_filtered(user_id: int, time_filter=None, search: str = "") -> pd.DataFrame:
    """
    Return expenses for user filtered by a TimeFilter object.
    Falls back to all expenses if time_filter is None or mode='all'.

    time_filter: services.time_filter.TimeFilter instance (optional)
    search:      optional description substring filter
    """
    try:
        sql = ("SELECT id, date, source, category, description, amount "
               "FROM expenses WHERE user_id = %(user_id)s ORDER BY date DESC")
        engine = get_engine()
        if engine:
            df = pd.read_sql(sql, engine, params={"user_id": user_id})
        else:
            with get_connection() as conn:
                df = pd.read_sql(sql.replace("%(user_id)s", "%s"), conn, params=(user_id,))

        if df.empty:
            return df

        df.rename(columns={
            "id": "ID", "date": "Date", "source": "Source",
            "category": "Category", "description": "Description", "amount": "Amount",
        }, inplace=True)

        df["Date"] = pd.to_datetime(df["Date"])

        # Apply TimeFilter if provided and active
        if time_filter is not None and time_filter.is_active():
            from services.time_filter import apply_time_filter_to_df
            df = apply_time_filter_to_df(df, time_filter)

        if search:
            df = df[df["Description"].str.lower().str.contains(search.lower(), na=False)]

        return df

    except Exception as e:
        logger.error("get_expenses_df_filtered failed: %s", e)
        return pd.DataFrame()


def get_summary_stats(user_id: int, time_filter=None) -> dict:
    """
    Returns summary statistics for the Summary Card:
      total       — sum of all amounts
      count       — number of transactions
      highest     — single largest expense amount
      top_category — category with the highest total spend
    Returns zeros/empty strings if no data.
    """
    df = get_expenses_df_filtered(user_id, time_filter)
    if df.empty:
        return {"total": 0.0, "count": 0, "highest": 0.0, "top_category": "—"}

    top_cat = df.groupby("Category")["Amount"].sum().idxmax() if not df.empty else "—"
    return {
        "total":        float(df["Amount"].sum()),
        "count":        len(df),
        "highest":      float(df["Amount"].max()),
        "top_category": top_cat,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _apply_date_filter(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    now = datetime.now()
    if mode == "This Month":
        return df[(df["Date"].dt.year == now.year) & (df["Date"].dt.month == now.month)]
    elif mode == "This Year":
        return df[df["Date"].dt.year == now.year]
    return df  # "All Time"
