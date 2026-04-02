# services/time_filter.py — Granular time-based filter logic
#
# Single source of truth for all week/month/year filter calculations.
# No UI imports. Pure data logic — fully testable in isolation.
#
# Week definition: ISO Mon–Sun spans within a calendar month.
#   Week 1 = the span containing the 1st of the month, starting on Monday.
#   e.g. if March 1 2026 is a Sunday, Week 1 = just Mar 1 (Sun),
#        Week 2 = Mar 2 (Mon) – Mar 8 (Sun), etc.
#   SQL equivalent: CEIL((DAY(date) + WEEKDAY(DATE_FORMAT(date,'%Y-%m-01'))) / 7.0)

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

MONTH_NAMES = [
    "", "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Valid modes
MODE_ALL        = "all"
MODE_THIS_WEEK  = "this_week"
MODE_THIS_MONTH = "this_month"
MODE_THIS_YEAR  = "this_year"
MODE_CUSTOM     = "custom"   # uses year / month / week fields


@dataclass
class TimeFilter:
    mode:  str           = MODE_ALL
    year:  Optional[int] = None
    month: Optional[int] = None
    week:  Optional[int] = None   # 1-based week number within the month

    def is_active(self) -> bool:
        """True when any filter other than 'all' is applied."""
        return self.mode != MODE_ALL

    def copy(self) -> "TimeFilter":
        return TimeFilter(mode=self.mode, year=self.year,
                          month=self.month, week=self.week)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_period_label(tf: TimeFilter) -> str:
    """Human-readable period string, e.g. 'March 2026 · Week 1'."""
    today = date.today()

    if tf.mode == MODE_ALL:
        return "All Time"
    if tf.mode == MODE_THIS_WEEK:
        start, end = get_date_range(tf)
        return f"Week of {start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"
    if tf.mode == MODE_THIS_MONTH:
        return today.strftime("%B %Y")
    if tf.mode == MODE_THIS_YEAR:
        return str(today.year)

    # Custom mode
    parts = []
    if tf.year:
        parts.append(str(tf.year))
    if tf.month:
        parts.insert(0, MONTH_NAMES[tf.month])
    if tf.week:
        parts.append(f"· Week {tf.week}")
    return " ".join(parts) if parts else "Custom"


def get_date_range(tf: TimeFilter) -> tuple[date, date]:
    """
    Returns (start_date, end_date) inclusive for the given filter.
    Used for DataFrame slicing.
    """
    today = date.today()

    if tf.mode == MODE_ALL:
        return date(2000, 1, 1), date(2099, 12, 31)

    if tf.mode == MODE_THIS_WEEK:
        # ISO week: Monday = start
        start = today - timedelta(days=today.weekday())
        end   = start + timedelta(days=6)
        return start, end

    if tf.mode == MODE_THIS_MONTH:
        start = today.replace(day=1)
        # last day of month
        if today.month == 12:
            end = date(today.year, 12, 31)
        else:
            end = date(today.year, today.month + 1, 1) - timedelta(days=1)
        return start, end

    if tf.mode == MODE_THIS_YEAR:
        return date(today.year, 1, 1), date(today.year, 12, 31)

    # Custom
    if tf.mode == MODE_CUSTOM:
        y = tf.year or today.year
        if tf.month:
            if tf.week:
                return _week_range_in_month(y, tf.month, tf.week)
            # whole month
            start = date(y, tf.month, 1)
            if tf.month == 12:
                end = date(y, 12, 31)
            else:
                end = date(y, tf.month + 1, 1) - timedelta(days=1)
            return start, end
        # whole year
        return date(y, 1, 1), date(y, 12, 31)

    return date(2000, 1, 1), date(2099, 12, 31)


def get_week_number_for_date(d: date) -> int:
    """
    Returns the ISO Mon–Sun week number (1-based) of date d within its month.
    Week 1 starts on the Monday on or before the 1st of the month.
    """
    first_of_month = d.replace(day=1)
    # weekday(): Monday=0 … Sunday=6
    offset = first_of_month.weekday()   # days before Monday at start of month
    return ((d.day + offset - 1) // 7) + 1


def get_weeks_in_month(year: int, month: int) -> list[int]:
    """Returns list of week numbers that exist in the given month."""
    if month == 12:
        last_day = date(year, 12, 31)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)
    max_week = get_week_number_for_date(last_day)
    return list(range(1, max_week + 1))


def get_week_label(week_num: int) -> str:
    return f"Week {week_num}"


def get_available_years(user_id: int) -> list[int]:
    """Distinct years that have expense data for this user."""
    try:
        from db import get_connection
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT YEAR(date) FROM expenses "
                "WHERE user_id = %s ORDER BY 1 DESC",
                (user_id,),
            )
            rows = cursor.fetchall()
            cursor.close()
        return [r[0] for r in rows if r[0]]
    except Exception as e:
        logger.error("get_available_years failed: %s", e)
        return []


def get_available_months(user_id: int, year: int) -> list[int]:
    """Distinct months that have expense data for user in given year."""
    try:
        from db import get_connection
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT MONTH(date) FROM expenses "
                "WHERE user_id = %s AND YEAR(date) = %s ORDER BY 1",
                (user_id, year),
            )
            rows = cursor.fetchall()
            cursor.close()
        return [r[0] for r in rows if r[0]]
    except Exception as e:
        logger.error("get_available_months failed: %s", e)
        return []


def apply_time_filter_to_df(df, tf: TimeFilter):
    """
    Filter a DataFrame that has a 'Date' column (datetime) by the given TimeFilter.
    Returns filtered DataFrame. Does not mutate the original.
    """
    if df.empty or not tf.is_active():
        return df

    import pandas as pd

    start, end = get_date_range(tf)
    start_ts = pd.Timestamp(start)
    end_ts   = pd.Timestamp(end) + pd.Timedelta(hours=23, minutes=59, seconds=59)
    return df[(df["Date"] >= start_ts) & (df["Date"] <= end_ts)]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _week_range_in_month(year: int, month: int, week_num: int) -> tuple[date, date]:
    """
    Returns the start (Monday) and end (Sunday) of the given week
    within the month, clamped to the month boundaries.
    """
    first = date(year, month, 1)
    # Monday on or before the 1st
    week_start_offset = first.weekday()   # 0=Mon
    # Day-of-month of the Monday that opens week_num
    monday_day = 1 - week_start_offset + (week_num - 1) * 7
    sunday_day = monday_day + 6

    # Clamp to month
    if month == 12:
        last_day_of_month = 31
    else:
        last_day_of_month = (date(year, month + 1, 1) - timedelta(days=1)).day

    monday_day = max(1, monday_day)
    sunday_day = min(last_day_of_month, sunday_day)

    return date(year, month, monday_day), date(year, month, sunday_day)
