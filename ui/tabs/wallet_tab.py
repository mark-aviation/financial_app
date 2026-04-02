# ui/tabs/wallet_tab.py
import logging
import customtkinter as ctk
from tkinter import ttk, messagebox
from datetime import datetime

from config import COLORS, DATE_FORMAT
from models import get_income_df, add_income, update_income, delete_income, get_wallet_list, transfer_funds, get_income_metadata
from models.fixed_bills import get_total_fixed_bills
from models.budget import get_latest_budget
from services.analytics_service import get_summary_totals, get_wallet_balances
from services.event_bus import bus
from services.time_filter import TimeFilter, get_period_label, apply_time_filter_to_df

logger = logging.getLogger(__name__)


class WalletTab:
    def __init__(self, parent, user_id, username, filter_mode, time_filter=None, **kwargs):
        self.parent = parent
        self.user_id = user_id
        self.filter_mode = filter_mode
        self.time_filter: TimeFilter = time_filter if time_filter is not None else TimeFilter()
        self.frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.frame.pack(fill="both", expand=True)
        self._build_ui()
        bus.subscribe("expense.saved",   self.reload)
        bus.subscribe("expense.deleted", self.reload)
        bus.subscribe("income.saved",    self.reload)
        bus.subscribe("income.deleted",  self.reload)
        bus.subscribe("budget.saved",    self.reload)
        bus.subscribe("fixed_bills.saved", self.reload)
        bus.subscribe("filter.changed",      self.reload)
        bus.subscribe("time_filter.changed", self.reload)

    def pack(self, **kwargs):
        pass

    def _build_ui(self):
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=1)
        self.frame.rowconfigure(1, weight=1)

        # Summary cards
        cards = ctk.CTkFrame(self.frame, fg_color="transparent")
        cards.grid(row=0, column=0, columnspan=2, sticky="ew", padx=15, pady=(15, 5))
        cards.columnconfigure((0, 1, 2, 3, 4), weight=1)
        self.lbl_in   = self._card(cards, "Total Income",    COLORS["success"], 0)
        self.lbl_out  = self._card(cards, "Total Spent",     COLORS["danger"],  1)
        self.lbl_bills= self._card(cards, "Fixed Bills/mo",  COLORS["warning"], 2)
        self.lbl_net  = self._card(cards, "Net Balance",     COLORS["primary"], 3)
        self.lbl_disp = self._card(cards, "After Fixed Bills", "#9b59b6",       4)

        # Budget + wallet balances
        left = ctk.CTkFrame(self.frame, corner_radius=12)
        left.grid(row=1, column=0, sticky="nsew", padx=(15, 8), pady=8)

        ctk.CTkLabel(left, text="Monthly Budget", font=("Roboto", 16, "bold")).pack(pady=(15, 5))
        self.lbl_budget = ctk.CTkLabel(left, text="No budget set.", font=("Roboto", 12))
        self.lbl_budget.pack()
        self.progress_budget = ctk.CTkProgressBar(left, width=300)
        self.progress_budget.pack(pady=8)
        self.progress_budget.set(0)

        ctk.CTkLabel(left, text="Per-Wallet Balance", font=("Roboto", 14, "bold")).pack(pady=(20, 5))
        self.bal_tree = ttk.Treeview(left, columns=("Wallet", "Balance"), show="headings", height=6)
        self.bal_tree.heading("Wallet",  text="Wallet")
        self.bal_tree.heading("Balance", text="Balance")
        self.bal_tree.column("Wallet",  width=160)
        self.bal_tree.column("Balance", width=120)
        self.bal_tree.pack(fill="both", expand=True, padx=10, pady=5)

        ctk.CTkButton(
            left, text="⇄  Transfer Funds",
            command=self._open_transfer_dialog,
            fg_color=COLORS["primary"], hover_color="#1a6fa8",
            font=("Roboto", 13, "bold"), height=34,
        ).pack(pady=(4, 12))
        right = ctk.CTkFrame(self.frame, corner_radius=12)
        right.grid(row=1, column=1, sticky="nsew", padx=(8, 15), pady=8)

        ctk.CTkLabel(right, text="Income Log", font=("Roboto", 16, "bold")).pack(pady=(15, 5))

        form = ctk.CTkFrame(right, fg_color="transparent")
        form.pack(fill="x", padx=10)
        self.ent_inc_date   = ctk.CTkEntry(form, width=110, placeholder_text="YYYY-MM-DD")
        self.ent_inc_date.insert(0, datetime.now().strftime(DATE_FORMAT))
        self.ent_inc_source = ctk.CTkEntry(form, width=120, placeholder_text="Source / Wallet")
        self.ent_inc_amount = ctk.CTkEntry(form, width=100, placeholder_text="Amount")
        for w in (self.ent_inc_date, self.ent_inc_source, self.ent_inc_amount):
            w.pack(side="left", padx=3)
        ctk.CTkButton(form, text="Add", command=self._add_income, width=60).pack(side="left", padx=3)

        self.inc_tree = ttk.Treeview(right, columns=("ID","Date","Source","Amount"),
                                     show="headings", height=12)
        for col, w in zip(("ID","Date","Source","Amount"), (40,100,150,100)):
            self.inc_tree.heading(col, text=col)
            self.inc_tree.column(col, width=w)
        self.inc_tree.pack(fill="both", expand=True, padx=10, pady=5)
        self.inc_tree.bind("<<TreeviewSelect>>", self._on_income_select)

        btn_row = ctk.CTkFrame(right, fg_color="transparent")
        btn_row.pack(pady=(0, 10))
        ctk.CTkButton(btn_row, text="Update Selected", command=self._update_income, width=130).pack(side="left", padx=5)
        ctk.CTkButton(btn_row, text="Delete Selected", command=self._delete_income,
                      fg_color=COLORS["danger"], width=130).pack(side="left", padx=5)

    def _card(self, parent, title, color, col):
        card = ctk.CTkFrame(parent, corner_radius=12, fg_color="#1e1e1e")
        card.grid(row=0, column=col, sticky="ew", padx=6, pady=4)
        ctk.CTkLabel(card, text=title, font=("Roboto", 12), text_color="silver").pack(pady=(10,2))
        lbl = ctk.CTkLabel(card, text="₱0.00", font=("Roboto", 22, "bold"), text_color=color)
        lbl.pack(pady=(0,10))
        return lbl

    def reload(self, **_):
        mode = self.filter_mode.get()
        totals = get_summary_totals(self.user_id, mode)
        self.lbl_in.configure(text=f"₱{totals['total_in']:,.2f}")
        self.lbl_out.configure(text=f"₱{totals['total_out']:,.2f}")
        net = totals["net"]
        self.lbl_net.configure(text=f"₱{net:,.2f}",
                               text_color=COLORS["success"] if net >= 0 else COLORS["danger"])

        fixed = get_total_fixed_bills(self.user_id)
        self.lbl_bills.configure(text=f"₱{fixed:,.2f}")
        disposable = net - fixed
        self.lbl_disp.configure(
            text=f"₱{disposable:,.2f}",
            text_color=COLORS["success"] if disposable >= 0 else COLORS["danger"],
        )

        budget = get_latest_budget(self.user_id)
        total_out = totals["total_out"]
        if budget:
            pct = min(total_out / budget, 1.0) if budget > 0 else 0
            self.lbl_budget.configure(text=f"₱{total_out:,.2f} / ₱{budget:,.2f} ({int(pct*100)}%)")
            self.progress_budget.set(pct)
            color = COLORS["danger"] if pct > 0.9 else (COLORS["warning"] if pct > 0.7 else COLORS["success"])
            self.progress_budget.configure(progress_color=color)
        else:
            self.lbl_budget.configure(text="No budget set. Go to Settings.")
            self.progress_budget.set(0)

        for item in self.bal_tree.get_children():
            self.bal_tree.delete(item)
        for row in get_wallet_balances(self.user_id, mode):
            self.bal_tree.insert("", "end", values=(row["wallet"], f"₱{row['balance']:,.2f}"))

        for item in self.inc_tree.get_children():
            self.inc_tree.delete(item)
        df = get_income_df(self.user_id, mode)
        if not df.empty:
            # Hide internal transfer rows from the income log
            if "IsTransfer" in df.columns:
                df = df[df["IsTransfer"] == 0]
            for _, r in df.iterrows():
                self.inc_tree.insert("", "end", values=(
                    r["ID"], r["Date"].strftime("%Y-%m-%d"), r["Source"], f"₱{r['Amount']:,.2f}"))

    def _add_income(self):
        try:
            amount = float(self.ent_inc_amount.get())
        except ValueError:
            messagebox.showerror("Error", "Amount must be a number.")
            return
        if add_income(self.user_id, self.ent_inc_date.get(), self.ent_inc_source.get(), amount):
            self.ent_inc_source.delete(0, "end")
            self.ent_inc_amount.delete(0, "end")
            bus.publish("income.saved")
        else:
            messagebox.showerror("Error", "Failed to add income.")

    def _on_income_select(self, _):
        sel = self.inc_tree.selection()
        if sel:
            v = self.inc_tree.item(sel[0])["values"]
            self.ent_inc_date.delete(0, "end"); self.ent_inc_date.insert(0, v[1])
            self.ent_inc_source.delete(0, "end"); self.ent_inc_source.insert(0, v[2])
            self.ent_inc_amount.delete(0, "end")
            self.ent_inc_amount.insert(0, str(v[3]).replace("₱","").replace(",",""))

    def _update_income(self):
        sel = self.inc_tree.selection()
        if not sel:
            messagebox.showwarning("Warning", "Select an entry to update.")
            return
        income_id = self.inc_tree.item(sel[0])["values"][0]
        
        # Check if this is a transfer entry (should not be editable)
        metadata = get_income_metadata(income_id)
        if metadata and metadata["is_transfer"]:
            messagebox.showwarning(
                "Cannot Edit",
                "Transfer entries are automatically managed.\n\n"
                "To adjust a transfer, delete it and create a new one."
            )
            return
        
        try:
            amount = float(self.ent_inc_amount.get())
        except ValueError:
            messagebox.showerror("Error", "Amount must be a number.")
            return
        if update_income(income_id, self.ent_inc_date.get(), self.ent_inc_source.get(), amount):
            self.ent_inc_source.delete(0, "end")
            self.ent_inc_amount.delete(0, "end")
            bus.publish("income.saved")
        else:
            messagebox.showerror("Error", "Update failed.")

    def _delete_income(self):
        sel = self.inc_tree.selection()
        if sel and messagebox.askyesno("Confirm", "Delete selected income entry?"):
            if delete_income(self.inc_tree.item(sel[0])["values"][0]):
                bus.publish("income.deleted")
            else:
                messagebox.showerror("Error", "Delete failed.")

    # ------------------------------------------------------------------
    # Fund Transfer Dialog
    # ------------------------------------------------------------------

    def _open_transfer_dialog(self):
        wallets = get_wallet_list(self.user_id)
        if len(wallets) < 2:
            messagebox.showwarning("Transfer", "You need at least 2 wallets to transfer funds.")
            return

        dialog = ctk.CTkToplevel(self.frame)
        dialog.title("Transfer Funds Between Wallets")
        dialog.geometry("420x420")
        dialog.resizable(False, False)
        dialog.grab_set()

        ctk.CTkLabel(dialog, text="Transfer Funds", font=("Roboto", 16, "bold")).pack(pady=(15, 4))
        ctk.CTkLabel(dialog, text="Move money from one wallet to another.",
                     font=("Roboto", 11), text_color="gray").pack(pady=(0, 12))

        # Get wallet balances for reference
        balances = {row["wallet"]: row["balance"] for row in get_wallet_balances(self.user_id, "This Month")}

        form = ctk.CTkFrame(dialog, fg_color="transparent")
        form.pack(fill="x", padx=20)
        form.columnconfigure(1, weight=1)

        # From wallet with balance display
        ctk.CTkLabel(form, text="From:", anchor="w", font=("Roboto", 11, "bold")).grid(row=0, column=0, sticky="w", pady=8)
        from_var = ctk.StringVar(value=wallets[0])
        from_menu = ctk.CTkOptionMenu(form, variable=from_var, values=wallets, width=200)
        from_menu.grid(row=0, column=1, sticky="ew", padx=(10, 0))
        
        lbl_from_balance = ctk.CTkLabel(form, text="", font=("Roboto", 10), text_color="gray")
        lbl_from_balance.grid(row=1, column=1, sticky="e", padx=(10, 0), pady=(0, 8))

        # To wallet with balance display
        ctk.CTkLabel(form, text="To:", anchor="w", font=("Roboto", 11, "bold")).grid(row=2, column=0, sticky="w", pady=8)
        to_var = ctk.StringVar(value=wallets[1] if len(wallets) > 1 else wallets[0])
        to_menu = ctk.CTkOptionMenu(form, variable=to_var, values=wallets, width=200)
        to_menu.grid(row=2, column=1, sticky="ew", padx=(10, 0))
        
        lbl_to_balance = ctk.CTkLabel(form, text="", font=("Roboto", 10), text_color="gray")
        lbl_to_balance.grid(row=3, column=1, sticky="e", padx=(10, 0), pady=(0, 12))

        # Amount
        ctk.CTkLabel(form, text="Amount:", anchor="w", font=("Roboto", 11, "bold")).grid(row=4, column=0, sticky="w", pady=8)
        ent_amount = ctk.CTkEntry(form, placeholder_text="0.00", width=200)
        ent_amount.grid(row=4, column=1, sticky="ew", padx=(10, 0))

        # Date
        ctk.CTkLabel(form, text="Date:", anchor="w", font=("Roboto", 11, "bold")).grid(row=5, column=0, sticky="w", pady=8)
        ent_date = ctk.CTkEntry(form, placeholder_text="YYYY-MM-DD", width=200)
        ent_date.insert(0, datetime.now().strftime(DATE_FORMAT))
        ent_date.grid(row=5, column=1, sticky="ew", padx=(10, 0))

        # Update balance labels when wallet selection changes
        def _update_balance_display(*_):
            from_bal = balances.get(from_var.get(), 0)
            to_bal = balances.get(to_var.get(), 0)
            lbl_from_balance.configure(text=f"Balance: ₱{from_bal:,.2f}")
            lbl_to_balance.configure(text=f"Balance: ₱{to_bal:,.2f}")

        from_var.trace("w", _update_balance_display)
        to_var.trace("w", _update_balance_display)
        _update_balance_display()  # Initial display

        def _do_transfer():
            from_w = from_var.get()
            to_w   = to_var.get()
            
            # Validation
            if from_w == to_w:
                messagebox.showerror("Error", "Source and destination wallets must be different.", parent=dialog)
                return
            
            try:
                amount = float(ent_amount.get())
                if amount <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Enter a valid positive amount.", parent=dialog)
                return
            
            # Check for insufficient balance
            from_balance = balances.get(from_w, 0)
            if from_balance < amount:
                if not messagebox.askyesno(
                    "Low Balance",
                    f"The '{from_w}' wallet only has ₱{from_balance:,.2f}.\n"
                    f"You're trying to transfer ₱{amount:,.2f}.\n\nContinue anyway?",
                    parent=dialog
                ):
                    return
            
            # Confirm transfer
            if not messagebox.askyesno(
                "Confirm Transfer",
                f"Transfer ₱{amount:,.2f}\nfrom {from_w} → {to_w}\n\nConfirm this transfer?",
                parent=dialog
            ):
                return

            if transfer_funds(self.user_id, ent_date.get(), from_w, to_w, amount):
                messagebox.showinfo(
                    "Success",
                    f"✓ Transferred ₱{amount:,.2f}\n{from_w} → {to_w}",
                    parent=dialog,
                )
                dialog.destroy()
                bus.publish("income.saved")
            else:
                messagebox.showerror("Error", "Transfer failed. Check logs.", parent=dialog)

        button_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        button_frame.pack(pady=(16, 10))
        
        ctk.CTkButton(
            button_frame, text="Confirm Transfer",
            command=_do_transfer,
            fg_color=COLORS["primary"], hover_color="#1a6fa8",
            height=36, width=130,
            font=("Roboto", 12, "bold"),
        ).pack(side="left", padx=6)
        
        ctk.CTkButton(
            button_frame, text="Cancel",
            command=dialog.destroy,
            fg_color="gray30", height=36, width=130
        ).pack(side="left", padx=6)
