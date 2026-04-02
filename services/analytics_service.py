# services/analytics_service.py — Chart data preparation
#
# 🏛️ Architect: All chart data calculations live here.
#   The analytics tab calls these and only handles rendering.
#   This makes chart logic testable without a GUI.
#
# 💎 Dev: Charts now run in a background thread (see analytics_tab.py).
#   This module is pure data — no Matplotlib imports, no UI references.

import logging
from dataclasses import dataclass

import pandas as pd

from models import get_expenses_df, get_income_df

logger = logging.getLogger(__name__)


@dataclass
class PieChartData:
    labels: list[str]
    values: list[float]
    is_empty: bool


@dataclass
class CashFlowData:
    dates: list[str]
    amounts: list[float]
    colors: list[str]
    is_empty: bool


def get_pie_data(user_id: int, filter_mode: str) -> PieChartData:
    """Spending breakdown by category."""
    df = get_expenses_df(user_id, filter_mode)
    if df.empty:
        return PieChartData([], [], is_empty=True)

    grouped = df.groupby("Category")["Amount"].sum()
    return PieChartData(
        labels=grouped.index.tolist(),
        values=grouped.values.tolist(),
        is_empty=False,
    )


def get_cashflow_data(user_id: int, filter_mode: str, timeframe: str) -> CashFlowData:
    """
    Income vs expense bar chart data.
    timeframe: "Week" | "Month" | "Year"
    """
    df_inc = get_income_df(user_id, filter_mode)
    df_exp = get_expenses_df(user_id, filter_mode)

    frames = []
    if not df_inc.empty:
        frames.append(df_inc[["Date", "Amount"]].copy())
    if not df_exp.empty:
        neg = df_exp[["Date", "Amount"]].copy()
        neg["Amount"] = -neg["Amount"]
        frames.append(neg)

    if not frames:
        return CashFlowData([], [], [], is_empty=True)

    flow_df = pd.concat(frames)
    flow_df["Date"] = pd.to_datetime(flow_df["Date"])

    resample_rule = "D" if timeframe in ("Week", "Month") else "ME"
    resampled = flow_df.set_index("Date").resample(resample_rule).sum()

    date_labels = resampled.index.strftime("%m-%d").tolist()
    amounts = resampled["Amount"].tolist()
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in amounts]

    return CashFlowData(
        dates=date_labels,
        amounts=amounts,
        colors=colors,
        is_empty=False,
    )


def get_pie_data_filtered(user_id: int, time_filter=None) -> "PieChartData":
    """Spending breakdown by category, respecting a TimeFilter."""
    from models.expense import get_expenses_df_filtered
    df = get_expenses_df_filtered(user_id, time_filter)
    if df.empty:
        return PieChartData([], [], is_empty=True)
    grouped = df.groupby("Category")["Amount"].sum()
    return PieChartData(
        labels=grouped.index.tolist(),
        values=grouped.values.tolist(),
        is_empty=False,
    )


def get_cashflow_data_filtered(user_id: int, time_filter=None, timeframe: str = "Month") -> "CashFlowData":
    """
    Income vs expense bar chart data, respecting a TimeFilter.
    timeframe: "Week" | "Month" | "Year"
    """
    from models.expense import get_expenses_df_filtered
    from models.income import get_income_df

    # For income we reuse the existing coarse filter mapped from TimeFilter
    filter_mode = _time_filter_to_mode(time_filter)
    df_inc = get_income_df(user_id, filter_mode)
    df_exp = get_expenses_df_filtered(user_id, time_filter)

    # Further restrict income to the same date range as the TimeFilter
    if time_filter is not None and time_filter.is_active():
        from services.time_filter import apply_time_filter_to_df
        if not df_inc.empty:
            df_inc = apply_time_filter_to_df(df_inc, time_filter)

    frames = []
    if not df_inc.empty:
        frames.append(df_inc[["Date", "Amount"]].copy())
    if not df_exp.empty:
        neg = df_exp[["Date", "Amount"]].copy()
        neg["Amount"] = -neg["Amount"]
        frames.append(neg)

    if not frames:
        return CashFlowData([], [], [], is_empty=True)

    flow_df = pd.concat(frames)
    flow_df["Date"] = pd.to_datetime(flow_df["Date"])

    resample_rule = "D" if timeframe in ("Week", "Month") else "ME"
    resampled = flow_df.set_index("Date").resample(resample_rule).sum()

    date_labels = resampled.index.strftime("%m-%d").tolist()
    amounts = resampled["Amount"].tolist()
    colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in amounts]

    return CashFlowData(
        dates=date_labels,
        amounts=amounts,
        colors=colors,
        is_empty=False,
    )


