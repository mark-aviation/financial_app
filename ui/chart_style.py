# ui/chart_style.py — Shared Matplotlib dark-theme styling
#
# Applied consistently across Analytics and Project Budgets charts.
# Import apply_dark_style() and call it on any (fig, axes) pair.

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

# ── Palette ────────────────────────────────────────────────────────────────
BG_FIGURE  = "#141414"   # deep figure background
BG_AXES    = "#1a1a1a"   # slightly lighter axes area
GRID_COLOR = "#262626"   # barely-visible grid
SPINE_COLOR = "#333333"  # subtle axis borders
TEXT_COLOR  = "#E5E7EB"  # near-white readable text
MUTED_COLOR = "#6B7280"  # de-emphasised labels

# Data colours
COLOR_COMMITTED = "#F59E0B"   # amber  — committed / expense
COLOR_REMAINING = "#10B981"   # emerald — remaining / income
COLOR_DANGER    = "#EF4444"   # red     — remaining < 20% warning
COLOR_INCOME    = "#10B981"
COLOR_EXPENSE   = "#EF4444"

# Pie palette — 6 distinct, finance-appropriate colours
PIE_COLORS = ["#3B82F6", "#F59E0B", "#10B981", "#8B5CF6", "#EC4899", "#06B6D4"]

AT_RISK_THRESHOLD = 0.20   # remaining < 20% of balance → red bar


def apply_dark_axes(ax):
    """Apply the shared dark style to a single Axes object."""
    ax.set_facecolor(BG_AXES)
    ax.tick_params(colors=TEXT_COLOR, labelsize=8)
    ax.xaxis.label.set_color(TEXT_COLOR)
    ax.yaxis.label.set_color(TEXT_COLOR)
    ax.title.set_color(TEXT_COLOR)

    # Hide all spines except bottom
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(SPINE_COLOR)

    # Subtle horizontal grid only
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=GRID_COLOR, linewidth=0.6, linestyle="--")
    ax.set_axisbelow(True)


def apply_dark_figure(fig):
    """Apply background to the figure itself."""
    fig.patch.set_facecolor(BG_FIGURE)


def bar_label(ax, bar, value: float, color: str, offset: float, fontsize: int = 8):
    """Draw a ₱ currency label just outside a horizontal bar."""
    if value > 0:
        ax.text(
            value + offset,
            bar.get_y() + bar.get_height() / 2,
            f"\u20b1{value:,.0f}",
            va="center",
            ha="left",
            color=color,
            fontsize=fontsize,
            fontweight="bold",
        )
