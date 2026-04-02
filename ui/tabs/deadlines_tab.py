# ui/tabs/deadlines_tab.py
#
# v4 changes:
#   BUG 1 FIX: subscribe to "filter.changed" so cards load on login
#   BUG 2 FIX: completed cards show ↩ Reactivate button
#   FEATURE:   Multi-wallet allocation UI in add-form and EditDeadlineDialog

import logging
import customtkinter as ctk
from tkinter import messagebox
from datetime import datetime

from config import COLORS, DATE_FORMAT, PRIORITY_LEVELS
from models.deadline import (
    get_deadlines, add_deadline, update_deadline,
    complete_deadline, reactivate_deadline, delete_deadline, DeadlineItem,
)
from models.income import get_wallet_list
from services.budget_service import check_warnings, compute_allocation_statuses
from services.event_bus import bus
from services.time_filter import TimeFilter

logger = logging.getLogger(__name__)

BUCKETS = [
    ("overdue",   "⚠️  OVERDUE",       "#8e44ad"),
    ("high",      "🔴  HIGH PRIORITY", COLORS["danger"]),
    ("medium",    "🟡  DUE SOON",      COLORS["warning"]),
    ("low",       "🟢  UPCOMING",      COLORS["success"]),
    ("completed", "✅  COMPLETED",     "#3498db"),
]

STATUS_COLORS = {
    "funded":   COLORS["success"],
    "at_risk":  COLORS["warning"],
    "unfunded": COLORS["danger"],
}


# ---------------------------------------------------------------------------
# Reusable wallet allocation widget
# ---------------------------------------------------------------------------

class WalletAllocationWidget(ctk.CTkFrame):
    """
    A self-contained widget that lets the user build a list of
    {wallet, amount} allocations. Used in both the add-form and edit dialog.
    """

    def __init__(self, parent, wallets: list[str], **kwargs):
        super().__init__(parent, fg_color="transparent", **kwargs)
        self.wallets = wallets
        self._rows: list[dict] = []   # [{wallet_var, amount_var, frame}, ...]
        self._build_header()
        self.add_row()               # start with one blank row

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", pady=(4, 2))
        ctk.CTkLabel(hdr, text="Wallet Allocations",
                     font=("Roboto", 12, "bold")).pack(side="left")
        ctk.CTkButton(hdr, text="+ Add Wallet", width=100, height=24,
                      command=self.add_row).pack(side="left", padx=8)

    def add_row(self, wallet: str = "", amount: str = ""):
        row_frame = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=6)
        row_frame.pack(fill="x", pady=2)

        wallet_var = ctk.StringVar(value=wallet or (self.wallets[0] if self.wallets else ""))
        amount_var = ctk.StringVar(value=amount)

        cmb = ctk.CTkComboBox(row_frame, variable=wallet_var,
                               values=self.wallets, width=130)
        cmb.pack(side="left", padx=(8, 4), pady=6)

        ent = ctk.CTkEntry(row_frame, textvariable=amount_var,
                            placeholder_text="Amount", width=110)
        ent.pack(side="left", padx=4)

        row_data = {"wallet_var": wallet_var, "amount_var": amount_var, "frame": row_frame}

        def remove(rd=row_data):
            rd["frame"].destroy()
            self._rows.remove(rd)

        ctk.CTkButton(row_frame, text="✕", width=28, height=28,
                      fg_color=COLORS["danger"], hover_color="#c0392b",
                      command=remove).pack(side="left", padx=4)

        self._rows.append(row_data)

    def get_allocations(self) -> list[dict] | None:
        """
        Parse and validate all rows.
        Returns list of {wallet, amount} or None if validation fails.
        """
        result = []
        for rd in self._rows:
            wallet = rd["wallet_var"].get().strip()
            amt_str = rd["amount_var"].get().strip()
            if not wallet and not amt_str:
                continue   # skip empty rows silently
            if not amt_str:
                messagebox.showerror("Error", f"Enter an amount for wallet '{wallet}'.")
                return None
            try:
                amount = float(amt_str)
                if amount <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", f"Amount for '{wallet}' must be a positive number.")
                return None
            result.append({"wallet": wallet, "amount": amount})
        return result  # empty list = no budget

    def load_allocations(self, allocations: list[dict]):
        """Pre-fill from existing allocation data."""
        # Clear existing rows
        for rd in list(self._rows):
            rd["frame"].destroy()
        self._rows.clear()
        if allocations:
            for alloc in allocations:
                self.add_row(wallet=alloc["wallet"], amount=str(alloc["amount"]))
        else:
            self.add_row()

    def refresh_wallets(self, wallets: list[str]):
        self.wallets = wallets
        for rd in self._rows:
            current = rd["wallet_var"].get()
            cmb_widget = rd["frame"].winfo_children()[0]
            cmb_widget.configure(values=wallets)
            if current not in wallets and wallets:
                rd["wallet_var"].set(wallets[0])


