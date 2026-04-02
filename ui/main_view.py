# ui/main_view.py — Tab shell and event bus wiring
# 💎 Dev: Plain object, no CTkFrame subclassing.

import logging
import time
import threading

import customtkinter as ctk

from config import COLORS
from services.event_bus import bus
from services.time_filter import TimeFilter

logger = logging.getLogger(__name__)


class MainView:
    def __init__(self, parent, user_id: int, username: str, on_logout):
        self.parent = parent
        self.user_id = user_id
        self.username = username
        self.on_logout = on_logout
        self.filter_mode = ctk.StringVar(value="This Month")
        self.time_filter = TimeFilter()   # granular per-tab filter; resets to 'all' on each login

        bus.clear()

        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.frame.pack(fill="both", expand=True)

        self._show_loading()
        threading.Thread(target=self._load_in_background, daemon=True).start()

    def destroy(self):
        self.frame.destroy()

    def _show_loading(self):
        self.loading_frame = ctk.CTkFrame(self.frame, fg_color="transparent")
        self.loading_frame.pack(fill="both", expand=True)
        ctk.CTkLabel(self.loading_frame, text="Loading Dashboard...",
                     font=("Roboto", 24, "bold")).pack(pady=(120, 20))
        self.progress_bar = ctk.CTkProgressBar(self.loading_frame, width=300, height=20)
        self.progress_bar.pack(pady=10)
        self.progress_bar.set(0)
        self.progress_label = ctk.CTkLabel(self.loading_frame, text="Initializing...",
                                           font=("Roboto", 12))
        self.progress_label.pack(pady=8)

    def _set_progress(self, value: float, label: str):
        self.frame.after(0, lambda: self.progress_bar.set(value))
        self.frame.after(0, lambda: self.progress_label.configure(text=label))

    def _load_in_background(self):
        try:
            self._set_progress(0.1, "Building interface...")
            self.frame.after(0, self._build_main_ui)
            time.sleep(0.3)

            self._set_progress(0.3, "Setting up tabs...")
            self.frame.after(0, self._build_tabs)
            time.sleep(0.4)

            self._set_progress(0.9, "Loading data...")
            self.frame.after(0, self._wire_and_load)

            self._set_progress(1.0, "Ready!")
            self.frame.after(400, self._hide_loading)

        except Exception as e:
            logger.error("Failed to load MainView: %s", e)
            self.frame.after(0, self.on_logout)

    def _hide_loading(self):
        if self.loading_frame.winfo_exists():
            self.loading_frame.destroy()

    def _build_main_ui(self):
        header = ctk.CTkFrame(self.frame, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(10, 0))

        ctk.CTkLabel(header, text=f"Welcome, {self.username}",
                     font=("Roboto", 16, "bold")).pack(side="left")

        ctk.CTkSegmentedButton(
            header,
            values=["This Month", "This Year", "All Time"],
            variable=self.filter_mode,
            command=lambda _: bus.publish("filter.changed"),
        ).pack(side="left", padx=20)

        ctk.CTkButton(header, text="Logout", command=self._logout,
                      fg_color=COLORS["danger"], width=80, height=28).pack(side="right")

        self.tabview = ctk.CTkTabview(
            self.frame,
            segmented_button_fg_color="#1e1e1e",
            segmented_button_selected_color=COLORS["primary"],
        )
        self.tabview.pack(padx=20, pady=10, fill="both", expand=True)

        for name in ["Add Expense", "Manage Data", "My Wallet",
                     "Analytics", "Deadlines", "Project Budgets", "Buy Advisor", "Settings"]:
            self.tabview.add(name)

    def _build_tabs(self):
        from ui.tabs.add_expense_tab import AddExpenseTab
        from ui.tabs.project_budgets_tab import ProjectBudgetsTab
        from ui.tabs.manage_data_tab import ManageDataTab
        from ui.tabs.wallet_tab import WalletTab
        from ui.tabs.analytics_tab import AnalyticsTab
        from ui.tabs.deadlines_tab import DeadlinesTab
        from ui.tabs.settings_tab import SettingsTab
        from ui.tabs.buy_advisor_tab import BuyAdvisorTab

        ctx = {"user_id": self.user_id, "username": self.username,
               "filter_mode": self.filter_mode, "time_filter": self.time_filter}

        import traceback
        def _make(cls, parent, **kw):
            try:
                return cls(parent, **kw)
            except Exception as e:
                traceback.print_exc()
                logger.error("Failed to build tab %s: %s", cls.__name__, e)
                return None

        self.tab_add          = _make(AddExpenseTab,    self.tabview.tab("Add Expense"), **ctx)
        self.tab_manage       = _make(ManageDataTab,    self.tabview.tab("Manage Data"), **ctx)
        self.tab_wallet       = _make(WalletTab,        self.tabview.tab("My Wallet"), **ctx)
        self.tab_analytics    = _make(AnalyticsTab,     self.tabview.tab("Analytics"), **ctx)
        self.tab_deadlines    = _make(DeadlinesTab,     self.tabview.tab("Deadlines"), **ctx)
        self.tab_proj_budgets = _make(ProjectBudgetsTab,self.tabview.tab("Project Budgets"), **ctx)
        self.tab_buy_advisor  = _make(BuyAdvisorTab,   self.tabview.tab("Buy Advisor"), **ctx)
        self.tab_settings     = _make(SettingsTab,      self.tabview.tab("Settings"),
                                      **ctx, on_logout=self._logout)

        for tab in [self.tab_add, self.tab_manage, self.tab_wallet,
                    self.tab_analytics, self.tab_deadlines, self.tab_proj_budgets, self.tab_buy_advisor, self.tab_settings]:
            if tab is not None:
                tab.pack(fill="both", expand=True)

    def _wire_and_load(self):
        bus.publish("filter.changed")

    def _logout(self):
        bus.clear()
        self.on_logout()
