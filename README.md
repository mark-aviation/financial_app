# Expensis Pro v2.0

Personal finance tracker — Python · CustomTkinter · MySQL · Pandas · Matplotlib

## What changed in v2.0

The entire app was refactored from a single 724-line God Class into a clean layered architecture.

### Structure

```
expensis/
├── main.py                        # Entry point (15 lines)
├── config.py                      # All constants and defaults
├── requirements.txt
├── db/
│   └── connection.py              # Connection pool (replaces per-request connections)
├── models/                        # Pure DB CRUD — no UI code
│   ├── expense.py
│   ├── income.py
│   ├── budget.py
│   └── deadline.py
├── services/                      # Business logic
│   ├── auth_service.py
│   ├── analytics_service.py
│   ├── export_service.py          # NEW: CSV + PDF export
│   └── event_bus.py               # NEW: replaces refresh_all_tabs()
└── ui/
    ├── app.py                     # Window shell only
    ├── login_screen.py
    ├── main_view.py
    └── tabs/
        ├── add_expense_tab.py
        ├── manage_data_tab.py
        ├── wallet_tab.py
        ├── analytics_tab.py
        ├── deadlines_tab.py
        └── settings_tab.py
```

## Key improvements

| Issue | Fix |
|---|---|
| Login/dashboard slow | Connection pool — single pool shared across app, no per-request TCP handshake |
| Charts freeze UI | Chart data fetched in background thread, only `canvas.draw()` on main thread |
| `refresh_all_tabs()` reruns everything | Event bus — each tab subscribes only to its relevant events |
| Overdue deadlines showed "-3 Days Left" | Overdue items get their own purple bucket: "Overdue by 3 days" |
| Silent `except: pass` hiding bugs | All exceptions logged with `logger.error()`, real errors surfaced |
| SQL injection in `get_filtered_df` | Table names whitelisted in `config.ALLOWED_TABLES` |
| 724-line God Class | Split into 16 focused modules |

## New features

- **Export to CSV** — expenses and income, filtered by current time period
- **Export to PDF** — full summary report with table (requires `reportlab`)
- **Enter key** submits login form
- **Budget pre-filled** from last saved value in Settings tab
- **Deadlines kanban** now has 5 buckets: Overdue / High / Medium / Low / Completed

## Setup

```bash
pip install -r requirements.txt
python main.py
```

## Environment

- Set `EXPENSIS_LOG_LEVEL=DEBUG` for verbose logging
- DB config stored in `db_config.json` (auto-created on first save)