# ---------------------------------------------------------------------------
# Edit dialog
# ---------------------------------------------------------------------------

class EditDeadlineDialog(ctk.CTkToplevel):
    def __init__(self, parent, task: DeadlineItem, wallets: list[str],
                 user_id: int, on_save):
        super().__init__(parent)
        self.task = task
        self.user_id = user_id
        self.on_save = on_save
        self.wallets = wallets

        self.title(f"Edit — {task.project_name}")
        self.geometry("560x460")
        self.resizable(False, False)
        self.grab_set()
        self.lift()
        self.focus_force()
        self._build()
        self._prefill()

    def _build(self):
        pad = {"padx": 16, "pady": 5}

        ctk.CTkLabel(self, text="Edit Project / Deadline",
                     font=("Roboto", 15, "bold")).pack(anchor="w", **pad)

        # Name
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row, text="Name:", width=90, anchor="w").pack(side="left")
        self.ent_name = ctk.CTkEntry(row, width=400)
        self.ent_name.pack(side="left")

        # Dates
        row2 = ctk.CTkFrame(self, fg_color="transparent")
        row2.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row2, text="Start:", width=90, anchor="w").pack(side="left")
        self.ent_start = ctk.CTkEntry(row2, width=140, placeholder_text="YYYY-MM-DD")
        self.ent_start.pack(side="left", padx=(0, 12))
        ctk.CTkLabel(row2, text="End:", width=40, anchor="w").pack(side="left")
        self.ent_end = ctk.CTkEntry(row2, width=140, placeholder_text="YYYY-MM-DD")
        self.ent_end.pack(side="left")

        # Total cost + priority
        row3 = ctk.CTkFrame(self, fg_color="transparent")
        row3.pack(fill="x", padx=16, pady=4)
        ctk.CTkLabel(row3, text="Total Cost:", width=90, anchor="w").pack(side="left")
        self.ent_cost = ctk.CTkEntry(row3, width=130, placeholder_text="Optional total")
        self.ent_cost.pack(side="left", padx=(0, 16))
        ctk.CTkLabel(row3, text="Priority:", width=60, anchor="w").pack(side="left")
        self.priority_var = ctk.StringVar(value="Medium")
        self.cmb_priority = ctk.CTkComboBox(row3, variable=self.priority_var,
                                             values=PRIORITY_LEVELS, width=110)
        self.cmb_priority.pack(side="left")

        # Wallet allocation widget
        alloc_frame = ctk.CTkFrame(self, fg_color="transparent")
        alloc_frame.pack(fill="x", padx=16, pady=4)
        self.alloc_widget = WalletAllocationWidget(alloc_frame, wallets=self.wallets)
        self.alloc_widget.pack(fill="x")

        # Buttons
        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(pady=(10, 0))
        ctk.CTkButton(btn_row, text="Save Changes", command=self._save,
                      fg_color=COLORS["primary"], width=130).pack(side="left", padx=8)
        ctk.CTkButton(btn_row, text="Cancel", command=self.destroy,
                      fg_color=COLORS["muted"], width=100).pack(side="left", padx=8)

    def _prefill(self):
        self.ent_name.insert(0, self.task.project_name)
        self.ent_start.insert(0, self.task.start_date.strftime(DATE_FORMAT))
        self.ent_end.insert(0, self.task.end_date.strftime(DATE_FORMAT))
        if self.task.estimated_cost is not None:
            cost_val = self.task.estimated_cost
            cost_str = str(int(cost_val)) if cost_val == int(cost_val) else f"{cost_val:,.2f}"
            self.ent_cost.insert(0, cost_str)
        self.priority_var.set(self.task.priority_level or "Medium")
        self.alloc_widget.load_allocations(self.task.allocations)

    def _save(self):
        name  = self.ent_name.get().strip()
        start = self.ent_start.get().strip()
        end   = self.ent_end.get().strip()
        if not name or not end:
            messagebox.showerror("Error", "Name and end date are required.", parent=self)
            return

        cost_text = self.ent_cost.get().strip()
        estimated_cost = None
        if cost_text:
            try:
                estimated_cost = float(cost_text)
            except ValueError:
                messagebox.showerror("Error", "Total cost must be a number.", parent=self)
                return

        allocations = self.alloc_widget.get_allocations()
        if allocations is None:
            return  # validation error already shown

        priority_level = self.priority_var.get().strip() or None

        if allocations:
            warnings = check_warnings(self.user_id, allocations,
                                      exclude_task_id=self.task.id)
            if warnings:
                msg = "\n\n".join(warnings) + "\n\nSave changes anyway?"
                if not messagebox.askyesno("Budget Warning", msg,
                                           icon="warning", parent=self):
                    return

        self.on_save(self.task.id, name, start, end,
                     estimated_cost, priority_level, allocations)
        self.destroy()


