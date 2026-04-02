# ui/tabs/settings_tab.py
# v4.1 Visual polish: DB credentials card with amber accent border,
#      consistent field sizing, ghost Test button, fading status banner.
#      All logic identical — only presentation changed.

import logging
import threading
import customtkinter as ctk
from tkinter import messagebox

from config import COLORS
from models.budget import set_budget, get_latest_budget
from services.auth_service import add_custom_category, delete_account
from services.export_service import export_expenses_csv, export_income_csv, export_summary_pdf
from services.event_bus import bus
from ui.chart_style import COLOR_COMMITTED, COLOR_REMAINING, COLOR_DANGER, MUTED_COLOR

logger = logging.getLogger(__name__)

# Banner colour tokens
BANNER_SUCCESS_BG   = "#064E3B"
BANNER_SUCCESS_FG   = "#6EE7B7"
BANNER_ERROR_BG     = "#7F1D1D"
BANNER_ERROR_FG     = "#FCA5A5"
BANNER_NEUTRAL_BG   = "#1C2B3A"
BANNER_NEUTRAL_FG   = "#93C5FD"

FIELD_WIDTH  = 320
FIELD_HEIGHT = 36


class SettingsTab:
    def __init__(self, parent, user_id, username, filter_mode, on_logout, **kwargs):
        self.parent     = parent
        self.user_id    = user_id
        self.username   = username
        self.filter_mode = filter_mode
        self.on_logout  = on_logout
        self._fade_job  = None   # pending after() id for banner fade

        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.frame.pack(fill="both", expand=True)
        self._build_ui()

    def pack(self, **kwargs):
        pass

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build_ui(self):
        scroll = ctk.CTkScrollableFrame(self.frame, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=10)

        # ── 🔌 Database Connection ────────────────────────────────────
        self._section_label(scroll, "🔌  Database Connection")
        ctk.CTkLabel(
            scroll,
            text="Changes take effect immediately — no restart required.",
            font=("Roboto", 11),
            text_color=MUTED_COLOR,
        ).pack(anchor="w", pady=(0, 10))

        # Card with amber left-accent border (simulated with nested frames)
        outer = ctk.CTkFrame(scroll, fg_color=COLOR_COMMITTED, corner_radius=10)
        outer.pack(fill="x", pady=(0, 8))
        inner = ctk.CTkFrame(outer, fg_color="#1a1a1a", corner_radius=9)
        inner.pack(fill="both", expand=True, padx=(3, 0), pady=0)   # 3px left gap = accent

        fields_frame = ctk.CTkFrame(inner, fg_color="transparent")
        fields_frame.pack(fill="x", padx=18, pady=(14, 10))
        fields_frame.columnconfigure(1, weight=1)

        from db.connection import load_db_config
        cfg = load_db_config()

        def db_row(label_text, row, default, show=""):
            ctk.CTkLabel(
                fields_frame, text=label_text, anchor="w",
                font=("Roboto", 12), text_color="#D1D5DB", width=115,
            ).grid(row=row, column=0, sticky="w", pady=5, padx=(0, 12))
            ent = ctk.CTkEntry(
                fields_frame,
                width=FIELD_WIDTH, height=FIELD_HEIGHT,
                show=show,
                fg_color="#111111",
                border_color="#374151",
                text_color="#F9FAFB",
            )
            ent.insert(0, str(default))
            ent.grid(row=row, column=1, sticky="ew", pady=5)
            return ent

        self.db_host     = db_row("Host / IP",       0, cfg.get("host", "localhost"))
        self.db_port     = db_row("Port",            1, cfg.get("port", 3306))
        self.db_name     = db_row("Database",        2, cfg.get("database", "expensis"))
        self.db_user     = db_row("Username",        3, cfg.get("user", ""))
        self.db_password = db_row("🔒  Password",    4, cfg.get("password", ""), show="●")

        # Buttons
        btn_row = ctk.CTkFrame(inner, fg_color="transparent")
        btn_row.pack(anchor="w", padx=18, pady=(4, 16))

        ctk.CTkButton(
            btn_row,
            text="💾  Save & Reconnect",
            command=self._save_db_credentials,
            fg_color=COLOR_COMMITTED,
            hover_color="#D97706",
            text_color="#000000",
            font=("Roboto", 13, "bold"),
            width=175, height=36,
            corner_radius=8,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            btn_row,
            text="🔁  Test Connection",
            command=self._test_connection,
            fg_color="transparent",
            border_width=1,
            border_color="#374151",
            hover_color="#1f2937",
            text_color="#D1D5DB",
            width=150, height=36,
            corner_radius=8,
        ).pack(side="left")

        # Status banner — hidden until needed
        self.banner_frame = ctk.CTkFrame(
            scroll, corner_radius=8, fg_color="transparent", height=0,
        )
        self.banner_frame.pack(fill="x", pady=(0, 6))
        self.lbl_db_status = ctk.CTkLabel(
            self.banner_frame, text="", font=("Roboto", 12, "bold"),
            text_color=BANNER_SUCCESS_FG,
        )
        self.lbl_db_status.pack(padx=14, pady=8)

        # ── Monthly Budget ────────────────────────────────────────────
        self._section_label(scroll, "Monthly Budget Goal")
        bud_row = ctk.CTkFrame(scroll, fg_color="transparent")
        bud_row.pack(anchor="w", pady=(0, 5))
        self.ent_budget = ctk.CTkEntry(bud_row, placeholder_text="Amount (e.g. 15000)", width=200)
        self.ent_budget.pack(side="left", padx=(0, 10))
        current = get_latest_budget(self.user_id)
        if current:
            self.ent_budget.insert(0, str(int(current)))
        ctk.CTkButton(bud_row, text="Set Budget", command=self._set_budget).pack(side="left")

        # ── Custom Categories ─────────────────────────────────────────
        self._section_label(scroll, "Custom Expense Categories")
        cat_row = ctk.CTkFrame(scroll, fg_color="transparent")
        cat_row.pack(anchor="w", pady=(0, 15))
        self.ent_category = ctk.CTkEntry(cat_row, placeholder_text="New category name", width=200)
        self.ent_category.pack(side="left", padx=(0, 10))
        ctk.CTkButton(cat_row, text="Save Category", command=self._add_category).pack(side="left")

        # ── Export ────────────────────────────────────────────────────
        self._section_label(scroll, "Export Data")
        ctk.CTkLabel(scroll, text="Saved to ~/Documents/Expensis Exports/",
                     font=("Roboto", 11), text_color=MUTED_COLOR).pack(anchor="w", pady=(0, 8))
        exp_row = ctk.CTkFrame(scroll, fg_color="transparent")
        exp_row.pack(anchor="w", pady=(0, 5))
        for label, cmd in [
            ("Expenses CSV", self._export_expenses_csv),
            ("Income CSV",   self._export_income_csv),
            ("Summary PDF",  self._export_pdf),
        ]:
            ctk.CTkButton(exp_row, text=label, command=cmd, width=140).pack(side="left", padx=(0, 8))
        self.lbl_export = ctk.CTkLabel(scroll, text="", font=("Roboto", 11),
                                       text_color=COLOR_REMAINING)
        self.lbl_export.pack(anchor="w")

        # ── Financial Profile ──────────────────────────────────────────
        self._section_label(scroll, "💰  Financial Profile")
        self._build_financial_profile(scroll)

        # ── Fixed Monthly Bills ────────────────────────────────────────
        self._section_label(scroll, "🧾  Fixed Monthly Bills")
        ctk.CTkLabel(
            scroll,
            text="Recurring obligations deducted from disposable income (Rent, Electricity, Water, Internet, etc.)",
            font=("Roboto", 11), text_color=MUTED_COLOR,
        ).pack(anchor="w", pady=(0, 8))
        self._build_fixed_bills(scroll)

        # ── Danger Zone ───────────────────────────────────────────────
        ctk.CTkLabel(scroll, text="Danger Zone", font=("Roboto", 18, "bold"),
                     text_color=COLOR_DANGER).pack(anchor="w", pady=(30, 8))
        ctk.CTkButton(
            scroll, text="DELETE MY ACCOUNT",
            fg_color=COLOR_DANGER, hover_color="#991B1B",
            command=self._delete_account,
        ).pack(anchor="w")

    def _build_financial_profile(self, parent):
        """Salary, loans, and credit card management."""
        from models.financial_profile import get_salary, set_salary
        from models.loan import get_loans, add_loan, delete_loan
        from models.credit_card import get_credit_cards, add_credit_card, delete_credit_card

        # ── Salary ────────────────────────────────────────────────────
        ctk.CTkLabel(parent, text="Monthly Net Salary (take-home)",
                     font=("Roboto", 13, "bold")).pack(anchor="w", pady=(0, 4))
        sal_row = ctk.CTkFrame(parent, fg_color="transparent")
        sal_row.pack(anchor="w", pady=(0, 10))
        self.ent_salary = ctk.CTkEntry(sal_row, width=200,
                                       placeholder_text="e.g. 25000")
        current_salary = get_salary(self.user_id)
        if current_salary > 0:
            self.ent_salary.insert(0, str(int(current_salary)))
        self.ent_salary.pack(side="left", padx=(0, 10))
        ctk.CTkButton(sal_row, text="Save Salary", width=110,
                      command=lambda: self._save_salary(get_salary, set_salary)
                      ).pack(side="left")

        # ── Loans ──────────────────────────────────────────────────────
        ctk.CTkLabel(parent, text="Loans / Amortizations",
                     font=("Roboto", 13, "bold")).pack(anchor="w", pady=(10, 4))

        self.loans_frame = ctk.CTkFrame(parent, fg_color="#1a1a1a",
                                         corner_radius=8)
        self.loans_frame.pack(fill="x", pady=(0, 6))
        self._refresh_loans_display(get_loans, delete_loan)

        # Add loan form
        loan_form = ctk.CTkFrame(parent, fg_color="transparent")
        loan_form.pack(fill="x", pady=(0, 10))
        self.ent_loan_name    = ctk.CTkEntry(loan_form, width=130, placeholder_text="Loan name")
        self.ent_loan_bank    = ctk.CTkEntry(loan_form, width=100, placeholder_text="Bank")
        self.ent_loan_total   = ctk.CTkEntry(loan_form, width=90,  placeholder_text="Total ₱")
        self.ent_loan_monthly = ctk.CTkEntry(loan_form, width=90,  placeholder_text="Monthly ₱")
        self.ent_loan_months  = ctk.CTkEntry(loan_form, width=60,  placeholder_text="Months")
        self.ent_loan_rate    = ctk.CTkEntry(loan_form, width=60,  placeholder_text="Rate %")
        for w in [self.ent_loan_name, self.ent_loan_bank, self.ent_loan_total,
                  self.ent_loan_monthly, self.ent_loan_months, self.ent_loan_rate]:
            w.pack(side="left", padx=(0, 4))
        ctk.CTkButton(loan_form, text="+ Add Loan", width=90,
                      fg_color="#1abc9c", hover_color="#16a085",
                      command=lambda: self._add_loan(add_loan, get_loans, delete_loan)
                      ).pack(side="left")

        # ── Credit Cards ───────────────────────────────────────────────
        ctk.CTkLabel(parent, text="Credit Cards",
                     font=("Roboto", 13, "bold")).pack(anchor="w", pady=(10, 4))

        self.cards_frame = ctk.CTkFrame(parent, fg_color="#1a1a1a",
                                         corner_radius=8)
        self.cards_frame.pack(fill="x", pady=(0, 6))
        self._refresh_cards_display(get_credit_cards, delete_credit_card)

        # Add card form
        card_form = ctk.CTkFrame(parent, fg_color="transparent")
        card_form.pack(fill="x", pady=(0, 10))
        self.ent_card_name    = ctk.CTkEntry(card_form, width=120, placeholder_text="Card name")
        self.ent_card_bank    = ctk.CTkEntry(card_form, width=100, placeholder_text="Bank")
        self.ent_card_limit   = ctk.CTkEntry(card_form, width=90,  placeholder_text="Limit ₱")
        self.ent_card_balance = ctk.CTkEntry(card_form, width=90,  placeholder_text="Balance ₱")
        self.ent_card_pct     = ctk.CTkEntry(card_form, width=70,  placeholder_text="Min % (e.g. 2)")
        self.ent_card_due     = ctk.CTkEntry(card_form, width=60,  placeholder_text="Due day")
        for w in [self.ent_card_name, self.ent_card_bank, self.ent_card_limit,
                  self.ent_card_balance, self.ent_card_pct, self.ent_card_due]:
            w.pack(side="left", padx=(0, 4))
        ctk.CTkButton(card_form, text="+ Add Card", width=90,
                      fg_color="#3B8ED0", hover_color="#2a6db5",
                      command=lambda: self._add_card(add_credit_card, get_credit_cards, delete_credit_card)
                      ).pack(side="left")

    def _save_salary(self, get_salary, set_salary):
        try:
            amount = float(self.ent_salary.get())
            if amount < 0:
                raise ValueError
        except ValueError:
            from tkinter import messagebox
            messagebox.showerror("Error", "Enter a valid positive salary amount.")
            return
        if set_salary(self.user_id, amount):
            from tkinter import messagebox
            messagebox.showinfo("Saved", f"Salary set to ₱{amount:,.2f}/month")
        else:
            from tkinter import messagebox
            messagebox.showerror("Error", "Failed to save salary.")

    def _refresh_loans_display(self, get_loans, delete_loan):
        for w in self.loans_frame.winfo_children():
            w.destroy()
        loans = get_loans(self.user_id)
        if not loans:
            ctk.CTkLabel(self.loans_frame, text="No loans added yet.",
                         font=("Roboto", 11), text_color="silver"
                         ).pack(padx=12, pady=8)
            return
        for loan in loans:
            row = ctk.CTkFrame(self.loans_frame, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=3)
            ctk.CTkLabel(row,
                         text=f"{loan.loan_name} ({loan.bank})  "
                              f"₱{loan.monthly_payment:,.2f}/mo  "
                              f"{loan.months_remaining} months left  "
                              f"{loan.interest_rate}%",
                         font=("Roboto", 11), text_color="white",
                         anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkButton(row, text="✕", width=28, height=24,
                          fg_color="#e74c3c", hover_color="#c0392b",
                          command=lambda lid=loan.id: self._delete_loan(
                              lid, delete_loan, get_loans)
                          ).pack(side="right")

    def _add_loan(self, add_loan, get_loans, delete_loan):
        from tkinter import messagebox
        try:
            name    = self.ent_loan_name.get().strip()
            bank    = self.ent_loan_bank.get().strip()
            total   = float(self.ent_loan_total.get())
            monthly = float(self.ent_loan_monthly.get())
            months  = int(self.ent_loan_months.get())
            rate    = float(self.ent_loan_rate.get() or "0")
            if not name:
                raise ValueError("Name required")
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid input: {e}")
            return
        if add_loan(self.user_id, name, bank, total, monthly, months, rate):
            for ent in [self.ent_loan_name, self.ent_loan_bank, self.ent_loan_total,
                        self.ent_loan_monthly, self.ent_loan_months, self.ent_loan_rate]:
                ent.delete(0, "end")
            self._refresh_loans_display(get_loans, delete_loan)
        else:
            messagebox.showerror("Error", "Failed to save loan.")

    def _delete_loan(self, loan_id, delete_loan, get_loans):
        from models.credit_card import get_credit_cards, delete_credit_card
        delete_loan(loan_id, self.user_id)
        self._refresh_loans_display(get_loans, delete_loan)

    def _refresh_cards_display(self, get_credit_cards, delete_credit_card):
        for w in self.cards_frame.winfo_children():
            w.destroy()
        cards = get_credit_cards(self.user_id)
        if not cards:
            ctk.CTkLabel(self.cards_frame, text="No credit cards added yet.",
                         font=("Roboto", 11), text_color="silver"
                         ).pack(padx=12, pady=8)
            return
        for card in cards:
            row = ctk.CTkFrame(self.cards_frame, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=3)
            util = f"{card.utilization_pct:.0f}% used"
            ctk.CTkLabel(row,
                         text=f"{card.card_name} ({card.bank})  "
                              f"Limit: ₱{card.credit_limit:,.2f}  "
                              f"Balance: ₱{card.current_balance:,.2f}  "
                              f"{util}  Min: {card.minimum_payment_pct}%  "
                              f"Due: Day {card.payment_due_day}",
                         font=("Roboto", 11), text_color="white",
                         anchor="w").pack(side="left", fill="x", expand=True)
            ctk.CTkButton(row, text="✕", width=28, height=24,
                          fg_color="#e74c3c", hover_color="#c0392b",
                          command=lambda cid=card.id: self._delete_card(
                              cid, delete_credit_card, get_credit_cards)
                          ).pack(side="right")

    def _add_card(self, add_credit_card, get_credit_cards, delete_credit_card):
        from tkinter import messagebox
        try:
            name    = self.ent_card_name.get().strip()
            bank    = self.ent_card_bank.get().strip()
            limit   = float(self.ent_card_limit.get())
            balance = float(self.ent_card_balance.get() or "0")
            pct     = float(self.ent_card_pct.get() or "2")
            due     = int(self.ent_card_due.get() or "1")
            if not name:
                raise ValueError("Name required")
        except ValueError as e:
            messagebox.showerror("Error", f"Invalid input: {e}")
            return
        if add_credit_card(self.user_id, name, bank, limit, balance, pct, due):
            for ent in [self.ent_card_name, self.ent_card_bank, self.ent_card_limit,
                        self.ent_card_balance, self.ent_card_pct, self.ent_card_due]:
                ent.delete(0, "end")
            self._refresh_cards_display(get_credit_cards, delete_credit_card)
        else:
            messagebox.showerror("Error", "Failed to save card.")

    def _delete_card(self, card_id, delete_credit_card, get_credit_cards):
        delete_credit_card(card_id, self.user_id)
        self._refresh_cards_display(get_credit_cards, delete_credit_card)

    def _section_label(self, parent, title: str):
        ctk.CTkLabel(parent, text=title, font=("Roboto", 18, "bold")).pack(
            anchor="w", pady=(22, 8))

    # ------------------------------------------------------------------
    # Banner with moderate fade-out
    # ------------------------------------------------------------------

    def _show_banner(self, message: str, bg: str, fg: str):
        """Show a coloured status banner then fade it out after 3 s."""
        # Cancel any pending fade
        if self._fade_job:
            self.frame.after_cancel(self._fade_job)
            self._fade_job = None

        self.banner_frame.configure(fg_color=bg)
        self.lbl_db_status.configure(text=message, text_color=fg)

        # Schedule fade: 10 opacity steps × 60 ms = 600 ms fade starting at 3 s
        def start_fade():
            steps = 10
            delay_ms = 60

            # CustomTkinter doesn't expose alpha, so we approximate by
            # stepping the text colour toward the background colour
            import colorsys

            def hex_to_rgb(h):
                h = h.lstrip("#")
                return tuple(int(h[i:i+2], 16) / 255 for i in (0, 2, 4))

            def lerp(a, b, t):
                return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))

            def rgb_to_hex(rgb):
                return "#{:02x}{:02x}{:02x}".format(
                    int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255))

            fg_rgb = hex_to_rgb(fg)
            bg_rgb = hex_to_rgb(bg)

            def step(n):
                if n > steps:
                    self.banner_frame.configure(fg_color="transparent")
                    self.lbl_db_status.configure(text="")
                    return
                t = n / steps
                blended = lerp(fg_rgb, bg_rgb, t)
                self.lbl_db_status.configure(text_color=rgb_to_hex(blended))
                self.frame.after(delay_ms, lambda: step(n + 1))

            step(0)

        self._fade_job = self.frame.after(3000, start_fade)

    def _set_status_threadsafe(self, message: str, bg: str, fg: str):
        self.frame.after(0, lambda: self._show_banner(message, bg, fg))

    # ------------------------------------------------------------------
    # DB credential actions  (logic untouched)
    # ------------------------------------------------------------------

    def _get_db_form_values(self) -> dict | None:
        host     = self.db_host.get().strip()
        port_str = self.db_port.get().strip()
        database = self.db_name.get().strip()
        user     = self.db_user.get().strip()
        password = self.db_password.get()

        if not host or not database or not user:
            messagebox.showerror("Error", "Host, Database, and Username are required.")
            return None
        try:
            port = int(port_str)
        except ValueError:
            messagebox.showerror("Error", "Port must be a number (default: 3306).")
            return None

        return {"host": host, "port": port, "database": database,
                "user": user, "password": password}

    def _save_db_credentials(self):
        cfg = self._get_db_form_values()
        if not cfg:
            return
        self._show_banner("⟳  Connecting…", BANNER_NEUTRAL_BG, BANNER_NEUTRAL_FG)

        def task():
            from db.connection import save_db_config, init_pool
            try:
                init_pool(cfg)
                save_db_config(cfg)
                self._set_status_threadsafe(
                    "✅  Connected and saved successfully!", BANNER_SUCCESS_BG, BANNER_SUCCESS_FG)
            except Exception as e:
                self._set_status_threadsafe(
                    f"❌  Connection failed: {e}", BANNER_ERROR_BG, BANNER_ERROR_FG)

        threading.Thread(target=task, daemon=True).start()

    def _test_connection(self):
        cfg = self._get_db_form_values()
        if not cfg:
            return
        self._show_banner("⟳  Testing…", BANNER_NEUTRAL_BG, BANNER_NEUTRAL_FG)

        def task():
            import mysql.connector
            try:
                conn = mysql.connector.connect(
                    host=cfg["host"], port=cfg["port"],
                    database=cfg["database"], user=cfg["user"],
                    password=cfg["password"], connection_timeout=5,
                )
                conn.close()
                self._set_status_threadsafe(
                    "✅  Connection successful! (not saved yet)",
                    BANNER_SUCCESS_BG, BANNER_SUCCESS_FG)
            except Exception as e:
                self._set_status_threadsafe(
                    f"❌  Failed: {e}", BANNER_ERROR_BG, BANNER_ERROR_FG)

        threading.Thread(target=task, daemon=True).start()

    # ------------------------------------------------------------------
    # Budget / Category / Export / Delete  (untouched)
    # ------------------------------------------------------------------

    def _set_budget(self):
        try:
            amount = float(self.ent_budget.get())
            if amount <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Error", "Enter a valid positive number.")
            return
        if set_budget(self.user_id, amount):
            messagebox.showinfo("Saved", f"Budget set to \u20b1{amount:,.2f}")
            bus.publish("budget.saved")
        else:
            messagebox.showerror("Error", "Failed to save budget.")

    def _add_category(self):
        name = self.ent_category.get().strip()
        if not name:
            return
        if add_custom_category(self.user_id, name):
            self.ent_category.delete(0, "end")
            messagebox.showinfo("Saved", f"Category '{name}' added.")
            bus.publish("category.saved")
        else:
            messagebox.showerror("Error", "Failed to save category.")

    def _export_expenses_csv(self):
        self._run_export(export_expenses_csv, self.user_id, self.filter_mode.get())

    def _export_income_csv(self):
        self._run_export(export_income_csv, self.user_id, self.filter_mode.get())

    def _export_pdf(self):
        self._run_export(export_summary_pdf, self.user_id, self.username, self.filter_mode.get())

    def _run_export(self, fn, *args):
        self.lbl_export.configure(text="⟳ Exporting…", text_color=COLORS["warning"])
        def task():
            try:
                path = fn(*args)
                self.frame.after(0, lambda: self.lbl_export.configure(
                    text=f"✓ Saved: {path}", text_color=COLOR_REMAINING))
            except Exception as e:
                self.frame.after(0, lambda: self.lbl_export.configure(
                    text=f"✗ Failed: {e}", text_color=COLOR_DANGER))
        threading.Thread(target=task, daemon=True).start()

    def _delete_account(self):
        if not messagebox.askyesno(
            "⚠️ Final Warning",
            f"Delete '{self.username}' and ALL data permanently?\nThis CANNOT be undone.",
        ):
            return
        if delete_account(self.user_id):
            self.on_logout()
        else:
            messagebox.showerror("Error", "Failed to delete account.")

    # ------------------------------------------------------------------
    # Fixed Monthly Bills
    # ------------------------------------------------------------------

    def _build_fixed_bills(self, parent):
        from models.fixed_bills import get_fixed_bills, add_fixed_bill, delete_fixed_bill
        from models.income import get_wallet_list

        # Bills list display
        self.bills_frame = ctk.CTkFrame(parent, fg_color="#1a1a1a", corner_radius=8)
        self.bills_frame.pack(fill="x", pady=(0, 6))
        self._refresh_bills_display(get_fixed_bills, delete_fixed_bill)

        # Total label
        self.lbl_bills_total = ctk.CTkLabel(
            parent, text="", font=("Roboto", 12, "bold"), text_color=COLORS["warning"]
        )
        self.lbl_bills_total.pack(anchor="w", pady=(0, 6))
        self._update_bills_total(get_fixed_bills)

        # Add bill form
        bill_form = ctk.CTkFrame(parent, fg_color="transparent")
        bill_form.pack(fill="x", pady=(0, 10))

        self.ent_bill_name   = ctk.CTkEntry(bill_form, width=150, placeholder_text="Bill name (e.g. Rent)")
        self.ent_bill_amount = ctk.CTkEntry(bill_form, width=110, placeholder_text="Amount ₱")

        wallets = get_wallet_list(self.user_id)
        self.cbo_bill_wallet = ctk.CTkComboBox(bill_form, values=[""] + wallets, width=160)
        self.cbo_bill_wallet.set("")

        for w in [self.ent_bill_name, self.ent_bill_amount, self.cbo_bill_wallet]:
            w.pack(side="left", padx=(0, 4))

        ctk.CTkButton(
            bill_form, text="+ Add Bill", width=90,
            fg_color="#9b59b6", hover_color="#7d3c98",
            command=lambda: self._add_fixed_bill(add_fixed_bill, get_fixed_bills, delete_fixed_bill),
        ).pack(side="left")

    def _refresh_bills_display(self, get_fixed_bills, delete_fixed_bill):
        for w in self.bills_frame.winfo_children():
            w.destroy()
        bills = get_fixed_bills(self.user_id)
        if not bills:
            ctk.CTkLabel(self.bills_frame, text="No fixed bills added yet.",
                         font=("Roboto", 11), text_color="silver").pack(padx=12, pady=8)
            return
        for bill in bills:
            row = ctk.CTkFrame(self.bills_frame, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=3)
            wallet_str = f"  [{bill['wallet']}]" if bill.get("wallet") else ""
            ctk.CTkLabel(
                row,
                text=f"{bill['name']}{wallet_str}  —  ₱{bill['amount']:,.2f}/mo",
                font=("Roboto", 11), text_color="white", anchor="w",
            ).pack(side="left", fill="x", expand=True)
            ctk.CTkButton(
                row, text="✕", width=28, height=24,
                fg_color="#e74c3c", hover_color="#c0392b",
                command=lambda bid=bill["id"]: self._delete_fixed_bill(
                    bid, delete_fixed_bill, get_fixed_bills),
            ).pack(side="right")

    def _update_bills_total(self, get_fixed_bills):
        bills = get_fixed_bills(self.user_id)
        total = sum(b["amount"] for b in bills)
        self.lbl_bills_total.configure(
            text=f"Total fixed bills: ₱{total:,.2f}/mo" if bills else ""
        )

    def _add_fixed_bill(self, add_fixed_bill, get_fixed_bills, delete_fixed_bill):
        from tkinter import messagebox as mb
        name   = self.ent_bill_name.get().strip()
        wallet = self.cbo_bill_wallet.get().strip()
        if not name:
            mb.showerror("Error", "Enter a bill name.")
            return
        try:
            amount = float(self.ent_bill_amount.get())
            if amount <= 0:
                raise ValueError
        except ValueError:
            mb.showerror("Error", "Enter a valid positive amount.")
            return
        if add_fixed_bill(self.user_id, name, amount, wallet):
            self.ent_bill_name.delete(0, "end")
            self.ent_bill_amount.delete(0, "end")
            self.cbo_bill_wallet.set("")
            self._refresh_bills_display(get_fixed_bills, delete_fixed_bill)
            self._update_bills_total(get_fixed_bills)
            bus.publish("fixed_bills.saved")
        else:
            mb.showerror("Error", "Failed to save bill.")

    def _delete_fixed_bill(self, bill_id, delete_fixed_bill, get_fixed_bills):
        delete_fixed_bill(bill_id)
        self._refresh_bills_display(get_fixed_bills, delete_fixed_bill)
        self._update_bills_total(get_fixed_bills)
        bus.publish("fixed_bills.saved")
