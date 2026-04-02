# ui/tabs/analytics_tab.py
# v5: Cash flow diverging bar replaced with clustered expense-by-category chart.
#     Pie chart untouched. Both charts respect TimeFilter and filter_mode.

import logging
import threading
import customtkinter as ctk

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from config import COLORS
from services.analytics_service import (
    get_pie_data, get_pie_data_filtered,
    get_expense_by_category_over_time,
)
from services.event_bus import bus
from services.time_filter import TimeFilter, get_period_label
from ui.chart_style import (
    apply_dark_axes, apply_dark_figure,
    BG_FIGURE, PIE_COLORS, TEXT_COLOR, MUTED_COLOR, GRID_COLOR,
)

logger = logging.getLogger(__name__)


class AnalyticsTab:
    def __init__(self, parent, user_id, username, filter_mode, time_filter=None, **kwargs):
        self.parent      = parent
        self.user_id     = user_id
        self.filter_mode = filter_mode
        self.time_filter: TimeFilter = time_filter if time_filter is not None else TimeFilter()
        self.period_var  = ctk.StringVar(value="Month")
        self.frame       = ctk.CTkFrame(parent, fg_color="transparent")
        self.frame.pack(fill="both", expand=True)
        self._build_ui()
        bus.subscribe("expense.saved",       self.reload)
        bus.subscribe("expense.deleted",     self.reload)
        bus.subscribe("income.saved",        self.reload)
        bus.subscribe("income.deleted",      self.reload)
        bus.subscribe("filter.changed",      self.reload)
        bus.subscribe("time_filter.changed", self.reload)

    def pack(self, **kwargs):
        pass

    def _build_ui(self):
        ctrl = ctk.CTkFrame(self.frame, fg_color="transparent")
        ctrl.pack(fill="x", padx=15, pady=(10, 0))
        ctk.CTkLabel(ctrl, text="Period:", text_color=MUTED_COLOR,
                     font=("Roboto", 12)).pack(side="left", padx=(0, 8))
        ctk.CTkSegmentedButton(
            ctrl, values=["Week", "Month", "Year"],
            variable=self.period_var,
            command=lambda _: self.reload(),
        ).pack(side="left")

        self.lbl_loading = ctk.CTkLabel(
            self.frame, text="", font=("Roboto", 11),
            text_color=COLORS["warning"],
        )
        self.lbl_loading.pack()

        self.fig, (self.ax_pie, self.ax_bar) = plt.subplots(
            1, 2, figsize=(13, 5.2), facecolor=BG_FIGURE,
        )
        apply_dark_figure(self.fig)
        apply_dark_axes(self.ax_pie)
        apply_dark_axes(self.ax_bar)
        self.fig.subplots_adjust(
            left=0.06, right=0.97, top=0.88, bottom=0.18, wspace=0.3,
        )

        self.canvas = FigureCanvasTkAgg(self.fig, master=self.frame)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=10, pady=10)

    def reload(self, **_):
        self.lbl_loading.configure(text="⟳ Updating charts...")
        threading.Thread(target=self._fetch_and_draw, daemon=True).start()

    def _fetch_and_draw(self):
        timeframe = self.period_var.get()
        if self.time_filter.is_active():
            pie_data = get_pie_data_filtered(self.user_id, self.time_filter)
            bar_data = get_expense_by_category_over_time(
                self.user_id, self.filter_mode.get(), timeframe, self.time_filter,
            )
        else:
            mode     = self.filter_mode.get()
            pie_data = get_pie_data(self.user_id, mode)
            bar_data = get_expense_by_category_over_time(
                self.user_id, mode, timeframe, None,
            )
        self.frame.after(0, lambda: self._draw(pie_data, bar_data))

    def _draw(self, pie_data, bar_data):
        self.ax_pie.clear()
        self.ax_bar.clear()

        _period        = get_period_label(self.time_filter) if self.time_filter.is_active() else ""
        _period_suffix = f" — {_period}" if _period else ""

        # ── Pie chart (untouched) ─────────────────────────────────────
        if not pie_data.is_empty:
            wedges, texts, autotexts = self.ax_pie.pie(
                pie_data.values,
                labels=pie_data.labels,
                autopct="%1.1f%%",
                colors=PIE_COLORS[:len(pie_data.values)],
                startangle=90,
                pctdistance=0.78,
                wedgeprops={"linewidth": 1.5, "edgecolor": BG_FIGURE},
            )
            for t in texts:
                t.set_color(TEXT_COLOR)
                t.set_fontsize(8.5)
            for at in autotexts:
                at.set_color("#ffffff")
                at.set_fontsize(7.5)
                at.set_fontweight("bold")
        else:
            self.ax_pie.text(
                0.5, 0.5, "No expense data",
                ha="center", va="center",
                color=MUTED_COLOR, fontsize=11,
                transform=self.ax_pie.transAxes,
            )

        self.ax_pie.set_facecolor(BG_FIGURE)
        for spine in self.ax_pie.spines.values():
            spine.set_visible(False)
        self.ax_pie.set_title(
            f"Spending Breakdown{_period_suffix}",
            color=TEXT_COLOR, fontsize=11, fontweight="bold", pad=12,
        )

        # ── Clustered bar chart ───────────────────────────────────────
        apply_dark_axes(self.ax_bar)

        if not bar_data.is_empty:
            import numpy as np

            periods    = bar_data.periods
            categories = bar_data.categories
            n_periods  = len(periods)
            n_cats     = len(categories)

            x         = np.arange(n_periods)
            bar_width = max(0.08, min(0.6 / max(n_cats, 1), 0.25))
            offsets   = (np.arange(n_cats) - (n_cats - 1) / 2) * bar_width

            for i, cat in enumerate(categories):
                color  = PIE_COLORS[i % len(PIE_COLORS)]
                values = bar_data.data[cat]
                bars   = self.ax_bar.bar(
                    x + offsets[i], values,
                    width=bar_width,
                    color=color,
                    label=cat,
                    zorder=3,
                )
                # Amount labels on top — only if bars are wide enough
                if bar_width >= 0.15 and n_periods <= 15:
                    for bar, val in zip(bars, values):
                        if val > 0:
                            self.ax_bar.text(
                                bar.get_x() + bar.get_width() / 2,
                                bar.get_height() + (max(
                                    max(bar_data.data[c]) for c in categories
                                ) * 0.015),
                                f"₱{val:,.0f}",
                                ha="center", va="bottom",
                                color=TEXT_COLOR, fontsize=6, fontweight="bold",
                            )

            self.ax_bar.set_xticks(x)
            self.ax_bar.set_xticklabels(
                periods, rotation=45, ha="right",
                color=MUTED_COLOR, fontsize=7.5,
            )
            self.ax_bar.tick_params(axis="y", colors=MUTED_COLOR, labelsize=8)
            self.ax_bar.yaxis.grid(
                True, color=GRID_COLOR, linewidth=0.5, linestyle="--",
            )
            self.ax_bar.set_axisbelow(True)

            # Legend
            self.ax_bar.legend(
                loc="upper right",
                facecolor="#1e1e1e",
                edgecolor="#333",
                labelcolor=TEXT_COLOR,
                fontsize=7.5,
                framealpha=0.9,
            )
        else:
            self.ax_bar.text(
                0.5, 0.5, "No expense data for this period",
                ha="center", va="center",
                color=MUTED_COLOR, fontsize=11,
                transform=self.ax_bar.transAxes,
            )

        self.ax_bar.set_title(
            f"Expenses by Category — {self.period_var.get()}{_period_suffix}",
            color=TEXT_COLOR, fontsize=11, fontweight="bold", pad=12,
        )
        self.ax_bar.set_ylabel("Amount (₱)", color=MUTED_COLOR, fontsize=8.5)
        self.ax_bar.set_facecolor("#1a1a1a")

        self.fig.canvas.draw_idle()
        self.lbl_loading.configure(text="")
