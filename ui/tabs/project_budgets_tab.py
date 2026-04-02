# ui/tabs/project_budgets_tab.py — Project Budget reservations overview
#
# v4.2: Added "Still Needed" column showing gap between estimated cost and allocations.
#       Fixed remaining bar clipping below axis on single-wallet charts.
#       Chart now shows estimated_cost bar alongside committed/remaining.

import logging
import threading
import customtkinter as ctk
from tkinter import ttk

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.patches import Patch

from config import COLORS
from services.budget_service import get_project_budget_summary, BudgetSummary
from services.event_bus import bus
from ui.chart_style import (
    apply_dark_axes, apply_dark_figure, bar_label,
    BG_FIGURE, COLOR_COMMITTED, COLOR_REMAINING, COLOR_DANGER,
    AT_RISK_THRESHOLD, TEXT_COLOR, MUTED_COLOR, GRID_COLOR,
)

logger = logging.getLogger(__name__)

COLOR_NEEDED  = "#60A5FA"   # soft blue — funds still needed
COLOR_BALANCE = "#3B82F6"   # wallet total balance reference

STATUS_META = {
    "funded":   ("✅ Funded",   COLOR_REMAINING),
    "at_risk":  ("⚠️ At Risk",  COLOR_COMMITTED),
    "unfunded": ("❌ Unfunded", COLOR_DANGER),
}


