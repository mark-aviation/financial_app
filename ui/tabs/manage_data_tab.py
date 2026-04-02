# ui/tabs/manage_data_tab.py
#
# v5 additions:
#   - Quick filter bar (All / This Week / This Month / This Year / Custom ▾)
#   - Chained custom dropdowns (Year → Month → Week)
#   - Summary card below existing summary (period · total · count · highest · top category)
#   - Empty-state overlay when no data for selected period
#   - Publishes "time_filter.changed" via the event bus

import logging
import customtkinter as ctk
from tkinter import ttk, messagebox

from config import COLORS
from models import get_expenses_df, update_expense, delete_expenses, get_wallet_list
from models.expense import get_expenses_df_filtered, get_summary_stats
from services.event_bus import bus
from services.time_filter import (
    TimeFilter, MONTH_NAMES,
    MODE_ALL, MODE_THIS_WEEK, MODE_THIS_MONTH, MODE_THIS_YEAR, MODE_CUSTOM,
    get_period_label, get_available_years, get_available_months,
    get_weeks_in_month, get_week_label,
)

logger = logging.getLogger(__name__)

_BTN_INACTIVE = {
    "fg_color": "#2b2b2b",
    "text_color": "silver",
    "border_width": 1,
    "border_color": "#3d3d3d",
    "hover_color": "#383838",
    "corner_radius": 14,
    "height": 28,
    "font": ("Segoe UI", 11),
}
_BTN_ACTIVE = {
    "fg_color": COLORS["primary"],
    "text_color": "white",
    "border_width": 0,
    "hover_color": COLORS["primary"],
    "corner_radius": 14,
    "height": 28,
    "font": ("Segoe UI", 11, "bold"),
}
_BTN_CUSTOM_INACTIVE = {**_BTN_INACTIVE, "border_color": "#4a4a6a"}


