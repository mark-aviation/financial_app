# services/financial_timeline.py — 12-month financial projection
#
# Projects month-by-month cash flow for the next 12 months using:
#   salary, avg expenses, loan payments, credit card minimums,
#   and optionally a simulated future purchase.

import logging
from dataclasses import dataclass, field
from datetime import date
from calendar import month_abbr

logger = logging.getLogger(__name__)


@dataclass
class MonthProjection:
    month_label:    str      # e.g. "Apr 2026"
    month_index:    int      # 0 = current month
    salary_in:      float
    expenses_out:   float    # avg monthly expenses
    loan_payments:  float
    card_payments:  float    # minimum payments
    purchase_hit:   float    # one-time purchase cost if simulated this month
    free_balance:   float    # salary_in − all outflows
    cumulative:     float    # running total free balance
    is_current:     bool


@dataclass
class FinancialTimeline:
    months:             list[MonthProjection] = field(default_factory=list)
    total_annual_in:    float = 0.0
    total_annual_out:   float = 0.0
    avg_monthly_free:   float = 0.0
    months_to_save:     float = 0.0   # how many months to save for a purchase
    is_empty:           bool  = True


def build_timeline(
    user_id: int,
    purchase_price: float = 0.0,
    purchase_month_index: int = -1,   # -1 = no simulation
) -> FinancialTimeline:
    """
    Build a 12-month projection.
    If purchase_price > 0 and purchase_month_index >= 0,
    simulate a one-time cash outflow in that month.
    """
    from models.financial_profile import get_salary
    from models.loan import get_loans
    from models.credit_card import get_credit_cards
    from services.analytics_service import get_summary_totals

    salary = get_salary(user_id)
    if salary <= 0:
        return FinancialTimeline(is_empty=True)

    # Average monthly expenses from this month's data
    try:
        totals = get_summary_totals(user_id, "This Month")
        avg_expenses = totals.get("total_out", 0.0)
    except Exception:
        avg_expenses = 0.0

    # Loan payments — reduce as months_remaining decrements
    loans = get_loans(user_id)

    # Credit card minimum payments (static — based on current balance)
    cards   = get_credit_cards(user_id)
    card_min = sum(c.minimum_payment for c in cards)

    today = date.today()
    months = []
    cumulative = 0.0

    for i in range(12):
        # Advance month
        m = (today.month - 1 + i) % 12
        y = today.year + (today.month - 1 + i) // 12
        label = f"{month_abbr[m + 1]} {y}"

        # Loan payments active in this month
        loan_total = sum(
            l.monthly_payment
            for l in loans
            if l.months_remaining > i   # loan still running
        )

        purchase_hit = purchase_price if i == purchase_month_index else 0.0

        free = salary - avg_expenses - loan_total - card_min - purchase_hit
        cumulative += free

        months.append(MonthProjection(
            month_label=label,
            month_index=i,
            salary_in=salary,
            expenses_out=avg_expenses,
            loan_payments=loan_total,
            card_payments=card_min,
            purchase_hit=purchase_hit,
            free_balance=free,
            cumulative=cumulative,
            is_current=(i == 0),
        ))

    total_in  = sum(m.salary_in for m in months)
    total_out = sum(
        m.expenses_out + m.loan_payments + m.card_payments
        for m in months
    )
    avg_free = sum(m.free_balance for m in months) / 12

    # Months needed to save for a purchase (based on avg free balance)
    months_to_save = 0.0
    if purchase_price > 0 and avg_free > 0:
        months_to_save = purchase_price / avg_free

    return FinancialTimeline(
        months=months,
        total_annual_in=total_in,
        total_annual_out=total_out,
        avg_monthly_free=avg_free,
        months_to_save=months_to_save,
        is_empty=False,
    )
