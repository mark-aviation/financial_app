# config.py — App-wide constants and defaults
# 🏛️ Architect: Single source of truth for all configuration.
# No magic strings scattered across the codebase.

import os

# --- App Info ---
APP_NAME = "Expensis Pro"
APP_VERSION = "2.0.0"
APP_GEOMETRY = "1400x900"

# --- Database ---
DB_CONFIG_FILE = "db_config.json"
DB_POOL_NAME = "expensis_pool"
DB_POOL_SIZE = 5
DB_CONNECTION_TIMEOUT = 5

DB_DEFAULTS = {
    "host": "your_database_host",
    "port": 3306,
    "user": "your_database_user",
    "password": "your_database_password",
    "database": "expensis",
}

# Whitelist of tables allowed in dynamic queries (prevents SQL injection)
ALLOWED_TABLES = {"expenses", "income"}

# --- Expense Categories ---
DEFAULT_CATEGORIES = [
    "Food",
    "Transport",
    "Leisure",
    "Personal & Self-Care",
    "Connectivity & Utilities",
    "Shopping",
]

# --- Date Formats ---
DATE_FORMAT = "%Y-%m-%d"
DISPLAY_DATE_FORMAT = "%Y-%m-%d"

# --- Budget Alert Thresholds ---
BUDGET_WARNING_THRESHOLD = 0.70   # Yellow at 70%
BUDGET_DANGER_THRESHOLD = 0.90    # Red at 90%

# --- Project Budget Thresholds ---
# If committing this project leaves less than 20% of wallet balance free → at_risk
PROJECT_AT_RISK_THRESHOLD = 0.20
# Warn user if new project would more than double current total committed budget
PROJECT_DOUBLE_WARN_THRESHOLD = 2.0

# --- Priority Levels ---
PRIORITY_LEVELS = ["High", "Medium", "Low"]

# --- Deadline Urgency Thresholds (days) ---
DEADLINE_HIGH_DAYS = 7    # < 7 days → red
DEADLINE_MED_DAYS = 14    # ≤ 14 days → yellow

# --- Theme Colors ---
COLORS = {
    "primary":   "#3B8ED0",
    "success":   "#2ecc71",
    "warning":   "#f1c40f",
    "danger":    "#e74c3c",
    "dark_bg":   "#2b2b2b",
    "muted":     "#34495e",
    "income":    "#2ecc71",
    "expense":   "#e74c3c",
}

# --- Logging ---
LOG_LEVEL = os.environ.get("EXPENSIS_LOG_LEVEL", "WARNING")
