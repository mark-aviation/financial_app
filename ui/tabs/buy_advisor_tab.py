# ui/tabs/buy_advisor_tab.py — Purchase Advisor + Financial Timeline
#
# Two sections via segmented button:
#   1. Advisor — enter item + price → full verdict + payment options
#   2. Timeline — 12-month financial projection chart

import logging
import threading
import customtkinter as ctk
from tkinter import messagebox

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import numpy as np

from config import COLORS
from models.purchase import (
    get_purchases, add_purchase, update_purchase_status, delete_purchase,
    STATUS_PLANNED, STATUS_BOUGHT, STATUS_CANCELLED,
    METHOD_CASH, METHOD_CREDIT, METHOD_LOAN,
)
from services.purchase_advisor import analyse_purchase
from services.financial_timeline import build_timeline
from services.event_bus import bus
from ui.chart_style import (
    apply_dark_axes, apply_dark_figure,
    BG_FIGURE, TEXT_COLOR, MUTED_COLOR, GRID_COLOR,
    COLOR_INCOME, COLOR_EXPENSE,
)

logger = logging.getLogger(__name__)

TEAL   = "#1abc9c"
PURPLE = "#9b59b6"

VERDICT_COLORS = {
    "yes":     COLORS["success"],
    "caution": COLORS["warning"],
    "no":      COLORS["danger"],
}
VERDICT_ICONS = {"yes": "✅", "caution": "⚠️", "no": "❌"}

STATUS_COLORS = {
    STATUS_PLANNED:   COLORS["primary"],
    STATUS_BOUGHT:    COLORS["success"],
    STATUS_CANCELLED: "#888888",
}
STATUS_LABELS = {
    STATUS_PLANNED:   "🔵 Planned",
    STATUS_BOUGHT:    "✅ Bought",
    STATUS_CANCELLED: "❌ Cancelled",
}


