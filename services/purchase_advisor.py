# services/purchase_advisor.py — Purchase decision engine
#
# Verdict is based purely on income vs obligations (salary, expenses, fixed bills,
# loans, credit cards). Wallet balance is fetched as READ-ONLY info only —
# it does NOT influence the verdict. This keeps present money (wallets) and
# future affordability (income analysis) cleanly separated.

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output data structures
# ---------------------------------------------------------------------------

@dataclass
class PaymentOption:
    method: str          # "cash" | "credit" | "loan"
    feasible: bool
    label: str
    detail: str
    monthly_impact: float = 0.0


@dataclass
class PurchaseAnalysis:
    # Inputs
    item_name: str
    price:     float

    # ── Income-based snapshot (drives the verdict) ───────────────────────
    salary:                   float = 0.0
    avg_monthly_expenses:     float = 0.0
    total_fixed_bills:        float = 0.0
    total_loan_payments:      float = 0.0
    total_min_card_payments:  float = 0.0
    true_disposable_income:   float = 0.0

    # Monthly budget
    monthly_budget:    float = 0.0
    budget_used:       float = 0.0
    budget_remaining:  float = 0.0

    # Interest & loan affordability
    interest_rate:           float = 0.0
    total_loan_cost:         float = 0.0
    interest_cost:           float = 0.0
    monthly_loan_payment:    float = 0.0
    salary_alloc_amount:     float = 0.0   # fixed ₱ the user will put toward loan/mo
    salary_alloc_sufficient: bool  = False

    # ── Wallet info (READ-ONLY — does NOT affect verdict) ────────────────
    total_wallet_balance: float = 0.0      # sum of all wallets right now
    has_cash_today:       bool  = False    # wallet_balance >= price

    # Overall verdict
    verdict:        str = "no"
    verdict_reason: str = ""

    # Payment options
    payment_options: list[PaymentOption] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyse_purchase(
    user_id: int,
    item_name: str,
    price: float,
    loan_months: int = 12,
    interest_rate: float = 0.0,
    salary_alloc_amount: float = 0.0,
) -> PurchaseAnalysis:
    from models.financial_profile import get_salary
    from models.loan import get_total_monthly_loan_payments
    from models.credit_card import get_total_minimum_payments
    from models.budget import get_latest_budget
    from models.fixed_bills import get_total_fixed_bills
    from services.analytics_service import get_wallet_balances, get_summary_totals

    result = PurchaseAnalysis(item_name=item_name, price=price)
    result.interest_rate       = interest_rate
    result.salary_alloc_amount = salary_alloc_amount

    # ── 1. Income & obligations (verdict drivers) ────────────────────────
    result.salary                  = get_salary(user_id)
    result.total_loan_payments     = get_total_monthly_loan_payments(user_id)
    result.total_min_card_payments = get_total_minimum_payments(user_id)
    result.total_fixed_bills       = get_total_fixed_bills(user_id)

    try:
        totals = get_summary_totals(user_id, "This Month")
        result.avg_monthly_expenses = totals.get("total_out", 0.0)
    except Exception:
        result.avg_monthly_expenses = 0.0

    result.true_disposable_income = (
        result.salary
        - result.avg_monthly_expenses
        - result.total_fixed_bills
        - result.total_loan_payments
        - result.total_min_card_payments
    )

    # ── 2. Monthly budget ────────────────────────────────────────────────
    try:
        result.monthly_budget   = get_latest_budget(user_id) or 0.0
        result.budget_used      = result.avg_monthly_expenses
        result.budget_remaining = max(0.0, result.monthly_budget - result.budget_used)
    except Exception:
        pass

    # ── 3. Loan cost with interest (amortised) ───────────────────────────
    result.monthly_loan_payment  = _amortised_payment(price, interest_rate, loan_months)
    result.total_loan_cost       = result.monthly_loan_payment * loan_months
    result.interest_cost         = max(0.0, result.total_loan_cost - price)
    result.salary_alloc_sufficient = (
        salary_alloc_amount > 0
        and salary_alloc_amount >= result.monthly_loan_payment
    )

    # ── 4. Wallet balance — READ ONLY, no effect on verdict ─────────────
    try:
        wallet_list = get_wallet_balances(user_id, "All Time")
        result.total_wallet_balance = sum(w["balance"] for w in wallet_list)
        result.has_cash_today       = result.total_wallet_balance >= price
    except Exception:
        result.total_wallet_balance = 0.0
        result.has_cash_today       = False

    # ── 5. Verdict — income only ─────────────────────────────────────────
    disposable = result.true_disposable_income

    if disposable >= result.monthly_loan_payment and result.salary_alloc_sufficient:
        result.verdict = "yes"
        result.verdict_reason = (
            f"Your disposable income (₱{disposable:,.2f}/mo) covers the "
            f"₱{result.monthly_loan_payment:,.2f}/mo payment, and your "
            f"₱{salary_alloc_amount:,.2f}/mo allocation is sufficient."
        )
    elif disposable >= result.monthly_loan_payment and salary_alloc_amount == 0:
        result.verdict = "yes"
        result.verdict_reason = (
            f"Your disposable income (₱{disposable:,.2f}/mo) can cover the "
            f"₱{result.monthly_loan_payment:,.2f}/mo payment."
        )
    elif result.salary_alloc_sufficient and disposable < result.monthly_loan_payment:
        result.verdict = "caution"
        result.verdict_reason = (
            f"Your allocated ₱{salary_alloc_amount:,.2f}/mo covers the payment, "
            f"but your true disposable income is only ₱{disposable:,.2f}/mo. "
            f"This will be tight — review your expenses."
        )
    elif disposable > 0 and not result.salary_alloc_sufficient and salary_alloc_amount > 0:
        result.verdict = "caution"
        result.verdict_reason = (
            f"Your ₱{salary_alloc_amount:,.2f}/mo allocation does not cover the "
            f"₱{result.monthly_loan_payment:,.2f}/mo payment. "
            f"You are ₱{result.monthly_loan_payment - salary_alloc_amount:,.2f}/mo short. "
            f"Consider a longer repayment period or a smaller loan."
        )
    else:
        result.verdict = "no"
        result.verdict_reason = (
            f"Your disposable income (₱{disposable:,.2f}/mo) is not enough "
            f"to cover the ₱{result.monthly_loan_payment:,.2f}/mo payment. "
            + (f"Your ₱{salary_alloc_amount:,.2f}/mo allocation also falls short."
               if salary_alloc_amount > 0 else
               "Consider setting a monthly allocation to evaluate affordability.")
        )

    # ── 6. Payment options ───────────────────────────────────────────────
    result.payment_options = _build_payment_options(
        user_id, price, result, loan_months, interest_rate,
    )

    return result