# ---------------------------------------------------------------------------
# Main tab
# ---------------------------------------------------------------------------

class DeadlinesTab:
    def __init__(self, parent, user_id, username, filter_mode, time_filter=None, **kwargs):
        self.parent = parent
        self.user_id = user_id
        self.time_filter: TimeFilter = time_filter if time_filter is not None else TimeFilter()
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.frame.pack(fill="both", expand=True)
        self._build_ui()
        # BUG 1 FIX: subscribe to filter.changed so cards load immediately on login
        bus.subscribe("filter.changed",      self.reload)
        bus.subscribe("time_filter.changed", self.reload)
        bus.subscribe("deadline.saved",  self.reload)
        bus.subscribe("deadline.done",   self.reload)
        bus.subscribe("income.saved",    self._refresh_wallet_list)

    def pack(self, **kwargs):
        pass

    # ------------------------------------------------------------------
    # UI Build
    # ------------------------------------------------------------------

    def _build_ui(self):
        form_frame = ctk.CTkFrame(self.frame, corner_radius=12)
        form_frame.pack(fill="x", padx=15, pady=(15, 8))

        ctk.CTkLabel(form_frame, text="Add Deadline / Project",
                     font=("Roboto", 15, "bold")).pack(anchor="w", padx=15, pady=(10, 5))

        # Row 1: name / dates / priority / add button
        row1 = ctk.CTkFrame(form_frame, fg_color="transparent")
        row1.pack(fill="x", padx=15, pady=(0, 4))

        self.ent_dl_name  = ctk.CTkEntry(row1, placeholder_text="Project / Task name", width=200)
        self.ent_dl_start = ctk.CTkEntry(row1, placeholder_text="Start (YYYY-MM-DD)", width=140)
        self.ent_dl_end   = ctk.CTkEntry(row1, placeholder_text="End (YYYY-MM-DD)", width=140)
        self.ent_dl_start.insert(0, datetime.now().strftime(DATE_FORMAT))
        for w in (self.ent_dl_name, self.ent_dl_start, self.ent_dl_end):
            w.pack(side="left", padx=4)

        ctk.CTkLabel(row1, text="Priority:", text_color="silver",
                     font=("Roboto", 12)).pack(side="left", padx=(8, 3))
        self.priority_var = ctk.StringVar(value="Medium")
        ctk.CTkComboBox(row1, variable=self.priority_var,
                         values=PRIORITY_LEVELS, width=100).pack(side="left", padx=4)

        ctk.CTkButton(row1, text="Add Deadline", command=self._add,
                      width=110).pack(side="left", padx=8)

        # Row 2: optional total cost
        row2 = ctk.CTkFrame(form_frame, fg_color="transparent")
        row2.pack(fill="x", padx=15, pady=(0, 4))
        ctk.CTkLabel(row2, text="Total Est. Cost (optional):",
                     font=("Roboto", 12), text_color="silver").pack(side="left", padx=(0, 6))
        self.ent_cost = ctk.CTkEntry(row2, placeholder_text="e.g. 10000", width=120)
        self.ent_cost.pack(side="left")

        # Row 3: wallet allocation widget (always visible)
        row3 = ctk.CTkFrame(form_frame, fg_color="transparent")
        row3.pack(fill="x", padx=15, pady=(0, 10))
        self.alloc_widget = WalletAllocationWidget(row3, wallets=self._get_wallets())
        self.alloc_widget.pack(fill="x")

        # Kanban board
        scroll = ctk.CTkScrollableFrame(self.frame, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=10, pady=5)
        scroll.columnconfigure(list(range(len(BUCKETS))), weight=1)

        self.bucket_frames = {}
        for col_idx, (key, label, color) in enumerate(BUCKETS):
            col = ctk.CTkFrame(scroll, corner_radius=10, fg_color="#1e1e1e")
            col.grid(row=0, column=col_idx, sticky="nsew", padx=6, pady=4)
            ctk.CTkLabel(col, text=label, font=("Roboto", 12, "bold"),
                         text_color=color).pack(pady=(10, 5), padx=8, anchor="w")
            content = ctk.CTkFrame(col, fg_color="transparent")
            content.pack(fill="both", expand=True, padx=4, pady=(0, 8))
            self.bucket_frames[key] = content

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_wallets(self) -> list[str]:
        w = get_wallet_list(self.user_id)
        return w if w else ["Cash"]

    def _refresh_wallet_list(self, **_):
        wallets = self._get_wallets()
        self.alloc_widget.refresh_wallets(wallets)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def reload(self, **_):
        for frame in self.bucket_frames.values():
            for widget in frame.winfo_children():
                widget.destroy()
        for task in get_deadlines(self.user_id):
            self._render_card(task)

    def _render_card(self, task: DeadlineItem):
        target = self.bucket_frames.get(task.triage)
        if not target:
            return

        card = ctk.CTkFrame(target, fg_color="#2b2b2b", corner_radius=8)
        card.pack(fill="x", pady=4)
        self._bind_double_click(card, task)

        ctk.CTkLabel(card, text=task.project_name,
                     font=("Roboto", 13, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
        ctk.CTkLabel(card, text=task.status_text, font=("Roboto", 10),
                     text_color=task.bar_color).pack(anchor="w", padx=10)
        ctk.CTkLabel(card, text=f"Due: {task.end_date.strftime('%b %d, %Y')}",
                     font=("Roboto", 10), text_color="silver").pack(anchor="w", padx=10)

        if task.priority_level:
            ctk.CTkLabel(card, text=f"Priority: {task.priority_level}",
                         font=("Roboto", 10), text_color="silver").pack(anchor="w", padx=10)

        # Budget badge — show each allocation
        if task.allocations:
            for alloc in task.allocations:
                ctk.CTkLabel(
                    card,
                    text=f"  💰 {alloc['wallet']}: ₱{alloc['amount']:,.2f}",
                    font=("Roboto", 10),
                    text_color=COLORS["primary"],
                ).pack(anchor="w", padx=10)

        pb = ctk.CTkProgressBar(card, progress_color=task.bar_color)
        pb.pack(fill="x", padx=10, pady=4)
        pb.set(task.progress)

        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(anchor="e", padx=10, pady=(0, 8))

        # Edit — always available
        ctk.CTkButton(btn_row, text="✏️ Edit", width=70, height=24,
                      fg_color=COLORS["primary"], hover_color="#2a6db5",
                      command=lambda t=task: self._open_edit(t)
                      ).pack(side="left", padx=(0, 6))

        if task.triage == "completed":
            # BUG 2 FIX: completed cards now have a Reactivate button
            ctk.CTkButton(btn_row, text="↩ Reactivate", width=100, height=24,
                          fg_color="#8e44ad", hover_color="#6c3483",
                          command=lambda i=task.id: self._reactivate(i)
                          ).pack(side="left", padx=(0, 6))
        else:
            ctk.CTkButton(btn_row, text="✓ Mark Done", width=90, height=24,
                          fg_color=COLORS["success"], hover_color="#27ae60",
                          command=lambda i=task.id: self._complete(i)
                          ).pack(side="left", padx=(0, 6))

        # Delete — always available, requires confirmation
        ctk.CTkButton(btn_row, text="🗑", width=30, height=24,
                      fg_color=COLORS["danger"], hover_color="#c0392b",
                      command=lambda i=task.id, n=task.project_name: self._delete(i, n)
                      ).pack(side="left")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _bind_double_click(self, widget, task):
        """Bind double-click on a card frame and all its children."""
        def handler(event, t=task):
            self._open_goal_tracker(t)
        widget.bind("<Double-Button-1>", handler)
        for child in widget.winfo_children():
            try:
                child.bind("<Double-Button-1>", handler)
            except Exception:
                pass

    def _open_goal_tracker(self, task):
        """Open the Goal Tracker overlay for the given project."""
        try:
            from ui.goal_tracker_overlay import GoalTrackerOverlay
            GoalTrackerOverlay(self.frame, task=task, user_id=self.user_id)
        except Exception as e:
            import traceback; traceback.print_exc()
            from tkinter import messagebox
            messagebox.showerror("Error", f"Could not open Goal Tracker:\n{e}")

    def _add(self):
        name  = self.ent_dl_name.get().strip()
        start = self.ent_dl_start.get().strip()
        end   = self.ent_dl_end.get().strip()
        if not name or not end:
            messagebox.showerror("Error", "Project name and end date are required.")
            return

        cost_text = self.ent_cost.get().strip()
        estimated_cost = None
        if cost_text:
            try:
                estimated_cost = float(cost_text)
            except ValueError:
                messagebox.showerror("Error", "Total cost must be a number.")
                return

        allocations = self.alloc_widget.get_allocations()
        if allocations is None:
            return

        priority_level = self.priority_var.get().strip() or None

        if allocations:
            warnings = check_warnings(self.user_id, allocations)
            if warnings:
                msg = "\n\n".join(warnings) + "\n\nSave this project anyway?"
                if not messagebox.askyesno("Budget Warning", msg, icon="warning"):
                    return

        ok, err = add_deadline(self.user_id, name, start, end,
                               estimated_cost, priority_level, allocations)
        if ok:
            self.ent_dl_name.delete(0, "end")
            self.ent_dl_end.delete(0, "end")
            self.ent_cost.delete(0, "end")
            self.alloc_widget.load_allocations([])
            bus.publish("deadline.saved")
            bus.publish("deadline.budget_saved")
        else:
            messagebox.showerror("Error", f"Failed to add deadline.\n\n{err}")

    def _open_edit(self, task: DeadlineItem):
        EditDeadlineDialog(
            parent=self.frame,
            task=task,
            wallets=self._get_wallets(),
            user_id=self.user_id,
            on_save=self._save_edit,
        )

    def _save_edit(self, task_id, name, start, end,
                   estimated_cost, priority_level, allocations):
        if update_deadline(task_id, name, start, end,
                           estimated_cost, priority_level, allocations):
            bus.publish("deadline.saved")
            bus.publish("deadline.budget_saved")
        else:
            messagebox.showerror("Error", "Failed to save changes.")

    def _complete(self, task_id):
        if complete_deadline(task_id):
            bus.publish("deadline.done")
            bus.publish("deadline.budget_saved")
        else:
            messagebox.showerror("Error", "Failed to mark as complete.")

    def _reactivate(self, task_id):
        # BUG 2 FIX: restore Completed → Active
        if reactivate_deadline(task_id):
            bus.publish("deadline.done")
            bus.publish("deadline.budget_saved")
        else:
            messagebox.showerror("Error", "Failed to reactivate project.")

    def _delete(self, task_id, project_name):
        if not messagebox.askyesno(
            "Delete Project",
            f"Permanently delete '{project_name}'?\n\n"
            "This will also remove all wallet allocations for this project.\n"
            "This cannot be undone.",
            icon="warning",
        ):
            return
        if delete_deadline(task_id):
            bus.publish("deadline.saved")
            bus.publish("deadline.budget_saved")
        else:
            messagebox.showerror("Error", "Failed to delete project.")
