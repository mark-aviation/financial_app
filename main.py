# main.py — Entry point
# Starts both the desktop app AND the web API server (in background thread).

import logging
import threading
from config import LOG_LEVEL
from db.connection import init_pool
from db.connection import init_db_pool

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.WARNING),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def start_api():
    """Launch the FastAPI web server in a background daemon thread."""
    try:
        import uvicorn
        print("[API] Starting web server on http://0.0.0.0:8000 ...")
        uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False, log_level="warning")
    except ImportError:
        print("[API] uvicorn not installed — web UI unavailable. Run: pip install fastapi uvicorn")
    except Exception as e:
        print(f"[API] Failed to start: {e}")


if __name__ == "__main__":
    # Startup import diagnostics
    print("--- Expensis startup diagnostics ---")
    for mod, names in [
        ("services.analytics_service", ["get_wallet_balances","get_pie_data_filtered","get_cashflow_data_filtered"]),
        ("services.time_filter",        ["TimeFilter","MODE_ALL"]),
        ("models.expense",              ["get_expenses_df_filtered","get_summary_stats"]),
    ]:
        try:
            m = __import__(mod, fromlist=names)
            for n in names: getattr(m, n)
            print(f"[OK] {mod}")
        except Exception as e:
            print(f"[FAIL] {mod}: {e}")
    print("--- end diagnostics ---")

    # Initialize DB connection pool
    try:
        init_pool()
    except Exception:
        pass  # Pool failure is shown in the UI via server status indicator

    # Start the web API in a background thread (daemon so it dies with the app)
    api_thread = threading.Thread(target=start_api, daemon=True)
    api_thread.start()

    # Start the desktop app (blocks until window is closed)
    from ui.app import App
    app = App()
    app.mainloop()
    # When the desktop app closes, the daemon thread stops automatically