class BuyAdvisorTab:
    def __init__(self, parent, user_id, username, filter_mode, **kwargs):
        self.parent  = parent
        self.user_id = user_id
        self._last_analysis = None
        self._timeline_fig  = None
        self._sim_month     = ctk.IntVar(value=0)

        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.frame.pack(fill="both", expand=True)
        self._build_ui()

        bus.subscribe("expense.saved",  self._on_data_change)
        bus.subscribe("filter.changed", self._on_data_change)

    def pack(self, **kwargs):
        pass

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Section toggle
        self._section = ctk.StringVar(value="Advisor")
        seg = ctk.CTkSegmentedButton(
            self.frame,
            values=["Advisor", "Timeline"],
            variable=self._section,
            command=self._switch_section,
        )
        seg.pack(fill="x", padx=20, pady=(10, 0))

        # Two section frames
        self._adv_frame  = ctk.CTkFrame(self.frame, fg_color="transparent")
        self._time_frame = ctk.CTkFrame(self.frame, fg_color="transparent")

        self._build_advisor_section(self._adv_frame)
        self._build_timeline_section(self._time_frame)

        self._adv_frame.pack(fill="both", expand=True, padx=10, pady=8)

    def _switch_section(self, value):
        if value == "Advisor":
            self._time_frame.pack_forget()
            self._adv_frame.pack(fill="both", expand=True, padx=10, pady=8)
        else:
            self._adv_frame.pack_forget()
            self._time_frame.pack(fill="both", expand=True, padx=10, pady=8)
            self._draw_timeline()

    # ── Advisor Section ───────────────────────────────────────────────────

    def _build_advisor_section(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)

        # ── Left: input + verdict ─────────────────────────────────────
        left = ctk.CTkFrame(parent, fg_color="#1e1e1e", corner_radius=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        ctk.CTkLabel(left, text="Purchase Analysis",
                     font=("Segoe UI", 15, "bold"), text_color="white"
                     ).pack(anchor="w", padx=16, pady=(14, 8))

        # Input form
        form = ctk.CTkFrame(left, fg_color="transparent")
        form.pack(fill="x", padx=16, pady=(0, 10))

        def field(label, placeholder, width=260):
            ctk.CTkLabel(form, text=label, font=("Segoe UI", 11),
                         text_color="silver").pack(anchor="w", pady=(6, 1))
            e = ctk.CTkEntry(form, placeholder_text=placeholder,
                             width=width, height=32)
            e.pack(anchor="w")
            return e

        self.ent_item   = field("Item name", "e.g. New laptop")
        self.ent_price  = field("Price (₱)", "e.g. 45000")

        ctk.CTkLabel(form, text="Loan repayment period (months)",
                     font=("Segoe UI", 11), text_color="silver"
                     ).pack(anchor="w", pady=(6, 1))
        self.ent_months = ctk.CTkEntry(form, placeholder_text="12",
                                       width=100, height=32)
        self.ent_months.insert(0, "12")
        self.ent_months.pack(anchor="w")

        ctk.CTkLabel(form, text="Annual interest rate (% — leave 0 for no interest)",
                     font=("Segoe UI", 11), text_color="silver"
                     ).pack(anchor="w", pady=(6, 1))
        self.ent_interest = ctk.CTkEntry(form, placeholder_text="e.g. 5.5",
                                          width=100, height=32)
        self.ent_interest.insert(0, "0")
        self.ent_interest.pack(anchor="w")

        ctk.CTkLabel(form, text="Monthly amount you can allocate for loan (₱)",
                     font=("Segoe UI", 11), text_color="silver"
                     ).pack(anchor="w", pady=(6, 1))
        self.ent_alloc_amount = ctk.CTkEntry(form, placeholder_text="e.g. 2000",
                                              width=150, height=32)
        self.ent_alloc_amount.pack(anchor="w")

        ctk.CTkButton(
            left, text="🔍  Analyse Purchase",
            height=40, font=("Segoe UI", 13, "bold"),
            fg_color=COLORS["primary"], hover_color="#2a6db5",
            command=self._run_analysis,
        ).pack(fill="x", padx=16, pady=(0, 10))

        # Verdict card
        self.verdict_card = ctk.CTkFrame(left, fg_color="#141414",
                                          corner_radius=10, border_width=2,
                                          border_color="#333")
        self.verdict_card.pack(fill="x", padx=16, pady=(0, 10))

        self.lbl_verdict_icon   = ctk.CTkLabel(self.verdict_card, text="",
                                                font=("Segoe UI", 28))
        self.lbl_verdict_icon.pack(pady=(12, 2))
        self.lbl_verdict_title  = ctk.CTkLabel(self.verdict_card, text="",
                                                font=("Segoe UI", 14, "bold"),
                                                text_color="silver")
        self.lbl_verdict_title.pack()
        self.lbl_verdict_reason = ctk.CTkLabel(self.verdict_card, text="",
                                                font=("Segoe UI", 11),
                                                text_color="silver",
                                                wraplength=320, justify="center")
        self.lbl_verdict_reason.pack(pady=(4, 12))

        # Buying power score
        self.lbl_buying_power = ctk.CTkLabel(self.verdict_card, text="",
                                              font=("Segoe UI", 32, "bold"),
                                              text_color=COLORS["success"])
        self.lbl_buying_power.pack()
        ctk.CTkLabel(self.verdict_card, text="buying power",
                     font=("Segoe UI", 9), text_color="#555"
                     ).pack(pady=(0, 12))

        # Payment options
        self.options_frame = ctk.CTkScrollableFrame(left, fg_color="transparent",
                                                     height=140)
        self.options_frame.pack(fill="x", padx=16, pady=(0, 10))

        # Save button
        self.btn_save = ctk.CTkButton(
            left, text="💾  Save to Planned Purchases",
            height=34, font=("Segoe UI", 11),
            fg_color="#2b2b2b", hover_color="#383838",
            border_width=1, border_color="#3d3d3d",
            state="disabled", command=self._save_purchase,
        )
        self.btn_save.pack(fill="x", padx=16, pady=(0, 14))

        # ── Right: breakdown + saved list ─────────────────────────────
        right = ctk.CTkFrame(parent, fg_color="#1e1e1e", corner_radius=12)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        ctk.CTkLabel(right, text="Financial Snapshot",
                     font=("Segoe UI", 15, "bold"), text_color="white"
                     ).pack(anchor="w", padx=16, pady=(14, 4))

        self.snapshot_frame = ctk.CTkFrame(right, fg_color="transparent")
        self.snapshot_frame.pack(fill="x", padx=16, pady=(0, 8))
        self._show_empty_snapshot()

        ctk.CTkFrame(right, fg_color="#2e2e2e", height=1).pack(fill="x",
                     padx=16, pady=6)

        ctk.CTkLabel(right, text="Planned Purchases",
                     font=("Segoe UI", 13, "bold"), text_color="white"
                     ).pack(anchor="w", padx=16, pady=(0, 4))

        self.purchases_scroll = ctk.CTkScrollableFrame(right,
                                                        fg_color="transparent")
        self.purchases_scroll.pack(fill="both", expand=True, padx=10,
                                   pady=(0, 10))
        self._refresh_purchases()

    def _show_empty_snapshot(self):
        for w in self.snapshot_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.snapshot_frame,
                     text="Run an analysis to see your financial snapshot.",
                     font=("Segoe UI", 11), text_color="silver",
                     wraplength=300).pack(pady=20)

    def _show_snapshot(self, a):
        for w in self.snapshot_frame.winfo_children():
            w.destroy()

        rows = [
            ("Monthly Salary",         f"₱{a.salary:,.2f}",              COLORS["success"]),
            ("Avg Monthly Expenses",   f"₱{a.avg_monthly_expenses:,.2f}", COLORS["danger"]),
            ("Fixed Bills/mo",         f"₱{a.total_fixed_bills:,.2f}",   COLORS["warning"]),
            ("Loan Payments/mo",       f"₱{a.total_loan_payments:,.2f}",  COLORS["warning"]),
            ("Card Min Payments/mo",   f"₱{a.total_min_card_payments:,.2f}", COLORS["warning"]),
            ("True Disposable/mo",     f"₱{a.true_disposable_income:,.2f}",
             COLORS["success"] if a.true_disposable_income >= 0 else COLORS["danger"]),
            ("",                       "",                                 ""),
            ("Monthly Budget",         f"₱{a.monthly_budget:,.2f}",      "silver"),
            ("Budget Used",            f"₱{a.budget_used:,.2f}",         COLORS["warning"]),
            ("Budget Remaining",       f"₱{a.budget_remaining:,.2f}",
             COLORS["success"] if a.budget_remaining >= 0 else COLORS["danger"]),
            ("",                       "",                                 ""),
            ("Loan Interest Rate",     f"{a.interest_rate:.2f}% p.a.",    "silver"),
            ("Total Loan Cost",        f"₱{a.total_loan_cost:,.2f}",
             COLORS["warning"] if a.interest_cost > 0 else "silver"),
            ("Interest Cost",          f"₱{a.interest_cost:,.2f}",
             COLORS["danger"] if a.interest_cost > 0 else "silver"),
            ("Monthly Payment (loan)", f"₱{a.monthly_loan_payment:,.2f}/mo", "silver"),
            ("Your Monthly Allocation",f"₱{a.salary_alloc_amount:,.2f}/mo",
             COLORS["success"] if a.salary_alloc_sufficient else COLORS["danger"]),
            ("Allocation Sufficient?", "✅ Yes" if a.salary_alloc_sufficient else "❌ No",
             COLORS["success"] if a.salary_alloc_sufficient else COLORS["danger"]),
            ("",                       "",                                 ""),
            ("── Wallet Info (Today) ──", "",                             "#555"),
            ("Total Wallet Balance",   f"₱{a.total_wallet_balance:,.2f}", "silver"),
            ("Have Cash Today?",
             "✅ Yes — enough in wallets" if a.has_cash_today else "❌ No — not enough today",
             COLORS["success"] if a.has_cash_today else COLORS["warning"]),
        ]

        for label, value, color in rows:
            if not label:
                ctk.CTkFrame(self.snapshot_frame, fg_color="#2e2e2e",
                             height=1).pack(fill="x", pady=3)
                continue
            r = ctk.CTkFrame(self.snapshot_frame, fg_color="transparent")
            r.pack(fill="x", pady=1)
            ctk.CTkLabel(r, text=label, font=("Segoe UI", 10),
                         text_color="#888", anchor="w", width=180
                         ).pack(side="left")
            ctk.CTkLabel(r, text=value, font=("Segoe UI", 10, "bold"),
                         text_color=color, anchor="e"
                         ).pack(side="right")

        if a.at_risk_projects:
            ctk.CTkFrame(self.snapshot_frame, fg_color="#2e2e2e",
                         height=1).pack(fill="x", pady=4)
            ctk.CTkLabel(self.snapshot_frame,
                         text="⚠️ Projects at risk:",
                         font=("Segoe UI", 10, "bold"),
                         text_color=COLORS["warning"]).pack(anchor="w")
            for p in a.at_risk_projects:
                ctk.CTkLabel(self.snapshot_frame, text=f"  • {p}",
                             font=("Segoe UI", 10),
                             text_color=COLORS["warning"]).pack(anchor="w")

    # ── Analysis ──────────────────────────────────────────────────────────

    def _run_analysis(self):
        item = self.ent_item.get().strip()
        if not item:
            messagebox.showerror("Error", "Enter an item name.", parent=self.frame)
            return
        try:
            price = float(self.ent_price.get())
            if price <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Enter a valid price.", parent=self.frame)
            return
        try:
            months = int(self.ent_months.get() or "12")
        except ValueError:
            months = 12
        try:
            interest_rate = float(self.ent_interest.get() or "0")
            if interest_rate < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Enter a valid interest rate (0 or above).", parent=self.frame)
            return
        try:
            alloc_amount = float(self.ent_alloc_amount.get() or "0")
            if alloc_amount < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Enter a valid allocation amount (₱).", parent=self.frame)
            return

        threading.Thread(
            target=self._fetch_analysis,
            args=(item, price, months, interest_rate, alloc_amount),
            daemon=True,
        ).start()

    def _fetch_analysis(self, item, price, months, interest_rate=0.0, alloc_amount=0.0):
        try:
            analysis = analyse_purchase(self.user_id, item, price, months,
                                        interest_rate=interest_rate,
                                        salary_alloc_amount=alloc_amount)
            self.frame.after(0, lambda: self._display_analysis(analysis))
        except Exception as e:
            logger.error("Analysis failed: %s", e)
            import traceback; traceback.print_exc()

    def _display_analysis(self, a):
        self._last_analysis = a
        color = VERDICT_COLORS[a.verdict]

        self.verdict_card.configure(border_color=color)
        self.lbl_verdict_icon.configure(text=VERDICT_ICONS[a.verdict])
        self.lbl_verdict_title.configure(
            text={"yes": "You can afford this",
                  "caution": "Proceed with caution",
                  "no": "Not affordable right now"}[a.verdict],
            text_color=color,
        )
        self.lbl_verdict_reason.configure(text=a.verdict_reason)
        # Buying power = disposable / monthly payment (capped at 999%)
        bp = (a.true_disposable_income / a.monthly_loan_payment * 100
              if a.monthly_loan_payment > 0 else 0.0)
        self.lbl_buying_power.configure(
            text=f"{min(max(bp, 0), 999):.0f}%",
            text_color=color,
        )

        # Payment options
        for w in self.options_frame.winfo_children():
            w.destroy()
        for opt in a.payment_options:
            card = ctk.CTkFrame(self.options_frame,
                                fg_color="#242424", corner_radius=8)
            card.pack(fill="x", pady=3)
            c = COLORS["success"] if opt.feasible else COLORS["danger"]
            ctk.CTkLabel(card, text=opt.label,
                         font=("Segoe UI", 11, "bold"),
                         text_color=c).pack(anchor="w", padx=10, pady=(6, 2))
            ctk.CTkLabel(card, text=opt.detail,
                         font=("Segoe UI", 10), text_color="silver",
                         wraplength=300, justify="left",
                         anchor="w").pack(anchor="w", padx=10, pady=(0, 6))

        self._show_snapshot(a)
        self.btn_save.configure(state="normal")

    # ── Save purchase ─────────────────────────────────────────────────────

    def _save_purchase(self):
        if not self._last_analysis:
            return
        a = self._last_analysis
        # Determine best feasible payment method
        method = METHOD_CASH
        for opt in a.payment_options:
            if opt.feasible:
                method = opt.method
                break
        if add_purchase(self.user_id, a.item_name, a.price, "", method):
            self._refresh_purchases()
            messagebox.showinfo("Saved",
                                f"'{a.item_name}' added to planned purchases.",
                                parent=self.frame)
        else:
            messagebox.showerror("Error", "Failed to save purchase.",
                                 parent=self.frame)

    # ── Purchases list ────────────────────────────────────────────────────

    def _refresh_purchases(self):
        for w in self.purchases_scroll.winfo_children():
            w.destroy()
        purchases = get_purchases(self.user_id)
        if not purchases:
            ctk.CTkLabel(self.purchases_scroll,
                         text="No planned purchases yet.",
                         font=("Segoe UI", 11), text_color="silver"
                         ).pack(pady=12)
            return
        for p in purchases:
            card = ctk.CTkFrame(self.purchases_scroll,
                                fg_color="#242424", corner_radius=8)
            card.pack(fill="x", pady=3)
            top = ctk.CTkFrame(card, fg_color="transparent")
            top.pack(fill="x", padx=10, pady=(6, 2))

            ctk.CTkLabel(top, text=p.item_name,
                         font=("Segoe UI", 12, "bold"),
                         text_color="white").pack(side="left")
            ctk.CTkLabel(top, text=f"₱{p.price:,.2f}",
                         font=("Segoe UI", 12, "bold"),
                         text_color=COLORS["primary"]).pack(side="left",
                                                            padx=(10, 0))

            status_color = STATUS_COLORS.get(p.status, "silver")
            ctk.CTkLabel(top,
                         text=STATUS_LABELS.get(p.status, p.status),
                         font=("Segoe UI", 10),
                         text_color=status_color).pack(side="left", padx=(10, 0))

            btns = ctk.CTkFrame(card, fg_color="transparent")
            btns.pack(anchor="e", padx=10, pady=(0, 6))

            if p.status == STATUS_PLANNED:
                ctk.CTkButton(
                    btns, text="Mark Bought", width=100, height=24,
                    fg_color=COLORS["success"], hover_color="#27ae60",
                    font=("Segoe UI", 10),
                    command=lambda pid=p.id: self._set_status(
                        pid, STATUS_BOUGHT),
                ).pack(side="left", padx=(0, 4))
                ctk.CTkButton(
                    btns, text="Cancel", width=70, height=24,
                    fg_color="#555", hover_color="#666",
                    font=("Segoe UI", 10),
                    command=lambda pid=p.id: self._set_status(
                        pid, STATUS_CANCELLED),
                ).pack(side="left", padx=(0, 4))

            ctk.CTkButton(
                btns, text="🗑", width=30, height=24,
                fg_color=COLORS["danger"], hover_color="#c0392b",
                font=("Segoe UI", 10),
                command=lambda pid=p.id: self._delete(pid),
            ).pack(side="left")

    def _set_status(self, purchase_id, status):
        update_purchase_status(purchase_id, self.user_id, status)
        self._refresh_purchases()

    def _delete(self, purchase_id):
        if messagebox.askyesno("Confirm", "Delete this planned purchase?",
                               parent=self.frame):
            delete_purchase(purchase_id, self.user_id)
            self._refresh_purchases()

    # ── Timeline Section ──────────────────────────────────────────────────

    def _build_timeline_section(self, parent):
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(1, weight=1)

        # Controls
        ctrl = ctk.CTkFrame(parent, fg_color="transparent")
        ctrl.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        ctk.CTkLabel(ctrl, text="Simulate purchase in month:",
                     font=("Segoe UI", 11), text_color="silver"
                     ).pack(side="left", padx=(0, 8))

        self.sim_price_entry = ctk.CTkEntry(ctrl, width=110,
                                             placeholder_text="Purchase ₱")
        self.sim_price_entry.pack(side="left", padx=(0, 8))

        ctk.CTkLabel(ctrl, text="Month (0=now, 11=next year):",
                     font=("Segoe UI", 11), text_color="silver"
                     ).pack(side="left", padx=(0, 4))

        self.sim_month_spin = ctk.CTkEntry(ctrl, width=50,
                                            textvariable=self._sim_month)
        self.sim_month_spin.pack(side="left", padx=(0, 8))

        ctk.CTkButton(ctrl, text="Update Timeline", width=130,
                      fg_color=TEAL, hover_color="#16a085",
                      command=self._draw_timeline).pack(side="left")

        ctk.CTkButton(ctrl, text="Clear Simulation", width=130,
                      fg_color="#2b2b2b", hover_color="#383838",
                      border_width=1, border_color="#3d3d3d",
                      command=self._clear_sim).pack(side="left", padx=(6, 0))

        # Chart container
        self.timeline_container = ctk.CTkFrame(parent, fg_color="#1e1e1e",
                                                corner_radius=10)
        self.timeline_container.grid(row=1, column=0, sticky="nsew")

        # Summary strip
        self.timeline_summary = ctk.CTkFrame(parent, fg_color="transparent")
        self.timeline_summary.grid(row=2, column=0, sticky="ew", pady=(6, 0))

    def _clear_sim(self):
        self.sim_price_entry.delete(0, "end")
        self._sim_month.set(0)
        self._draw_timeline()

    def _draw_timeline(self):
        threading.Thread(target=self._fetch_timeline, daemon=True).start()

    def _fetch_timeline(self):
        try:
            sim_price = float(self.sim_price_entry.get() or "0")
        except ValueError:
            sim_price = 0.0
        sim_month = self._sim_month.get()
        if sim_price <= 0:
            sim_month = -1

        try:
            tl = build_timeline(self.user_id, sim_price, sim_month)
            self.frame.after(0, lambda: self._render_timeline(tl, sim_price))
        except Exception as e:
            logger.error("Timeline failed: %s", e)
            import traceback; traceback.print_exc()

    def _render_timeline(self, tl, sim_price):
        for w in self.timeline_container.winfo_children():
            w.destroy()
        if self._timeline_fig:
            plt.close(self._timeline_fig)

        if tl.is_empty:
            ctk.CTkLabel(
                self.timeline_container,
                text="Set your monthly salary in Settings → Financial Profile\nto see the 12-month timeline.",
                font=("Segoe UI", 13), text_color="silver",
                justify="center",
            ).pack(expand=True)
            return

        labels   = [m.month_label for m in tl.months]
        salary   = [m.salary_in   for m in tl.months]
        expenses = [m.expenses_out + m.loan_payments + m.card_payments
                    for m in tl.months]
        free     = [m.free_balance for m in tl.months]
        cum      = [m.cumulative   for m in tl.months]

        x = np.arange(len(labels))
        w = 0.35

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 5.5),
                                        facecolor=BG_FIGURE)
        apply_dark_figure(fig)

        # ── Top: salary vs obligations bars ──────────────────────────
        apply_dark_axes(ax1)
        ax1.bar(x - w/2, salary,   w, color=COLOR_INCOME,  label="Salary",     zorder=3)
        ax1.bar(x + w/2, expenses, w, color=COLOR_EXPENSE, label="Obligations", zorder=3)

        # Purchase simulation marker
        for i, m in enumerate(tl.months):
            if m.purchase_hit > 0:
                ax1.axvline(x=i, color=COLORS["warning"], linewidth=1.5,
                            linestyle="--", alpha=0.8)
                ax1.text(i + 0.05, max(salary) * 0.95,
                         f"Purchase\n₱{m.purchase_hit:,.0f}",
                         color=COLORS["warning"], fontsize=7, va="top")

        ax1.set_xticks(x)
        ax1.set_xticklabels(labels, rotation=45, ha="right",
                             color=MUTED_COLOR, fontsize=7.5)
        ax1.tick_params(axis="y", colors=MUTED_COLOR, labelsize=8)
        ax1.yaxis.grid(True, color=GRID_COLOR, linewidth=0.5, linestyle="--")
        ax1.set_axisbelow(True)
        ax1.set_ylabel("Amount (₱)", color=MUTED_COLOR, fontsize=8)
        ax1.set_title("Monthly Income vs Obligations",
                      color=TEXT_COLOR, fontsize=11, fontweight="bold", pad=8)
        ax1.legend(facecolor="#1e1e1e", edgecolor="#333",
                   labelcolor=TEXT_COLOR, fontsize=8, loc="upper right")

        # ── Bottom: free balance + cumulative line ────────────────────
        apply_dark_axes(ax2)
        bar_colors = [COLOR_INCOME if v >= 0 else COLOR_EXPENSE for v in free]
        ax2.bar(x, free, color=bar_colors, zorder=3, label="Monthly free balance")
        ax2.plot(x, cum, color=COLORS["warning"], linewidth=2,
                 marker="o", markersize=4, zorder=4, label="Cumulative free")
        ax2.axhline(0, color="#444", linewidth=0.8)

        ax2.set_xticks(x)
        ax2.set_xticklabels(labels, rotation=45, ha="right",
                             color=MUTED_COLOR, fontsize=7.5)
        ax2.tick_params(axis="y", colors=MUTED_COLOR, labelsize=8)
        ax2.yaxis.grid(True, color=GRID_COLOR, linewidth=0.5, linestyle="--")
        ax2.set_axisbelow(True)
        ax2.set_ylabel("Amount (₱)", color=MUTED_COLOR, fontsize=8)
        ax2.set_title("Free Balance & Cumulative Savings",
                      color=TEXT_COLOR, fontsize=11, fontweight="bold", pad=8)
        ax2.legend(facecolor="#1e1e1e", edgecolor="#333",
                   labelcolor=TEXT_COLOR, fontsize=8, loc="upper left")

        fig.tight_layout(pad=1.4)

        canvas = FigureCanvasTkAgg(fig, master=self.timeline_container)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._timeline_fig = fig

        # Summary strip
        for w in self.timeline_summary.winfo_children():
            w.destroy()
        for label, value, color in [
            ("Annual Income",    f"₱{tl.total_annual_in:,.2f}",   COLORS["success"]),
            ("Annual Outflows",  f"₱{tl.total_annual_out:,.2f}",  COLORS["danger"]),
            ("Avg Free/Month",   f"₱{tl.avg_monthly_free:,.2f}",
             COLORS["success"] if tl.avg_monthly_free >= 0 else COLORS["danger"]),
            ("Months to Save",   f"{tl.months_to_save:.1f} mo" if sim_price > 0 else "—",
             COLORS["warning"]),
        ]:
            col = ctk.CTkFrame(self.timeline_summary, fg_color="#1e1e1e",
                               corner_radius=8)
            col.pack(side="left", padx=6, pady=4, fill="x", expand=True)
            ctk.CTkLabel(col, text=label, font=("Segoe UI", 9),
                         text_color="#666").pack(pady=(6, 0))
            ctk.CTkLabel(col, text=value, font=("Segoe UI", 13, "bold"),
                         text_color=color).pack(pady=(0, 6))

    # ── Helpers ───────────────────────────────────────────────────────────

    def _on_data_change(self, **_):
        pass   # timeline redraws on demand via button
