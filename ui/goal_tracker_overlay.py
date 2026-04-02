# ui/goal_tracker_overlay.py — Goal Tracker popup overlay

import logging
import threading
from datetime import date, timedelta

import customtkinter as ctk
from tkinter import messagebox

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from config import COLORS
from models.deadline import DeadlineItem
from models.goal import (
    Goal, get_goals, add_goal, delete_goal,
    toggle_completion, get_completions_for_week,
    get_daily_completions_for_week, get_weekly_history,
    week_start, week_days,
    export_goals_csv, export_goals_pdf,
)
from services.budget_service import get_project_budget_summary
from ui.chart_style import (
    apply_dark_axes, apply_dark_figure,
    BG_FIGURE, TEXT_COLOR, MUTED_COLOR, GRID_COLOR,
)

logger = logging.getLogger(__name__)

TEAL        = "#1abc9c"
TEAL_HOVER  = "#16a085"
DAY_NAMES   = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
PCT_GREEN   = 90
PCT_YELLOW  = 60


def _pct_color(pct: float) -> str:
    if pct >= PCT_GREEN:
        return COLORS["success"]
    if pct >= PCT_YELLOW:
        return COLORS["warning"]
    return COLORS["danger"]


class GoalTrackerOverlay(ctk.CTkToplevel):

    def __init__(self, parent, task: DeadlineItem, user_id: int):
        super().__init__(parent)
        self.task    = task
        self.user_id = user_id
        self.title(f"Goal Tracker — {task.project_name}")
        self.geometry("1200x780")
        self.resizable(True, True)
        self.configure(fg_color="#141414")
        self.grab_set()
        self.focus_force()

        self._week_start = week_start(date.today())
        self._goals: list[Goal] = []
        self._completions: dict = {}
        self._check_vars: dict  = {}
        self._chart_fig_donut = None
        self._chart_fig_line  = None

        self._build_ui()
        self._load_data()

    # ── UI Construction ───────────────────────────────────────────────────

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)
        self.grid_rowconfigure(1, weight=2)
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(3, weight=0)

        self._build_header()
        self._build_charts_row()
        self._build_grid_section()
        self._build_footer()

    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color="#1e1e1e", corner_radius=0)
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            hdr, text=self.task.project_name,
            font=("Segoe UI", 17, "bold"), text_color="white",
        ).grid(row=0, column=0, padx=16, pady=12, sticky="w")

        nav = ctk.CTkFrame(hdr, fg_color="transparent")
        nav.grid(row=0, column=1, pady=12)

        self.btn_prev = ctk.CTkButton(
            nav, text="← Prev", width=80, height=30,
            fg_color=TEAL, hover_color=TEAL_HOVER,
            font=("Segoe UI", 11), command=self._prev_week,
        )
        self.btn_prev.pack(side="left", padx=(0, 10))

        self.lbl_week = ctk.CTkLabel(
            nav, text="", font=("Segoe UI", 12, "bold"),
            text_color="white", width=240,
        )
        self.lbl_week.pack(side="left")

        self.btn_next = ctk.CTkButton(
            nav, text="Next →", width=80, height=30,
            fg_color=TEAL, hover_color=TEAL_HOVER,
            font=("Segoe UI", 11), command=self._next_week,
        )
        self.btn_next.pack(side="left", padx=(10, 0))

        exp = ctk.CTkFrame(hdr, fg_color="transparent")
        exp.grid(row=0, column=2, padx=16, pady=12)

        for label, cmd in [
            ("Export CSV", self._export_csv),
            ("Export PDF", self._export_pdf),
        ]:
            ctk.CTkButton(
                exp, text=label, width=100, height=30,
                fg_color="#2b2b2b", hover_color="#383838",
                border_width=1, border_color="#3d3d3d",
                font=("Segoe UI", 11), text_color="silver",
                command=cmd,
            ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            exp, text="✕ Close", width=70, height=30,
            fg_color=COLORS["danger"], hover_color="#c0392b",
            font=("Segoe UI", 11), command=self.destroy,
        ).pack(side="left")

        self._update_week_label()

    def _build_charts_row(self):
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=12, pady=(6, 0))
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=2)

        donut_frame = ctk.CTkFrame(row, fg_color="#1e1e1e", corner_radius=10)
        donut_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        ctk.CTkLabel(
            donut_frame, text="This Week",
            font=("Segoe UI", 11), text_color="silver",
        ).pack(anchor="w", padx=14, pady=(4, 2))

        stats_inner = ctk.CTkFrame(donut_frame, fg_color="transparent")
        stats_inner.pack(fill="x", padx=14, pady=(0, 6))

        self.lbl_pct_done    = self._stat_label(stats_inner, "completed", COLORS["success"])
        self.lbl_pct_missing = self._stat_label(stats_inner, "missing",   "#888888")

        self.donut_container = ctk.CTkFrame(donut_frame, fg_color="transparent")
        self.donut_container.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        line_frame = ctk.CTkFrame(row, fg_color="#1e1e1e", corner_radius=10)
        line_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        ctk.CTkLabel(
            line_frame, text="Weekly Progress",
            font=("Segoe UI", 11), text_color="silver",
        ).pack(anchor="w", padx=14, pady=(10, 0))

        self.line_container = ctk.CTkFrame(line_frame, fg_color="transparent")
        self.line_container.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    def _stat_label(self, parent, title: str, color: str):
        col = ctk.CTkFrame(parent, fg_color="transparent")
        col.pack(side="left", padx=(0, 20), pady=4)
        ctk.CTkLabel(col, text=title.upper(), font=("Segoe UI", 9),
                     text_color="silver").pack(anchor="w")
        lbl = ctk.CTkLabel(col, text="—", font=("Segoe UI", 20, "bold"),
                           text_color=color)
        lbl.pack(anchor="w")
        return lbl

    def _build_grid_section(self):
        wrapper = ctk.CTkFrame(self, fg_color="#1e1e1e", corner_radius=10)
        wrapper.grid(row=2, column=0, sticky="nsew", padx=12, pady=(4, 4))
        wrapper.grid_columnconfigure(0, weight=1)
        wrapper.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            wrapper, text="Weekly Goals Grid",
            font=("Segoe UI", 11, "bold"), text_color="white",
        ).grid(row=0, column=0, sticky="w", padx=12, pady=(5, 2))

        self.grid_scroll = ctk.CTkScrollableFrame(
            wrapper, fg_color="transparent", corner_radius=0,
        )
        self.grid_scroll.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

    def _build_footer(self):
        foot = ctk.CTkFrame(self, fg_color="transparent")
        foot.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 8))
        foot.grid_columnconfigure(0, weight=3)
        foot.grid_columnconfigure(1, weight=1)
        foot.grid_rowconfigure(0, weight=1)
        foot.grid_propagate(False)
        foot.configure(height=170)

        self._build_goals_list(foot)
        self._build_budget_summary(foot)

    def _build_goals_list(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="#1e1e1e", corner_radius=10)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        frame.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            frame, text="Goals",
            font=("Segoe UI", 11, "bold"), text_color="white",
        ).pack(anchor="w", padx=10, pady=(6, 2))

        add_row = ctk.CTkFrame(frame, fg_color="transparent")
        add_row.pack(fill="x", padx=10, pady=(0, 4))

        self.ent_goal = ctk.CTkEntry(
            add_row, placeholder_text="Type a goal and press Enter…",
            height=32, font=("Segoe UI", 12),
        )
        self.ent_goal.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.ent_goal.bind("<Return>", lambda e: self._add_goal())

        ctk.CTkButton(
            add_row, text="+ Add", width=70, height=32,
            fg_color=TEAL, hover_color=TEAL_HOVER,
            font=("Segoe UI", 11), command=self._add_goal,
        ).pack(side="right")

        self.goals_list_frame = ctk.CTkScrollableFrame(
            frame, fg_color="transparent",
        )
        self.goals_list_frame.pack(fill="both", expand=True, padx=8, pady=(0, 6))

        self.lbl_no_goals = ctk.CTkLabel(
            self.goals_list_frame,
            text="No goals yet — type above and press Enter to add your first goal",
            font=("Segoe UI", 11), text_color="silver",
        )

    def _build_budget_summary(self, parent):
        frame = ctk.CTkFrame(parent, fg_color="#1e1e1e", corner_radius=10)
        frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        ctk.CTkLabel(
            frame, text="Budget",
            font=("Segoe UI", 11, "bold"), text_color="white",
        ).pack(anchor="w", padx=10, pady=(6, 3))

        self.budget_inner = ctk.CTkFrame(frame, fg_color="transparent")
        self.budget_inner.pack(fill="both", expand=True, padx=10, pady=(0, 6))

    # ── Data Loading ──────────────────────────────────────────────────────

    def _load_data(self):
        threading.Thread(target=self._fetch_and_render, daemon=True).start()

    def _fetch_and_render(self):
        try:
            goals       = get_goals(self.task.id, self.user_id)
            completions = get_completions_for_week(
                self.task.id, self.user_id, self._week_start,
            )
            daily       = get_daily_completions_for_week(
                self.task.id, self.user_id, self._week_start,
            )
            history     = get_weekly_history(self.task.id, self.user_id, weeks=8)
            budget_data = get_project_budget_summary(self.user_id)

            self.after(0, lambda: self._render_all(
                goals, completions, daily, history, budget_data,
            ))
        except Exception as e:
            logger.error("GoalTracker _fetch_and_render failed: %s", e)
            import traceback; traceback.print_exc()

    def _render_all(self, goals, completions, daily, history, budget_data):
        self._goals       = goals
        self._completions = completions
        self._render_goals_list()
        self._render_grid(daily)
        self._render_donut(daily)
        self._render_line_chart(history, daily)
        self._render_budget(budget_data)

    # ── Goals List ────────────────────────────────────────────────────────

    def _render_goals_list(self):
        for w in self.goals_list_frame.winfo_children():
            w.destroy()

        if not self._goals:
            self.lbl_no_goals.pack(pady=6)
            return

        for goal in self._goals:
            row = ctk.CTkFrame(self.goals_list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            ctk.CTkLabel(
                row, text=f"• {goal.goal_name}",
                font=("Segoe UI", 12), text_color="white", anchor="w",
            ).pack(side="left", fill="x", expand=True)

            ctk.CTkButton(
                row, text="✕", width=26, height=22,
                fg_color=COLORS["danger"], hover_color="#c0392b",
                font=("Segoe UI", 10),
                command=lambda gid=goal.id: self._delete_goal(gid),
            ).pack(side="right", padx=(4, 0))

    def _add_goal(self):
        name = self.ent_goal.get().strip()
        if not name:
            return
        new_goal = add_goal(self.task.id, self.user_id, name)
        if new_goal:
            self.ent_goal.delete(0, "end")
            self._goals.append(new_goal)
            self._render_goals_list()
            self._reload_grid_and_charts()
        else:
            messagebox.showerror("Error", "Failed to save goal.", parent=self)

    def _delete_goal(self, goal_id: int):
        if not messagebox.askyesno("Confirm", "Delete this goal and all its history?",
                                   parent=self):
            return
        if delete_goal(goal_id, self.user_id):
            self._goals = [g for g in self._goals if g.id != goal_id]
            self._render_goals_list()
            self._reload_grid_and_charts()
        else:
            messagebox.showerror("Error", "Failed to delete goal.", parent=self)

    # ── Weekly Grid ───────────────────────────────────────────────────────

    def _render_grid(self, daily: list[dict]):
        try:
            self._render_grid_inner(daily)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"[GRID ERROR] {e}")

    def _render_grid_inner(self, daily: list[dict]):
        # ── ADJUST THESE TO RESIZE ───────────────────────────────────
        GOAL_COL_WIDTH = 200   # goal name column width
        DAY_COL_WIDTH  = 80    # each day column width
        ROW_HEIGHT     = 40    # goal rows + summary cells height
        # ─────────────────────────────────────────────────────────────

        for w in self.grid_scroll.winfo_children():
            w.destroy()
        self._check_vars.clear()

        days = week_days(self._week_start)
        today = date.today()

        if not self._goals:
            ctk.CTkLabel(
                self.grid_scroll,
                text="No goals yet — add your first goal below",
                font=("Segoe UI", 12), text_color="silver",
            ).pack(pady=20)
            return

        # Use grid on grid_scroll so all rows share the same columns
        self.grid_scroll.grid_columnconfigure(0, minsize=GOAL_COL_WIDTH)
        for c in range(1, 8):
            self.grid_scroll.grid_columnconfigure(c, minsize=DAY_COL_WIDTH, weight=0)

        current_row = 0

        # ── Header row ────────────────────────────────────────────────
        ctk.CTkLabel(
            self.grid_scroll, text="Goal",
            font=("Segoe UI", 11, "bold"),
            text_color="silver", anchor="w",
        ).grid(row=current_row, column=0, padx=(4, 0), pady=(0, 4), sticky="w")

        for i, d in enumerate(days):
            is_today = (d == today)
            ctk.CTkLabel(
                self.grid_scroll,
                text=f"{DAY_NAMES[i]}\n{d.month}/{d.day}",
                width=DAY_COL_WIDTH,
                height=ROW_HEIGHT,
                font=("Segoe UI", 10, "bold"),
                text_color="white",
                fg_color=TEAL if is_today else "transparent",
                corner_radius=6,
                justify="center",
            ).grid(row=current_row, column=i + 1, padx=2, pady=(0, 4))

        current_row += 1

        # ── Goal rows ─────────────────────────────────────────────────
        for goal in self._goals:
            ctk.CTkLabel(
                self.grid_scroll,
                text=goal.goal_name,
                font=("Segoe UI", 11), text_color="white",
                anchor="w", wraplength=190,
                fg_color="#242424", corner_radius=6,
                width=GOAL_COL_WIDTH, height=ROW_HEIGHT,
            ).grid(row=current_row, column=0, padx=(4, 2), pady=2, sticky="ew")

            for i, d in enumerate(days):
                key = (goal.id, d)
                var = ctk.BooleanVar(value=self._completions.get(key, False))
                self._check_vars[key] = var

                cell = ctk.CTkFrame(
                    self.grid_scroll,
                    fg_color="#242424", corner_radius=6,
                    width=DAY_COL_WIDTH, height=ROW_HEIGHT,
                )
                cell.grid(row=current_row, column=i + 1, padx=2, pady=2)
                cell.grid_propagate(False)
                cell.grid_rowconfigure(0, weight=1)
                cell.grid_columnconfigure(0, weight=1)

                cb = ctk.CTkCheckBox(
                    cell, text="", variable=var,
                    checkbox_width=22, checkbox_height=22,
                    checkmark_color="white",
                    fg_color=TEAL, hover_color=TEAL_HOVER,
                    border_color="#555555",
                    command=lambda g=goal.id, dt=d, v=var: self._on_toggle(g, dt, v),
                )
                cb.grid(row=0, column=0)

            current_row += 1

        # ── Separator ─────────────────────────────────────────────────
        sep = ctk.CTkFrame(self.grid_scroll, fg_color="#3d3d3d", height=1)
        sep.grid(row=current_row, column=0, columnspan=8,
                 sticky="ew", padx=4, pady=(6, 4))
        current_row += 1

        # ── Summary row ───────────────────────────────────────────────
        ctk.CTkLabel(
            self.grid_scroll, text="Summary",
            font=("Segoe UI", 10, "bold"), text_color="silver",
            anchor="w",
        ).grid(row=current_row, column=0, padx=(4, 0), sticky="w")

        self._summary_labels = []
        for i, day_data in enumerate(daily):
            pct  = day_data["pct"]
            done = day_data["completed"]
            tot  = day_data["total_goals"]
            bg   = _pct_color(pct) if tot > 0 else "#2b2b2b"

            cell = ctk.CTkFrame(
                self.grid_scroll, fg_color=bg, corner_radius=6,
                width=DAY_COL_WIDTH, height=ROW_HEIGHT,
            )
            cell.grid(row=current_row, column=i + 1, padx=2, pady=2)
            cell.grid_propagate(False)
            cell.grid_rowconfigure(0, weight=1)
            cell.grid_columnconfigure(0, weight=1)

            ctk.CTkLabel(
                cell,
                text=f"{done}/{tot}\n{pct:.0f}%",
                font=("Segoe UI", 9, "bold"),
                text_color="white",
                justify="center",
            ).grid(row=0, column=0)

    def _on_toggle(self, goal_id: int, d: date, var: ctk.BooleanVar):
        is_done = var.get()
        self._completions[(goal_id, d)] = is_done
        toggle_completion(goal_id, self.user_id, d, is_done)
        self._reload_grid_and_charts()

    # ── Charts ────────────────────────────────────────────────────────────

    def _render_donut(self, daily: list[dict]):
        try:
            self._render_donut_inner(daily)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"[DONUT ERROR] {e}")

    def _render_donut_inner(self, daily: list[dict]):
        for w in self.donut_container.winfo_children():
            w.destroy()
        if self._chart_fig_donut:
            plt.close(self._chart_fig_donut)

        total = sum(d["total_goals"] for d in daily)
        done  = sum(d["completed"]   for d in daily)
        miss  = total - done
        pct_done    = (done / total * 100) if total > 0 else 0
        pct_missing = 100 - pct_done

        self.lbl_pct_done.configure(text=f"{pct_done:.0f}%")
        self.lbl_pct_missing.configure(text=f"{pct_missing:.0f}%")

        fig, ax = plt.subplots(figsize=(2.8, 1.6), dpi=80)
        apply_dark_figure(fig)
        ax.set_facecolor(BG_FIGURE)

        vals  = [done, miss] if total > 0 else [0, 1]
        clrs  = [TEAL, "#3d3d3d"]
        ax.pie(vals, colors=clrs, startangle=90,
               wedgeprops={"width": 0.45, "linewidth": 0})
        ax.set_aspect("equal")
        for spine in ax.spines.values():
            spine.set_visible(False)
        fig.tight_layout(pad=0.2)

        canvas = FigureCanvasTkAgg(fig, master=self.donut_container)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._chart_fig_donut = fig

    def _render_line_chart(self, history: list[dict], daily: list[dict]):
        try:
            self._render_line_chart_inner(history, daily)
        except Exception as e:
            import traceback; traceback.print_exc()
            print(f"[LINE CHART ERROR] {e}")

    def _render_line_chart_inner(self, history: list[dict], daily: list[dict]):
        for w in self.line_container.winfo_children():
            w.destroy()
        if self._chart_fig_line:
            plt.close(self._chart_fig_line)

        fig, ax = plt.subplots(figsize=(6.0, 1.6), dpi=80)
        apply_dark_figure(fig)
        apply_dark_axes(ax)

        today = date.today()
        days  = week_days(self._week_start)

        past_x, past_y = [], []
        future_x = []

        for i, (d, day_data) in enumerate(zip(days, daily)):
            if d <= today:
                past_x.append(DAY_NAMES[i])
                past_y.append(day_data["pct"])
            else:
                future_x.append(DAY_NAMES[i])

        if past_x:
            ax.plot(past_x, past_y, color=COLORS["success"], linewidth=2,
                    marker="o", markersize=4, zorder=3)

        if past_x and future_x:
            join_x = [past_x[-1]] + future_x
            join_y = [past_y[-1]] + [past_y[-1]] * len(future_x)
            ax.plot(join_x, join_y, color=COLORS["success"], linewidth=1.5,
                    linestyle="--", alpha=0.45, zorder=2)

        ax.set_ylim(0, 105)
        ax.set_ylabel("%", color=MUTED_COLOR, fontsize=8)
        ax.tick_params(axis="x", labelsize=8, colors=MUTED_COLOR)
        ax.tick_params(axis="y", labelsize=7, colors=MUTED_COLOR)
        ax.yaxis.grid(True, color=GRID_COLOR, linewidth=0.5, linestyle="--")
        ax.set_axisbelow(True)
        fig.tight_layout(pad=0.4)

        canvas = FigureCanvasTkAgg(fig, master=self.line_container)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._chart_fig_line = fig

    # ── Budget Summary ────────────────────────────────────────────────────

    def _render_budget(self, budget_data):
        for w in self.budget_inner.winfo_children():
            w.destroy()

        rows = [r for r in budget_data.allocation_rows
                if r.project_name == self.task.project_name]

        if not rows:
            ctk.CTkLabel(
                self.budget_inner,
                text="No budget allocated.",
                font=("Segoe UI", 11), text_color="silver",
            ).pack(anchor="w")
            return

        STATUS_ICONS  = {"funded": "✅ Funded", "at_risk": "⚠️ At Risk",
                         "unfunded": "❌ Unfunded"}
        STATUS_COLORS = {"funded": COLORS["success"], "at_risk": COLORS["warning"],
                         "unfunded": COLORS["danger"]}

        def row_lbl(label, value, color="silver"):
            r = ctk.CTkFrame(self.budget_inner, fg_color="transparent")
            r.pack(fill="x", pady=1)
            ctk.CTkLabel(r, text=label, font=("Segoe UI", 10),
                         text_color="#666666", width=120, anchor="w").pack(side="left")
            ctk.CTkLabel(r, text=value, font=("Segoe UI", 11, "bold"),
                         text_color=color, anchor="w").pack(side="left")

        ar = rows[0]
        if self.task.estimated_cost:
            row_lbl("Estimated Cost",
                    f"₱{self.task.estimated_cost:,.2f}", COLORS["primary"])

        total_alloc = sum(r.allocated_cost for r in rows)
        row_lbl("Total Allocated", f"₱{total_alloc:,.2f}", "white")

        if self.task.priority_level:
            row_lbl("Priority", self.task.priority_level, COLORS["warning"])

        row_lbl("Status",
                STATUS_ICONS.get(ar.budget_status, "—"),
                STATUS_COLORS.get(ar.budget_status, "silver"))

        for r in rows:
            row_lbl(f"  {r.wallet_name}", f"₱{r.allocated_cost:,.2f}",
                    COLORS["primary"])

    # ── Week navigation ───────────────────────────────────────────────────

    def _prev_week(self):
        self._week_start -= timedelta(weeks=1)
        self._update_week_label()
        self._reload_grid_and_charts()

    def _next_week(self):
        current_monday = week_start(date.today())
        if self._week_start >= current_monday:
            return
        self._week_start += timedelta(weeks=1)
        self._update_week_label()
        self._reload_grid_and_charts()

    def _update_week_label(self):
        end = self._week_start + timedelta(days=6)
        self.lbl_week.configure(
            text=f"Week of {self._week_start.strftime('%b %d')} – "
                 f"{end.strftime('%b %d, %Y')}"
        )
        current_monday = week_start(date.today())
        if hasattr(self, "btn_next"):
            if self._week_start >= current_monday:
                self.btn_next.configure(fg_color="#2b2b2b", text_color="gray",
                                        state="disabled")
            else:
                self.btn_next.configure(fg_color=TEAL, text_color="white",
                                        state="normal")

    def _reload_grid_and_charts(self):
        threading.Thread(target=self._reload_worker, daemon=True).start()

    def _reload_worker(self):
        try:
            completions = get_completions_for_week(
                self.task.id, self.user_id, self._week_start,
            )
            daily   = get_daily_completions_for_week(
                self.task.id, self.user_id, self._week_start,
            )
            history = get_weekly_history(self.task.id, self.user_id, weeks=8)
            self.after(0, lambda: self._apply_reload(completions, daily, history))
        except Exception as e:
            logger.error("_reload_worker failed: %s", e)

    def _apply_reload(self, completions, daily, history):
        self._completions = completions
        self._render_grid(daily)
        self._render_donut(daily)
        self._render_line_chart(history, daily)

    # ── Export ────────────────────────────────────────────────────────────

    def _export_csv(self):
        try:
            path = export_goals_csv(self.task.id, self.user_id,
                                    self.task.project_name)
            messagebox.showinfo("Exported", f"CSV saved to:\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("Export Failed", str(e), parent=self)

    def _export_pdf(self):
        try:
            path = export_goals_pdf(self.task.id, self.user_id,
                                    self.task.project_name)
            messagebox.showinfo("Exported", f"PDF saved to:\n{path}", parent=self)
        except Exception as e:
            messagebox.showerror("Export Failed", str(e), parent=self)
