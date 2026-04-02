# ui/tabs/add_expense_tab.py
import logging
from datetime import datetime
import customtkinter as ctk
from tkinter import messagebox

from config import COLORS, DATE_FORMAT, DEFAULT_CATEGORIES
from models import add_expense
from services import get_user_categories, add_custom_category
from services.event_bus import bus

logger = logging.getLogger(__name__)


class AddExpenseTab:
    def __init__(self, parent, user_id, username, filter_mode, **kwargs):
        self.parent = parent
        self.user_id = user_id
        self.filter_mode = filter_mode
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.frame.pack(fill="both", expand=True)
        self._build_ui()
        bus.subscribe("category.saved",  self._refresh_categories)
        bus.subscribe("income.saved",     self._refresh_wallets)
        bus.subscribe("income.deleted",   self._refresh_wallets)
        bus.subscribe("filter.changed",   self._refresh_wallets)

    def pack(self, **kwargs):
        pass  # frame already packed in __init__

    def _build_ui(self):
        self.frame.grid_columnconfigure(0, weight=1)
        self.frame.grid_rowconfigure(0, weight=1)

        outer = ctk.CTkFrame(self.frame, fg_color="transparent", border_width=3,
                             border_color=COLORS["primary"], corner_radius=25)
        outer.grid(row=0, column=0, pady=40, padx=20, sticky="ns")

        af = ctk.CTkScrollableFrame(outer, width=450, height=600, fg_color="transparent")
        af.pack(pady=15, padx=15, fill="both", expand=True)

        ctk.CTkLabel(af, text="LOG NEW EXPENSE", font=("Roboto", 26, "bold"),
                     text_color=COLORS["primary"]).pack(pady=(20, 25))

        self.ent_date = self._input(af, "Date (YYYY-MM-DD)")
        self.ent_date.insert(0, datetime.now().strftime(DATE_FORMAT))

        ctk.CTkLabel(af, text="Paid Via", text_color="silver").pack(pady=(10, 2))
        from models import get_wallet_list
        _wallets = get_wallet_list(self.user_id)
        self.cbo_source = ctk.CTkComboBox(af, values=_wallets, width=300)
        if _wallets:
            self.cbo_source.set(_wallets[0])
        self.cbo_source.pack(pady=(0, 10))

        ctk.CTkLabel(af, text="Category", text_color="silver").pack(pady=(10, 2))
        self.cbo_category = ctk.CTkComboBox(
            af, values=get_user_categories(self.user_id, DEFAULT_CATEGORIES), width=300)
        self.cbo_category.pack(pady=(0, 10))

        self.ent_desc = self._input(af, "Description")
        self.ent_amount = self._input(af, "Amount (₱)")

        ctk.CTkButton(af, text="SAVE EXPENSE", command=self._save,
                      height=45, font=("Roboto", 14, "bold")).pack(pady=20)

    def _input(self, parent, label):
        ctk.CTkLabel(parent, text=label).pack(pady=(10, 0))
        e = ctk.CTkEntry(parent, width=300)
        e.pack(pady=(0, 5))
        return e

    def _save(self):
        try:
            amount = float(self.ent_amount.get())
        except ValueError:
            messagebox.showerror("Error", "Amount must be a number.")
            return
        success = add_expense(
            user_id=self.user_id, date=self.ent_date.get(),
            source=self.cbo_source.get(), category=self.cbo_category.get(),
            description=self.ent_desc.get(), amount=amount,
        )
        if success:
            self.ent_desc.delete(0, "end")
            self.ent_amount.delete(0, "end")
            bus.publish("expense.saved")
        else:
            messagebox.showerror("Error", "Failed to save expense.")

    def _refresh_categories(self, **_):
        self.cbo_category.configure(
            values=get_user_categories(self.user_id, DEFAULT_CATEGORIES))

    def _refresh_wallets(self, **_):
        from models import get_wallet_list
        self.cbo_source.configure(values=get_wallet_list(self.user_id))