def _time_filter_to_mode(time_filter) -> str:
    """Map a TimeFilter to the legacy filter_mode string for income queries."""
    if time_filter is None:
        return "This Month"
    from services.time_filter import MODE_ALL, MODE_THIS_YEAR, MODE_THIS_MONTH
    if time_filter.mode == MODE_ALL:
        return "All Time"
    if time_filter.mode == MODE_THIS_YEAR:
        return "This Year"
    return "All Time"   # custom ranges handled by apply_time_filter_to_df


def get_wallet_balances(user_id: int, filter_mode: str) -> list[dict]:
    """
    Per-wallet net balance: income - expenses.
    Transfers are included here (they physically move money between wallets)
    but the Transfer expense category is excluded to avoid double-counting —
    the deduction is already represented by the lower income on the source wallet.
    Returns list of {"wallet": str, "balance": float}
    """
    df_inc = get_income_df(user_id, filter_mode)
    df_exp = get_expenses_df(user_id, filter_mode)

    # NOTE: Transfer expenses are kept here so the source wallet is correctly
    # debited. The destination wallet is credited via its income entry.
    # Excluding Transfer expenses here was a bug — it meant transfers never
    # reduced the source wallet balance.
    from models import get_wallet_list
    wallets = get_wallet_list(user_id)

    results = []
    for w in wallets:
        inc = df_inc[df_inc["Source"] == w]["Amount"].sum() if not df_inc.empty else 0.0
        exp = df_exp[df_exp["Source"] == w]["Amount"].sum() if not df_exp.empty else 0.0
        results.append({"wallet": w, "balance": inc - exp})

    return results


def get_summary_totals(user_id: int, filter_mode: str) -> dict:
    """Total income, total expenses, net balance.
    Transfers between wallets are excluded from both totals so they don't
    inflate income or spending figures."""
    df_inc = get_income_df(user_id, filter_mode)
    df_exp = get_expenses_df(user_id, filter_mode)

    # Exclude transfer-tagged income rows
    if not df_inc.empty and "IsTransfer" in df_inc.columns:
        df_inc = df_inc[df_inc["IsTransfer"] == 0]
    # Exclude transfer-tagged expense rows (category == "Transfer")
    if not df_exp.empty and "Category" in df_exp.columns:
        df_exp = df_exp[df_exp["Category"] != "Transfer"]

    total_in = float(df_inc["Amount"].sum()) if not df_inc.empty else 0.0
    total_out = float(df_exp["Amount"].sum()) if not df_exp.empty else 0.0

    return {
        "total_in": total_in,
        "total_out": total_out,
        "net": total_in - total_out,
    }


# ---------------------------------------------------------------------------
# Clustered bar chart — expenses by category over time
# ---------------------------------------------------------------------------

from dataclasses import dataclass as _dataclass, field as _field


@_dataclass
class CategoryTimeData:
    """Data for clustered bar chart: expenses by category over time."""
    periods:    list          # x-axis labels  e.g. ["03-09", "03-10", ...]
    categories: list          # legend labels  e.g. ["Food", "Transport", ...]
    data:       dict          # {category: [amount_per_period, ...]}
    is_empty:   bool


def get_expense_by_category_over_time(
    user_id: int,
    filter_mode: str,
    timeframe: str,
    time_filter=None,
) -> CategoryTimeData:
    """
    Returns expenses grouped by category AND date period for clustered bar chart.

    timeframe: "Week" | "Month" | "Year"
    Each period is one day (Week/Month view) or one month (Year view).
    """
    from models.expense import get_expenses_df_filtered
    from models.expense import get_expenses_df

    # Fetch with time_filter if active, otherwise use legacy filter_mode
    if time_filter is not None and time_filter.is_active():
        df = get_expenses_df_filtered(user_id, time_filter)
    else:
        df = get_expenses_df(user_id, filter_mode)

    if df.empty:
        return CategoryTimeData([], [], {}, is_empty=True)

    import pandas as pd
    df["Date"] = pd.to_datetime(df["Date"])

    # Choose resample rule
    rule = "D" if timeframe in ("Week", "Month") else "ME"
    fmt  = "%m-%d" if timeframe in ("Week", "Month") else "%b %Y"

    # Pivot: index=Date, columns=Category, values=sum(Amount)
    pivot = (
        df.groupby([pd.Grouper(key="Date", freq=rule), "Category"])["Amount"]
        .sum()
        .unstack(fill_value=0)
    )

    if pivot.empty:
        return CategoryTimeData([], [], {}, is_empty=True)

    periods    = [d.strftime(fmt) for d in pivot.index]
    categories = list(pivot.columns)
    data       = {cat: pivot[cat].tolist() for cat in categories}

    return CategoryTimeData(
        periods=periods,
        categories=categories,
        data=data,
        is_empty=False,
    )