class ManageDataTab:
    def __init__(self, parent, user_id, username, filter_mode, time_filter=None, **kwargs):
        self.parent      = parent
        self.user_id     = user_id
        self.filter_mode = filter_mode
        self.time_filter: TimeFilter = time_filter if time_filter is not None else TimeFilter()

        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.frame.pack(fill="both", expand=True)
        self._apply_tree_style()
        self._build_ui()

        bus.subscribe("expense.saved",       self.reload)
        bus.subscribe("expense.deleted",     self.reload)
        bus.subscribe("filter.changed",      self.reload)
        bus.subscribe("time_filter.changed", self._on_time_filter_changed)

    def pack(self, **kwargs):
        pass

    def _apply_tree_style(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#2b2b2b", foreground="white",
                        fieldbackground="#2b2b2b", rowheight=35, font=("Segoe UI", 11))
        style.configure("Treeview.Heading", font=("Segoe UI", 12, "bold"),
                        background=COLORS["primary"], foreground="white", relief="flat")
        style.map("Treeview", background=[("selected", "#1f6aa5")])

    def _build_ui(self):
        # Container holds filter bar + custom dropdowns together
        # so dropdowns always appear directly below the pills
        self._filter_container = ctk.CTkFrame(self.frame, fg_color="transparent")
        self._filter_container.pack(fill="x", padx=0, pady=0)
        self._build_filter_bar()
        self._build_custom_dropdowns()
        self._build_summary_card()

        top = ctk.CTkFrame(self.frame, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(4, 4))
        ctk.CTkLabel(top, text="Search:").pack(side="left", padx=(0, 5))
        self.ent_search = ctk.CTkEntry(top, width=250, placeholder_text="Filter by description...")
        self.ent_search.pack(side="left")
        self.ent_search.bind("<KeyRelease>", lambda e: self.reload())

        cols = ("ID", "Date", "Source", "Category", "Description", "Amount")
        self.tree = ttk.Treeview(self.frame, columns=cols, show="headings", selectmode="extended")
        for col, w in zip(cols, (50, 100, 110, 130, 280, 100)):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w)
        self.tree.pack(fill="both", expand=True, padx=10, pady=(0, 5))
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        self.lbl_empty = ctk.CTkLabel(
            self.tree, text="", font=("Segoe UI", 13), text_color="silver",
        )

        edit = ctk.CTkFrame(self.frame, fg_color="transparent")
        edit.pack(fill="x", padx=10, pady=5)

        ctk.CTkLabel(edit, text="Date").pack(side="left", padx=(10, 2))
        self.edit_date = ctk.CTkEntry(edit, width=120)
        self.edit_date.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(edit, text="Source").pack(side="left", padx=(0, 2))
        self.edit_source = ctk.CTkComboBox(edit, values=["Cash"], width=130)
        self.edit_source.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(edit, text="Description").pack(side="left", padx=(0, 2))
        self.edit_desc = ctk.CTkEntry(edit, width=250)
        self.edit_desc.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(edit, text="Amount").pack(side="left", padx=(0, 2))
        self.edit_amt = ctk.CTkEntry(edit, width=100)
        self.edit_amt.pack(side="left", padx=(0, 10))

        ctk.CTkButton(edit, text="Update", command=self._update, width=80).pack(side="left", padx=5)
        ctk.CTkButton(edit, text="Delete", command=self._delete,
                      fg_color=COLORS["danger"], width=80).pack(side="left", padx=5)

    def _build_filter_bar(self):
        bar = ctk.CTkFrame(self._filter_container, fg_color="transparent")
        bar.pack(fill="x", padx=10, pady=(8, 2))

        self._filter_buttons = {}
        for label, mode in [
            ("All",        MODE_ALL),
            ("This Week",  MODE_THIS_WEEK),
            ("This Month", MODE_THIS_MONTH),
            ("This Year",  MODE_THIS_YEAR),
            ("Custom ▾",   MODE_CUSTOM),
        ]:
            kw = dict(_BTN_CUSTOM_INACTIVE if mode == MODE_CUSTOM else _BTN_INACTIVE)
            btn = ctk.CTkButton(
                bar, text=label, width=90,
                command=lambda m=mode: self._set_quick_filter(m),
                **kw,
            )
            btn.pack(side="left", padx=(0, 6))
            self._filter_buttons[mode] = btn

        self._highlight_active_button()

    def _build_custom_dropdowns(self):
        self.custom_frame = ctk.CTkFrame(
            self._filter_container, fg_color="#1c1c2e", corner_radius=8,
            border_width=1, border_color="#2e2e4a",
        )

        row = ctk.CTkFrame(self.custom_frame, fg_color="transparent")
        row.pack(fill="x", padx=10, pady=8)

        for attr, label_txt, width, cmd in [
            ("cbo_year",  "YEAR",  100, self._on_year_change),
            ("cbo_month", "MONTH", 130, self._on_month_change),
            ("cbo_week",  "WEEK",  100, self._on_week_change),
        ]:
            col = ctk.CTkFrame(row, fg_color="transparent")
            col.pack(side="left", padx=(0, 10))
            ctk.CTkLabel(col, text=label_txt, font=("Segoe UI", 9),
                         text_color="silver").pack(anchor="w")
            cbo = ctk.CTkComboBox(col, values=["—"], width=width, command=cmd)
            cbo.pack()
            setattr(self, attr, cbo)

        ctk.CTkButton(
            row, text="✕  Clear", width=70, height=28,
            fg_color="transparent", text_color="silver",
            hover_color="#2b2b2b", border_width=0,
            font=("Segoe UI", 11),
            command=self._clear_filter,
        ).pack(side="left", padx=(4, 0))

    def _build_summary_card(self):
        # Compact single-row strip — accent bar | period | 4 stats
        self.summary_card = ctk.CTkFrame(
            self.frame, fg_color="#1a1a1a", corner_radius=8,
            border_width=0, height=56,
        )
        self.summary_card.pack(fill="x", padx=10, pady=(2, 4))
        self.summary_card.pack_propagate(False)

        accent = ctk.CTkFrame(self.summary_card, fg_color=COLORS["primary"],
                               width=4, corner_radius=0)
        accent.pack(side="left", fill="y")

        # Period label
        self.lbl_period = ctk.CTkLabel(
            self.summary_card, text="All Time",
            font=("Segoe UI", 12, "bold"), text_color="white", width=100, anchor="w",
        )
        self.lbl_period.pack(side="left", padx=(12, 12))

        # Thin separator
        ctk.CTkFrame(self.summary_card, fg_color="#333333",
                     width=1).pack(side="left", fill="y", pady=6)

        def stat_col(title, color):
            col = ctk.CTkFrame(self.summary_card, fg_color="transparent")
            col.pack(side="left", padx=(16, 0))
            ctk.CTkLabel(col, text=title, font=("Segoe UI", 8),
                         text_color="#666666").pack(anchor="w")
            lbl = ctk.CTkLabel(col, text="₱0.00", font=("Segoe UI", 11, "bold"),
                                text_color=color)
            lbl.pack(anchor="w")
            return lbl

        self.stat_total    = stat_col("TOTAL SPENT",    COLORS["primary"])
        self.stat_count    = stat_col("TRANSACTIONS",   COLORS["success"])
        self.stat_highest  = stat_col("HIGHEST SINGLE", COLORS["warning"])
        self.stat_category = stat_col("TOP CATEGORY",   "silver")

    # ── Filter logic ──────────────────────────────────────────────────────

    def _highlight_active_button(self):
        for mode, btn in self._filter_buttons.items():
            if mode == self.time_filter.mode:
                btn.configure(**_BTN_ACTIVE)
            else:
                kw = dict(_BTN_CUSTOM_INACTIVE if mode == MODE_CUSTOM else _BTN_INACTIVE)
                btn.configure(**kw)

    def _set_quick_filter(self, mode: str):
        if mode == MODE_CUSTOM:
            self.time_filter.mode = MODE_CUSTOM
            self._show_custom_dropdowns()
            self._populate_year_dropdown()
        else:
            self.time_filter.mode  = mode
            self.time_filter.year  = None
            self.time_filter.month = None
            self.time_filter.week  = None
            self._hide_custom_dropdowns()
            bus.publish("time_filter.changed")
        self._highlight_active_button()

    def _show_custom_dropdowns(self):
        self.custom_frame.pack(fill="x", padx=10, pady=(0, 4))

    def _hide_custom_dropdowns(self):
        self.custom_frame.pack_forget()

    def _clear_filter(self):
        self.time_filter.mode  = MODE_ALL
        self.time_filter.year  = None
        self.time_filter.month = None
        self.time_filter.week  = None
        self._hide_custom_dropdowns()
        self._highlight_active_button()
        bus.publish("time_filter.changed")

    def _populate_year_dropdown(self):
        years = get_available_years(self.user_id)
        year_labels = [str(y) for y in years] if years else ["—"]
        self.cbo_year.configure(values=year_labels)
        self.cbo_year.set(year_labels[0])
        self._on_year_change(year_labels[0])

    def _on_year_change(self, value: str):
        try:
            self.time_filter.year = int(value)
        except (ValueError, TypeError):
            self.time_filter.year = None
        self.time_filter.month = None
        self.time_filter.week  = None

        if self.time_filter.year:
            months = get_available_months(self.user_id, self.time_filter.year)
            month_labels = [f"{MONTH_NAMES[m]} ({m})" for m in months] if months else ["—"]
        else:
            month_labels = ["—"]
        self.cbo_month.configure(values=month_labels)
        self.cbo_month.set(month_labels[0])
        self.cbo_week.configure(values=["—"])
        self.cbo_week.set("—")
        bus.publish("time_filter.changed")

    def _on_month_change(self, value: str):
        try:
            self.time_filter.month = int(value.split("(")[-1].rstrip(")"))
        except (ValueError, IndexError):
            self.time_filter.month = None
        self.time_filter.week = None

        if self.time_filter.year and self.time_filter.month:
            weeks = get_weeks_in_month(self.time_filter.year, self.time_filter.month)
            week_labels = ["All Weeks"] + [get_week_label(w) for w in weeks]
        else:
            week_labels = ["—"]
        self.cbo_week.configure(values=week_labels)
        self.cbo_week.set(week_labels[0])
        bus.publish("time_filter.changed")

    def _on_week_change(self, value: str):
        if value in ("—", "All Weeks"):
            self.time_filter.week = None
        else:
            try:
                self.time_filter.week = int(value.split()[-1])
            except (ValueError, IndexError):
                self.time_filter.week = None
        bus.publish("time_filter.changed")

    # ── Reload ────────────────────────────────────────────────────────────

    def _on_time_filter_changed(self, **_):
        self.reload()

    def reload(self, **_):
        self._update_summary_card()

        for item in self.tree.get_children():
            self.tree.delete(item)
        self.lbl_empty.place_forget()

        search = self.ent_search.get() if hasattr(self, "ent_search") else ""
        df = get_expenses_df_filtered(self.user_id, self.time_filter, search=search)

        if df.empty:
            label = get_period_label(self.time_filter)
            self.lbl_empty.configure(
                text=f"No expenses found for {label}\nTry selecting a different period."
            )
            self.lbl_empty.place(relx=0.5, rely=0.4, anchor="center")
        else:
            for _, r in df.iterrows():
                self.tree.insert("", "end", values=(
                    r["ID"], r["Date"].strftime("%Y-%m-%d"), r["Source"],
                    r["Category"], r["Description"], f"₱{r['Amount']:,.2f}",
                ))

        self.edit_source.configure(values=get_wallet_list(self.user_id))

    def _update_summary_card(self):
        self.lbl_period.configure(text=get_period_label(self.time_filter))
        stats = get_summary_stats(self.user_id, self.time_filter)
        self.stat_total.configure(text=f"₱{stats['total']:,.2f}")
        self.stat_count.configure(text=str(stats["count"]))
        self.stat_highest.configure(text=f"₱{stats['highest']:,.2f}")
        self.stat_category.configure(text=stats["top_category"])

    # ── Edit / delete ─────────────────────────────────────────────────────

    def _on_select(self, _):
        sel = self.tree.selection()
        if sel:
            v = self.tree.item(sel[-1])["values"]
            self.edit_date.delete(0, "end"); self.edit_date.insert(0, v[1])
            self.edit_source.set(v[2])
            self.edit_desc.delete(0, "end"); self.edit_desc.insert(0, v[4])
            self.edit_amt.delete(0, "end")
            self.edit_amt.insert(0, str(v[5]).replace("₱", "").replace(",", ""))

    def _update(self):
        sel = self.tree.selection()
        if not sel:
            return
        rid = self.tree.item(sel[0])["values"][0]
        try:
            amount = float(self.edit_amt.get())
        except ValueError:
            messagebox.showerror("Error", "Amount must be a number.")
            return
        if update_expense(rid, self.user_id, self.edit_date.get(),
                          self.edit_source.get(), self.edit_desc.get(), amount):
            bus.publish("expense.saved")
        else:
            messagebox.showerror("Error", "Update failed.")

    def _delete(self):
        selected = self.tree.selection()
        if not selected:
            return
        if messagebox.askyesno("Confirm", f"Delete {len(selected)} record(s)?"):
            ids = [self.tree.item(i)["values"][0] for i in selected]
            if delete_expenses(ids, self.user_id):
                bus.publish("expense.deleted")
            else:
                messagebox.showerror("Error", "Delete failed.")