class ProjectBudgetsTab:
    def __init__(self, parent, user_id, username, filter_mode, time_filter=None, **kwargs):
        self.parent = parent
        self.user_id = user_id
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.frame.pack(fill="both", expand=True)
        self._fig = None
        self._build_ui()
        bus.subscribe("deadline.saved",        self.reload)
        bus.subscribe("deadline.done",         self.reload)
        bus.subscribe("deadline.budget_saved", self.reload)
        bus.subscribe("filter.changed",        self.reload)
        bus.subscribe("time_filter.changed",   self.reload)
        bus.subscribe("income.saved",          self.reload)
        bus.subscribe("income.deleted",        self.reload)

    def pack(self, **kwargs):
        pass

    # ------------------------------------------------------------------
    # UI Build
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.frame.columnconfigure(0, weight=3)
        self.frame.columnconfigure(1, weight=2)
        self.frame.rowconfigure(1, weight=1)

        # Summary banner
        banner = ctk.CTkFrame(self.frame, corner_radius=12, fg_color="#1e1e1e")
        banner.grid(row=0, column=0, columnspan=2, sticky="ew", padx=15, pady=(15, 6))
        banner.columnconfigure((0, 1, 2, 3), weight=1)

        self.lbl_total_bal  = self._banner_card(banner, "Total Wallet Balance", COLORS["primary"],  0)
        self.lbl_committed  = self._banner_card(banner, "Total Committed",      COLOR_COMMITTED,    1)
        self.lbl_available  = self._banner_card(banner, "Available After",      COLOR_REMAINING,    2)
        self.lbl_needed     = self._banner_card(banner, "Total Still Needed",   COLOR_NEEDED,       3)
        self.lbl_warn = ctk.CTkLabel(banner, text="", font=("Roboto", 12, "bold"),
                                     text_color=COLOR_DANGER)
        self.lbl_warn.grid(row=1, column=0, columnspan=4, pady=(0, 10))

        # Project allocation list — now with Still Needed column
        left = ctk.CTkFrame(self.frame, corner_radius=12)
        left.grid(row=1, column=0, sticky="nsew", padx=(15, 6), pady=6)
        ctk.CTkLabel(left, text="Wallet Allocations by Project",
                     font=("Roboto", 15, "bold")).pack(anchor="w", padx=15, pady=(12, 6))

        cols = ("Project", "Priority", "Wallet", "Allocated", "Est. Total", "Still Needed", "Status")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=18)
        widths = {
            "Project": 140, "Priority": 65, "Wallet": 100,
            "Allocated": 95, "Est. Total": 95, "Still Needed": 105, "Status": 90,
        }
        for col in cols:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=widths[col], anchor="w")

        self.tree.tag_configure("funded",   foreground=COLOR_REMAINING)
        self.tree.tag_configure("at_risk",  foreground=COLOR_COMMITTED)
        self.tree.tag_configure("unfunded", foreground=COLOR_DANGER)
        self.tree.tag_configure("needed",   foreground=COLOR_NEEDED)
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 12))

        # Chart panel
        self.chart_frame = ctk.CTkFrame(self.frame, corner_radius=12)
        self.chart_frame.grid(row=1, column=1, sticky="nsew", padx=(6, 15), pady=6)
        ctk.CTkLabel(self.chart_frame, text="Budget Status per Wallet",
                     font=("Roboto", 13, "bold")).pack(pady=(12, 4))
        self.chart_container = ctk.CTkFrame(self.chart_frame, fg_color="transparent")
        self.chart_container.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _banner_card(self, parent, title, color, col):
        card = ctk.CTkFrame(parent, fg_color="transparent")
        card.grid(row=0, column=col, padx=12, pady=12, sticky="ew")
        ctk.CTkLabel(card, text=title, font=("Roboto", 10), text_color=MUTED_COLOR).pack()
        lbl = ctk.CTkLabel(card, text="\u20b10.00", font=("Roboto", 18, "bold"), text_color=color)
        lbl.pack()
        return lbl

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def reload(self, **_):
        threading.Thread(target=self._load_data, daemon=True).start()

    def _load_data(self):
        try:
            summary = get_project_budget_summary(self.user_id)
            self.frame.after(0, lambda: self._render(summary))
        except Exception as e:
            logger.error("ProjectBudgetsTab reload failed: %s", e)
            import traceback; traceback.print_exc()
            self.frame.after(0, lambda: self._show_error(str(e)))

    def _show_error(self, msg: str):
        """Show error visibly instead of blank screen."""
        for w in self.frame.winfo_children():
            if getattr(w, "_is_error_label", False):
                w.destroy()
        lbl = ctk.CTkLabel(
            self.frame,
            text=f"Failed to load Project Budgets:\n{msg}",
            font=("Segoe UI", 12), text_color="#e74c3c",
        )
        lbl._is_error_label = True
        lbl.place(relx=0.5, rely=0.5, anchor="center")

    def _render(self, summary: BudgetSummary):
        # Banner
        self.lbl_total_bal.configure(text=f"\u20b1{summary.total_wallet_balance:,.2f}")
        self.lbl_committed.configure(text=f"\u20b1{summary.total_committed:,.2f}")
        avail = summary.available_balance
        self.lbl_available.configure(
            text=f"\u20b1{avail:,.2f}",
            text_color=COLOR_DANGER if avail < 0 else COLOR_REMAINING,
        )

        # Total still needed — one per unique project
        seen_projects = set()
        total_needed = 0.0
        for ar in summary.allocation_rows:
            if ar.project_name not in seen_projects:
                total_needed += ar.funds_needed
                seen_projects.add(ar.project_name)

        self.lbl_needed.configure(
            text=f"\u20b1{total_needed:,.2f}",
            text_color=COLOR_NEEDED if total_needed > 0 else COLOR_REMAINING,
        )

        self.lbl_warn.configure(
            text=(f"🚨  OVER-COMMITTED by \u20b1{abs(avail):,.2f}!"
                  if summary.is_over_committed else "")
        )

        # ── Table — combine all wallets for the same project into ONE row ──
        for row in self.tree.get_children():
            self.tree.delete(row)

        if not summary.allocation_rows:
            self.tree.insert("", "end", values=(
                "No budgeted projects yet.", "", "", "", "", "", ""))
        else:
            # Group rows by project_name (preserve priority sort order)
            from collections import OrderedDict
            grouped: OrderedDict[str, list] = OrderedDict()
            for ar in summary.allocation_rows:
                grouped.setdefault(ar.project_name, []).append(ar)

            for project_name, rows in grouped.items():
                # Combine wallet names and sum allocations
                wallets_combined = ", ".join(r.wallet_name for r in rows)
                total_alloc      = sum(r.allocated_cost for r in rows)
                est_cost         = rows[0].estimated_cost   # same for all rows of a project
                funds_needed     = rows[0].funds_needed      # same for all rows of a project
                priority         = rows[0].priority_level

                # Overall status: worst of all wallets
                # unfunded > at_risk > funded
                status_rank = {"unfunded": 2, "at_risk": 1, "funded": 0}
                worst_status = max(
                    (r.budget_status for r in rows),
                    key=lambda s: status_rank.get(s, 0),
                )
                # If every wallet is funded, show funded; if mix, show partial
                all_funded   = all(r.budget_status == "funded"   for r in rows)
                all_unfunded = all(r.budget_status == "unfunded" for r in rows)
                if len(rows) > 1 and not all_funded and not all_unfunded:
                    status_label = "⚠️ Partial"
                    tag = "at_risk"
                else:
                    status_label, _ = STATUS_META.get(worst_status, ("—", "silver"))
                    tag = "needed" if funds_needed > 0 else worst_status

                needed_str = f"\u20b1{funds_needed:,.2f}" if funds_needed > 0 else "—"

                self.tree.insert("", "end", values=(
                    project_name,
                    priority,
                    wallets_combined,
                    f"\u20b1{total_alloc:,.2f}",
                    f"\u20b1{est_cost:,.2f}" if est_cost else "—",
                    needed_str,
                    status_label,
                ), tags=(tag,))

        self._draw_chart(summary)

    # ------------------------------------------------------------------
    # Chart — 3-bar layout: Committed | Remaining | Still Needed
    # ------------------------------------------------------------------

    def _draw_chart(self, summary: BudgetSummary):
        for w in self.chart_container.winfo_children():
            w.destroy()
        if self._fig:
            plt.close(self._fig)
            self._fig = None

        if not summary.allocation_rows:
            ctk.CTkLabel(self.chart_container, text="No budgeted projects to chart.",
                         text_color=MUTED_COLOR, font=("Roboto", 12)).pack(expand=True)
            return

        # Aggregate per wallet
        wallet_committed: dict[str, float] = {}
        wallet_balance:   dict[str, float] = {}
        wallet_needed:    dict[str, float] = {}
        seen = set()
        for ar in summary.allocation_rows:
            w = ar.wallet_name
            wallet_committed[w] = wallet_committed.get(w, 0.0) + ar.allocated_cost
            wallet_balance[w]   = ar.wallet_balance
            # funds_needed is per-project — accumulate only once per project/wallet pair
            key = (ar.project_name, w)
            if key not in seen:
                wallet_needed[w] = wallet_needed.get(w, 0.0) + ar.funds_needed
                seen.add(key)

        wallets   = list(wallet_committed.keys())
        committed = [wallet_committed[w] for w in wallets]
        balances  = [wallet_balance.get(w, 0) for w in wallets]
        remaining = [max(b - c, 0) for b, c in zip(balances, committed)]
        needed    = [wallet_needed.get(w, 0) for w in wallets]

        remaining_colors = [
            COLOR_DANGER if (b > 0 and (b - c) / b < AT_RISK_THRESHOLD) else COLOR_REMAINING
            for b, c in zip(balances, committed)
        ]

        n = len(wallets)
        bar_h = 0.22          # thinner bars — 3 per wallet now
        gap   = 0.26          # spacing between bar centres
        fig_h = max(2.8, n * 1.4 + 1.0)

        fig, ax = plt.subplots(figsize=(4.6, fig_h))
        apply_dark_figure(fig)
        apply_dark_axes(ax)

        # Add bottom margin so bars don't clip
        ax.set_ylim(-0.6, n - 0.4)

        for i, (w, com, rem, ned, rem_col) in enumerate(
                zip(wallets, committed, remaining, needed, remaining_colors)):
            # 3 bars per wallet: committed (top), remaining (middle), needed (bottom)
            ax.barh(i + gap,  com, bar_h, color=COLOR_COMMITTED, zorder=3)
            ax.barh(i,        rem, bar_h, color=rem_col,          zorder=3)
            ax.barh(i - gap,  ned, bar_h, color=COLOR_NEEDED,     zorder=3)

        # X-axis max = largest balance or largest needed, whichever is bigger
        max_val = max(max(balances, default=1), max(needed, default=1), 1)
        ax.set_xlim(0, max_val * 1.30)

        label_offset = max_val * 0.025
        for i, (com, rem, ned, rem_col) in enumerate(
                zip(committed, remaining, needed, remaining_colors)):
            if com > 0:
                ax.text(com + label_offset, i + gap,
                        f"\u20b1{com:,.0f}", va="center", color=COLOR_COMMITTED,
                        fontsize=7, fontweight="bold")
            if rem > 0:
                ax.text(rem + label_offset, i,
                        f"\u20b1{rem:,.0f}", va="center", color=rem_col,
                        fontsize=7, fontweight="bold")
            if ned > 0:
                ax.text(ned + label_offset, i - gap,
                        f"\u20b1{ned:,.0f}", va="center", color=COLOR_NEEDED,
                        fontsize=7, fontweight="bold")

        ax.set_yticks(list(range(n)))
        ax.set_yticklabels(wallets, color=TEXT_COLOR, fontsize=9, fontweight="bold")
        ax.tick_params(left=False)

        legend_handles = [
            Patch(color=COLOR_COMMITTED, label="Committed"),
            Patch(color=COLOR_REMAINING, label="Remaining"),
            Patch(color=COLOR_DANGER,    label="At Risk (<20%)"),
            Patch(color=COLOR_NEEDED,    label="Still Needed"),
        ]
        ax.legend(
            handles=legend_handles,
            loc="lower right",
            facecolor="#1e1e1e",
            edgecolor="#333",
            labelcolor=TEXT_COLOR,
            fontsize=7,
            framealpha=0.9,
        )

        ax.set_xlabel("Amount (\u20b1)", color=MUTED_COLOR, fontsize=8.5)
        ax.xaxis.grid(True, color=GRID_COLOR, linewidth=0.5, linestyle="--")
        fig.tight_layout(pad=1.4)

        canvas = FigureCanvasTkAgg(fig, master=self.chart_container)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._fig = fig
