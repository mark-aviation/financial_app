# services/budget_service.py — Project budget reservation logic
#
# v4: Fully rewritten for multi-wallet allocations via project_wallet_allocations.
#     Each project can now split its budget across multiple wallets.
#     All business rules (funded/at_risk/unfunded, warnings) remain the same.

import logging
from dataclasses import dataclass, field
from typing import Optional

from config import PROJECT_AT_RISK_THRESHOLD, PROJECT_DOUBLE_WARN_THRESHOLD
from models.deadline import get_budgeted_deadlines, DeadlineItem
from services.analytics_service import get_wallet_balances

logger = logging.getLogger(__name__)

PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2, None: 3}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class WalletAllocationRow:
    """One wallet slice shown in the Project Budgets list."""
    project_name: str
    priority_level: str
    wallet_name: str
    allocated_cost: float
    wallet_balance: float
    budget_status: str   # "funded" | "at_risk" | "unfunded"
    estimated_cost: float = 0.0    # total project cost target
    total_allocated: float = 0.0   # sum of all wallet allocations for this project
    funds_needed: float = 0.0      # estimated_cost - total_allocated (gap)


@dataclass
class BudgetSummary:
    total_wallet_balance: float
    total_committed: float
    available_balance: float
    is_over_committed: bool
    # One row per (project, wallet) pair — sorted by priority then project name
    allocation_rows: list[WalletAllocationRow] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_project_budget_summary(user_id: int) -> BudgetSummary:
    """
    Build the full summary for the Project Budgets tab.
    Uses All Time wallet balances so reservations reflect total funds.
    """
    budgeted = get_budgeted_deadlines(user_id)
    wallet_map = _build_wallet_map(user_id)

    # Compute committed per wallet across ALL active projects
    committed_per_wallet: dict[str, float] = {}
    for item in budgeted:
        for alloc in item.allocations:
            w = alloc["wallet"]
            committed_per_wallet[w] = committed_per_wallet.get(w, 0.0) + alloc["amount"]

    rows: list[WalletAllocationRow] = []
    for item in sorted(budgeted, key=lambda x: (PRIORITY_ORDER.get(x.priority_level, 3), x.project_name)):
        total_alloc = sum(a["amount"] for a in item.allocations)
        est_cost = item.estimated_cost or 0.0
        gap = max(est_cost - total_alloc, 0.0)
        for alloc in item.allocations:
            w = alloc["wallet"]
            bal = wallet_map.get(w, 0.0)
            committed = committed_per_wallet.get(w, 0.0)
            status = _compute_status(bal, committed)
            rows.append(WalletAllocationRow(
                project_name=item.project_name,
                priority_level=item.priority_level or "—",
                wallet_name=w,
                allocated_cost=alloc["amount"],
                wallet_balance=bal,
                budget_status=status,
                estimated_cost=est_cost,
                total_allocated=total_alloc,
                funds_needed=gap,
            ))

    total_wallet = sum(wallet_map.values())
    total_committed = sum(
        alloc["amount"]
        for item in budgeted
        for alloc in item.allocations
    )
    available = total_wallet - total_committed

    return BudgetSummary(
        total_wallet_balance=total_wallet,
        total_committed=total_committed,
        available_balance=available,
        is_over_committed=available < 0,
        allocation_rows=rows,
    )


def check_warnings(
    user_id: int,
    new_allocations: list[dict],
    exclude_task_id: Optional[int] = None,
) -> list[str]:
    """
    Return warning strings before saving a project.
    new_allocations: [{"wallet": str, "amount": float}, ...]
    Pass exclude_task_id when editing to avoid double-counting old values.
    """
    warnings: list[str] = []

    budgeted = _get_budgeted_excluding(user_id, exclude_task_id)
    wallet_map = _build_wallet_map(user_id)

    # Current committed per wallet (excluding this project)
    committed_per_wallet: dict[str, float] = {}
    for item in budgeted:
        for alloc in item.allocations:
            w = alloc["wallet"]
            committed_per_wallet[w] = committed_per_wallet.get(w, 0.0) + alloc["amount"]

    # Check each new allocation against its wallet
    for alloc in new_allocations:
        w = alloc["wallet"]
        amt = alloc["amount"]
        bal = wallet_map.get(w, 0.0)
        new_total = committed_per_wallet.get(w, 0.0) + amt
        if new_total > bal:
            warnings.append(
                f"⚠️  Over-commitment on '{w}': committing ₱{amt:,.2f} brings "
                f"total to ₱{new_total:,.2f} but balance is only ₱{bal:,.2f}."
            )

    # Check if new project more than doubles total committed budget (all wallets)
    total_existing = sum(
        alloc["amount"] for item in budgeted for alloc in item.allocations
    )
    total_new = sum(a["amount"] for a in new_allocations)
    if total_existing > 0 and (total_existing + total_new) >= total_existing * PROJECT_DOUBLE_WARN_THRESHOLD:
        warnings.append(
            f"⚠️  Budget spike: This project adds ₱{total_new:,.2f}, bringing "
            f"total committed from ₱{total_existing:,.2f} to "
            f"₱{total_existing + total_new:,.2f} — more than double."
        )

    return warnings


def compute_allocation_statuses(
    user_id: int,
    new_allocations: list[dict],
    exclude_task_id: Optional[int] = None,
) -> dict[str, str]:
    """
    Return {wallet_name: status} for each allocation in new_allocations.
    Used to show preview colors in the edit dialog.
    """
    budgeted = _get_budgeted_excluding(user_id, exclude_task_id)
    wallet_map = _build_wallet_map(user_id)

    committed_per_wallet: dict[str, float] = {}
    for item in budgeted:
        for alloc in item.allocations:
            w = alloc["wallet"]
            committed_per_wallet[w] = committed_per_wallet.get(w, 0.0) + alloc["amount"]

    result = {}
    for alloc in new_allocations:
        w = alloc["wallet"]
        bal = wallet_map.get(w, 0.0)
        committed = committed_per_wallet.get(w, 0.0) + alloc["amount"]
        result[w] = _compute_status(bal, committed)

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_budgeted_excluding(user_id: int, exclude_task_id: Optional[int]) -> list[DeadlineItem]:
    items = get_budgeted_deadlines(user_id)
    if exclude_task_id is not None:
        items = [i for i in items if i.id != exclude_task_id]
    return items


def _build_wallet_map(user_id: int) -> dict[str, float]:
    """Wallet name → current balance (All Time)."""
    return {row["wallet"]: row["balance"] for row in get_wallet_balances(user_id, "All Time")}


def _compute_status(wallet_balance: float, total_committed: float) -> str:
    """funded | at_risk | unfunded based on how tight the wallet is."""
    if wallet_balance <= 0 or total_committed > wallet_balance:
        return "unfunded"
    remaining_pct = (wallet_balance - total_committed) / wallet_balance
    return "at_risk" if remaining_pct < PROJECT_AT_RISK_THRESHOLD else "funded"