def _amortised_payment(principal: float, annual_rate_pct: float, months: int) -> float:
    if months <= 0:
        return 0.0
    if annual_rate_pct <= 0:
        return principal / months
    r = (annual_rate_pct / 100) / 12
    return principal * r / (1 - (1 + r) ** -months)


# ---------------------------------------------------------------------------
# Payment option builders
# ---------------------------------------------------------------------------

def _build_payment_options(
    user_id: int,
    price: float,
    snapshot: PurchaseAnalysis,
    loan_months: int,
    interest_rate: float = 0.0,
) -> list[PaymentOption]:
    options = []

    # ── Cash (based on wallet read-only info) ────────────────────────────
    if snapshot.has_cash_today:
        after = snapshot.total_wallet_balance - price
        options.append(PaymentOption(
            method="cash", feasible=True,
            label="✅ Cash — you have the money today",
            detail=(f"Total wallet balance: ₱{snapshot.total_wallet_balance:,.2f}. "
                    f"After purchase: ₱{after:,.2f} remaining."),
            monthly_impact=0.0,
        ))
    else:
        shortfall = price - snapshot.total_wallet_balance
        options.append(PaymentOption(
            method="cash", feasible=False,
            label="❌ Cash — not enough in wallets today",
            detail=(f"Total wallet balance: ₱{snapshot.total_wallet_balance:,.2f}. "
                    f"You need ₱{shortfall:,.2f} more. Wait for payday or use a loan."),
            monthly_impact=0.0,
        ))

    # ── Credit card ──────────────────────────────────────────────────────
    try:
        from models.credit_card import get_credit_cards
        cards = get_credit_cards(user_id)
        if cards:
            best_card = max(cards, key=lambda c: c.available_credit)
            if best_card.available_credit >= price:
                extra_min = price * (best_card.minimum_payment_pct / 100)
                new_disp  = snapshot.true_disposable_income - extra_min
                feasible  = new_disp >= 0
                options.append(PaymentOption(
                    method="credit", feasible=feasible,
                    label=f"{'✅' if feasible else '⚠️'} Credit — {best_card.card_name}",
                    detail=(
                        f"Available credit: ₱{best_card.available_credit:,.2f} "
                        f"on {best_card.card_name} ({best_card.bank}). "
                        f"Min payment adds ₱{extra_min:,.2f}/mo. "
                        f"New disposable: ₱{new_disp:,.2f}/mo."
                    ),
                    monthly_impact=extra_min,
                ))
            else:
                options.append(PaymentOption(
                    method="credit", feasible=False,
                    label="❌ Credit — insufficient limit",
                    detail=(f"Best available: ₱{best_card.available_credit:,.2f} "
                            f"on {best_card.card_name}. Need ₱{price:,.2f}."),
                    monthly_impact=0.0,
                ))
        else:
            options.append(PaymentOption(
                method="credit", feasible=False,
                label="— No credit cards on file",
                detail="Add a credit card in Settings → Financial Profile.",
                monthly_impact=0.0,
            ))
    except Exception as e:
        logger.error("Credit option failed: %s", e)

    # ── Loan (amortised with interest) ───────────────────────────────────
    if loan_months > 0:
        monthly_payment = snapshot.monthly_loan_payment
        new_disp        = snapshot.true_disposable_income - monthly_payment
        alloc_ok        = snapshot.salary_alloc_sufficient
        feasible        = alloc_ok or new_disp >= 0

        rate_str     = f" at {interest_rate:.2f}% p.a." if interest_rate > 0 else " (0% interest)"
        interest_str = (
            f" Total interest: ₱{snapshot.interest_cost:,.2f}. "
            f"Total cost: ₱{snapshot.total_loan_cost:,.2f}."
            if snapshot.interest_cost > 0 else " No interest charged."
        )
        alloc_str = (
            f" Allocation ₱{snapshot.salary_alloc_amount:,.2f}/mo "
            + ("✅ covers" if alloc_ok else "❌ does NOT cover")
            + f" the ₱{monthly_payment:,.2f}/mo payment."
            if snapshot.salary_alloc_amount > 0 else ""
        )

        options.append(PaymentOption(
            method="loan", feasible=feasible,
            label=f"{'✅' if feasible else '⚠️'} Loan — {loan_months} months{rate_str}",
            detail=(
                f"Monthly payment: ₱{monthly_payment:,.2f}/mo for {loan_months} months."
                f"{interest_str} Remaining disposable: ₱{new_disp:,.2f}/mo.{alloc_str}"
                f"{' ⚠️ Exceeds disposable income.' if new_disp < 0 else ''}"
            ),
            monthly_impact=monthly_payment,
        ))

    return options

