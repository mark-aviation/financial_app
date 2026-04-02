# api.py — Expensis Pro FastAPI Backend
#
# Place in the same directory as main.py (expensis_v3/)
# Runs automatically when main.py starts, or directly: python api.py

import logging
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, date
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── App modules ───────────────────────────────────────────────────────────────
from db.connection import init_pool, load_db_config
from services.auth_service import authenticate, register, get_user_categories, add_custom_category
from services.analytics_service import get_summary_totals, get_wallet_balances, get_pie_data, get_expense_by_category_over_time
from services.purchase_advisor import analyse_purchase
from services.budget_service import get_project_budget_summary
from models.expense import get_expenses_df, add_expense, delete_expenses, update_expense
from models.income import get_income_df, add_income, delete_income, update_income, transfer_funds, get_wallet_list
from models.deadline import get_deadlines, add_deadline, update_deadline, complete_deadline, reactivate_deadline, delete_deadline
from models.budget import get_latest_budget, set_budget
from models.fixed_bills import get_fixed_bills, add_fixed_bill, delete_fixed_bill, update_fixed_bill
from models.purchase import get_purchases, add_purchase, update_purchase_status, delete_purchase

logger = logging.getLogger(__name__)

# ── Static file paths ────────────────────────────────────────────────────────
_HERE        = os.path.dirname(os.path.abspath(__file__))
_UI_DIR      = os.path.join(_HERE, "expensis_web")
_UI_INDEX    = os.path.join(_UI_DIR, "index.html")
_UI_FALLBACK = os.path.join(_HERE, "expensis_web.html")

# ── Lifespan ──────────────────────────────────────────────────────────────────
import asyncio

def _run_auto_migrate():
    """Create any missing v7 tables on startup."""
    logger.info("Running auto-migrate...")
    sql_statements = [
        """CREATE TABLE IF NOT EXISTS financial_profile (
            id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL UNIQUE,
            monthly_salary DECIMAL(12,2) NOT NULL DEFAULT 0,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)""",
        """CREATE TABLE IF NOT EXISTS loans (
            id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL,
            loan_name VARCHAR(200) NOT NULL, bank VARCHAR(200) NOT NULL DEFAULT '',
            total_amount DECIMAL(12,2) NOT NULL DEFAULT 0,
            monthly_payment DECIMAL(12,2) NOT NULL DEFAULT 0,
            months_remaining INT NOT NULL DEFAULT 0,
            interest_rate DECIMAL(5,2) NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)""",
        """CREATE TABLE IF NOT EXISTS credit_cards (
            id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL,
            card_name VARCHAR(200) NOT NULL, bank VARCHAR(200) NOT NULL DEFAULT '',
            credit_limit DECIMAL(12,2) NOT NULL DEFAULT 0,
            current_balance DECIMAL(12,2) NOT NULL DEFAULT 0,
            minimum_payment_pct DECIMAL(5,2) NOT NULL DEFAULT 2.00,
            payment_due_day TINYINT NOT NULL DEFAULT 1,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)""",
        """CREATE TABLE IF NOT EXISTS planned_purchases (
            id INT AUTO_INCREMENT PRIMARY KEY, user_id INT NOT NULL,
            item_name VARCHAR(300) NOT NULL, price DECIMAL(12,2) NOT NULL,
            wallet VARCHAR(100) NOT NULL DEFAULT '',
            payment_method VARCHAR(20) NOT NULL DEFAULT 'cash',
            status VARCHAR(20) NOT NULL DEFAULT 'planned',
            notes TEXT, created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE)""",
    ]
    try:
        from db.connection import get_connection
        with get_connection() as conn:
            cursor = conn.cursor()
            for sql in sql_statements:
                cursor.execute(sql)
            conn.commit()
            cursor.close()
        logger.info("Auto-migrate complete")
    except Exception as e:
        logger.warning("Auto-migrate failed (non-fatal): %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Retry DB connection — on boot, MySQL may not be ready yet
    max_retries = 10
    retry_delay = 3  # seconds between attempts
    for attempt in range(1, max_retries + 1):
        try:
            init_pool()
            logger.info("DB pool initialized on attempt %d", attempt)
            break
        except Exception as e:
            logger.warning("DB connection attempt %d/%d failed: %s", attempt, max_retries, e)
            if attempt < max_retries:
                await asyncio.sleep(retry_delay)
            else:
                logger.error("Could not connect to DB after %d attempts. Will retry on first request.", max_retries)
    yield

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Expensis Pro API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve expensis_web/ folder as static (styles.css, app.js)
if os.path.isdir(_UI_DIR):
    app.mount("/ui", StaticFiles(directory=_UI_DIR), name="ui")

# ── In-memory session store ───────────────────────────────────────────────────
_sessions: dict[str, dict] = {}

def ensure_db():
    """Try to init the DB pool if it failed at startup (e.g. MySQL wasn't ready yet)."""
    import db.connection as _db_conn
    if _db_conn._pool is None:
        try:
            init_pool()
            logger.info("DB pool initialized on lazy reconnect")
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"Database not ready yet. Please wait a moment and try again."
            )

# ── UI file routes ────────────────────────────────────────────────────────────
@app.get("/", include_in_schema=False)
def serve_ui():
    if os.path.exists(_UI_INDEX):    return FileResponse(_UI_INDEX,    media_type="text/html")
    if os.path.exists(_UI_FALLBACK): return FileResponse(_UI_FALLBACK, media_type="text/html")
    return JSONResponse({"message": "Expensis Pro API running. Place expensis_web/ folder next to api.py."})

@app.get("/styles.css", include_in_schema=False)
def serve_css():
    f = os.path.join(_UI_DIR, "styles.css")
    return FileResponse(f, media_type="text/css") if os.path.exists(f) else Response(status_code=404)

@app.get("/app.js", include_in_schema=False)
def serve_js():
    f = os.path.join(_UI_DIR, "app.js")
    return FileResponse(f, media_type="application/javascript") if os.path.exists(f) else Response(status_code=404)

@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    ico = bytes([0,0,1,0,1,0,1,1,0,0,1,0,24,0,40,0,0,0,22,0,0,0,1,0,0,0,1,0,
                 24,0,0,0,0,0,4,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,
                 255,255,255,0,0,0,0,255])
    return Response(content=ico, media_type="image/x-icon")


# ═════════════════════════════════════════════════════════════════════════════
# AUTH HELPERS
# ═════════════════════════════════════════════════════════════════════════════

def get_current_user(request: Request) -> dict:
    ensure_db()  # Reconnect if DB wasn't ready at boot
    token = request.headers.get("X-Session-Token") or request.cookies.get("session_token")
    if not token or token not in _sessions:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _sessions[token]


# ═════════════════════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═════════════════════════════════════════════════════════════════════════════

class LoginRequest(BaseModel):
    username: str
    password: str

class ExpenseCreate(BaseModel):
    date: str
    source: str
    category: str
    description: str
    amount: float

class ExpenseUpdate(BaseModel):
    date: str
    source: str
    description: str
    amount: float

class IncomeCreate(BaseModel):
    date: str
    source: str
    amount: float

class IncomeUpdate(BaseModel):
    date: str
    source: str
    amount: float

class TransferRequest(BaseModel):
    date: str
    from_wallet: str
    to_wallet: str
    amount: float

class DeadlineCreate(BaseModel):
    project_name: str
    start_date: str
    end_date: str
    estimated_cost: Optional[float] = None
    priority_level: Optional[str] = None
    allocations: Optional[list[dict]] = None

class DeadlineUpdate(BaseModel):
    project_name: str
    start_date: str
    end_date: str
    estimated_cost: Optional[float] = None
    priority_level: Optional[str] = None
    allocations: Optional[list[dict]] = None

class BudgetSet(BaseModel):
    amount: float

class FixedBillCreate(BaseModel):
    name: str
    amount: float
    wallet: str = ""

class FixedBillUpdate(BaseModel):
    name: str
    amount: float
    wallet: str = ""

class CategoryCreate(BaseModel):
    name: str

class PurchaseCreate(BaseModel):
    item_name: str
    price: float
    wallet: str
    payment_method: str
    notes: str = ""

class AdvisorRequest(BaseModel):
    item_name: str
    price: float
    loan_months: int = 12
    interest_rate: float = 0.0
    salary_alloc_amount: float = 0.0

class DbConfigSave(BaseModel):
    host: str
    port: int = 3306
    user: str
    password: str
    database: str

class RegisterRequest(BaseModel):
    username: str
    password: str


# ═════════════════════════════════════════════════════════════════════════════
# AUTH ENDPOINTS
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/auth/login")
def login(body: LoginRequest):
    ensure_db()  # Make sure DB is up before login attempt
    try:
        user = authenticate(body.username, body.password)
    except ConnectionError as e:
        raise HTTPException(status_code=503, detail=str(e))

    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = secrets.token_hex(32)
    _sessions[token] = user
    return {"token": token, "user_id": user["id"], "username": user["username"]}


@app.post("/api/v1/auth/register")
def register_user(body: RegisterRequest):
    try:
        ok = register(body.username, body.password)
    except (ConnectionError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not ok:
        raise HTTPException(status_code=409, detail="Username already exists")
    return {"ok": True}


@app.post("/api/v1/auth/logout")
def logout(request: Request):
    token = request.headers.get("X-Session-Token")
    if token and token in _sessions:
        del _sessions[token]
    return {"ok": True}


@app.get("/api/v1/auth/me")
def me(user=Depends(get_current_user)):
    return user


# ═════════════════════════════════════════════════════════════════════════════
# SUMMARY / DASHBOARD
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/summary")
def summary(filter_mode: str = "This Month", user=Depends(get_current_user)):
    uid = user["id"]
    totals = get_summary_totals(uid, filter_mode)
    wallets = get_wallet_balances(uid, "All Time")
    budget = get_latest_budget(uid) or 0.0
    from models.fixed_bills import get_total_fixed_bills
    fixed_bills = get_total_fixed_bills(uid)
    return {
        "total_income": totals["total_in"],
        "total_spent": totals["total_out"],
        "net_balance": totals["net"],
        "fixed_bills": fixed_bills,
        "after_fixed_bills": totals["net"] - fixed_bills,
        "monthly_budget": budget,
        "wallets": wallets,
    }


# ═════════════════════════════════════════════════════════════════════════════
# EXPENSES
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/expenses")
def list_expenses(filter_mode: str = "This Month", search: str = "", user=Depends(get_current_user)):
    df = get_expenses_df(user["id"], filter_mode, search)
    if df.empty:
        return []
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    return df.to_dict("records")


@app.post("/api/v1/expenses")
def create_expense(body: ExpenseCreate, user=Depends(get_current_user)):
    ok = add_expense(user["id"], body.date, body.source, body.category, body.description, body.amount)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save expense")
    return {"ok": True}


@app.put("/api/v1/expenses/{expense_id}")
def edit_expense(expense_id: int, body: ExpenseUpdate, user=Depends(get_current_user)):
    ok = update_expense(expense_id, user["id"], body.date, body.source, body.description, body.amount)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update expense")
    return {"ok": True}


@app.delete("/api/v1/expenses/{expense_id}")
def remove_expense(expense_id: int, user=Depends(get_current_user)):
    ok = delete_expenses([expense_id], user["id"])
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete expense")
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════════
# INCOME
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/income")
def list_income(filter_mode: str = "This Month", user=Depends(get_current_user)):
    df = get_income_df(user["id"], filter_mode)
    if df.empty:
        return []
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")
    # Exclude internal transfer rows for display
    if "IsTransfer" in df.columns:
        df = df[df["IsTransfer"] == 0]
    return df.to_dict("records")


@app.post("/api/v1/income")
def create_income(body: IncomeCreate, user=Depends(get_current_user)):
    ok = add_income(user["id"], body.date, body.source, body.amount)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save income")
    return {"ok": True}


@app.put("/api/v1/income/{income_id}")
def edit_income(income_id: int, body: IncomeUpdate, user=Depends(get_current_user)):
    ok = update_income(income_id, body.date, body.source, body.amount)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update income")
    return {"ok": True}


@app.delete("/api/v1/income/{income_id}")
def remove_income(income_id: int, user=Depends(get_current_user)):
    ok = delete_income(income_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete income")
    return {"ok": True}


@app.post("/api/v1/income/transfer")
def do_transfer(body: TransferRequest, user=Depends(get_current_user)):
    if body.from_wallet == body.to_wallet:
        raise HTTPException(status_code=400, detail="Source and destination must differ")
    ok = transfer_funds(user["id"], body.date, body.from_wallet, body.to_wallet, body.amount)
    if not ok:
        raise HTTPException(status_code=500, detail="Transfer failed")
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════════
# WALLETS
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/wallets")
def list_wallets(user=Depends(get_current_user)):
    wallets = get_wallet_list(user["id"])
    balances = get_wallet_balances(user["id"], "All Time")
    bal_map = {w["wallet"]: w["balance"] for w in balances}
    return [{"name": w, "balance": bal_map.get(w, 0.0)} for w in wallets]


# ═════════════════════════════════════════════════════════════════════════════
# ANALYTICS
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/analytics/categories")
def analytics_by_category(filter_mode: str = "This Month", user=Depends(get_current_user)):
    pie = get_pie_data(user["id"], filter_mode)
    return [{"category": l, "amount": v} for l, v in zip(pie.labels, pie.values)]


@app.get("/api/v1/analytics/wallets")
def analytics_by_wallet(filter_mode: str = "This Month", user=Depends(get_current_user)):
    df = get_expenses_df(user["id"], filter_mode)
    if df.empty:
        return []
    df = df[df["Category"] != "Transfer"]
    grouped = df.groupby("Source")["Amount"].sum().reset_index()
    grouped.columns = ["wallet", "amount"]
    return grouped.sort_values("amount", ascending=False).to_dict("records")


@app.get("/api/v1/analytics/trend")
def analytics_trend(filter_mode: str = "This Month", timeframe: str = "Month", user=Depends(get_current_user)):
    data = get_expense_by_category_over_time(user["id"], filter_mode, timeframe)
    if data.is_empty:
        return {"periods": [], "categories": [], "data": {}}
    return {"periods": data.periods, "categories": data.categories, "data": data.data}


# ═════════════════════════════════════════════════════════════════════════════
# DEADLINES
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/deadlines")
def list_deadlines(user=Depends(get_current_user)):
    items = get_deadlines(user["id"])
    return [
        {
            "id": d.id,
            "project_name": d.project_name,
            "start_date": str(d.start_date),
            "end_date": str(d.end_date),
            "status": d.status,
            "days_left": d.days_left,
            "triage": d.triage,
            "status_text": d.status_text,
            "bar_color": d.bar_color,
            "estimated_cost": d.estimated_cost,
            "priority_level": d.priority_level,
            "allocations": d.allocations,
        }
        for d in items
    ]


@app.post("/api/v1/deadlines")
def create_deadline(body: DeadlineCreate, user=Depends(get_current_user)):
    ok, err = add_deadline(
        user["id"], body.project_name, body.start_date, body.end_date,
        body.estimated_cost, body.priority_level, body.allocations,
    )
    if not ok:
        raise HTTPException(status_code=500, detail=err or "Failed to create deadline")
    return {"ok": True}


@app.put("/api/v1/deadlines/{deadline_id}")
def edit_deadline(deadline_id: int, body: DeadlineUpdate, user=Depends(get_current_user)):
    ok = update_deadline(
        deadline_id, body.project_name, body.start_date, body.end_date,
        body.estimated_cost, body.priority_level, body.allocations,
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update deadline")
    return {"ok": True}


@app.post("/api/v1/deadlines/{deadline_id}/complete")
def mark_complete(deadline_id: int, user=Depends(get_current_user)):
    ok = complete_deadline(deadline_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to complete deadline")
    return {"ok": True}


@app.post("/api/v1/deadlines/{deadline_id}/reactivate")
def mark_reactivate(deadline_id: int, user=Depends(get_current_user)):
    ok = reactivate_deadline(deadline_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to reactivate")
    return {"ok": True}


@app.delete("/api/v1/deadlines/{deadline_id}")
def remove_deadline(deadline_id: int, user=Depends(get_current_user)):
    ok = delete_deadline(deadline_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete deadline")
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════════
# PROJECT BUDGETS
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/projects")
def project_budgets(user=Depends(get_current_user)):
    try:
        summary = get_project_budget_summary(user["id"])
        # Calculate total still needed across all projects
        total_needed = sum(r.funds_needed for r in summary.allocation_rows)
        return {
            "total_wallet_balance": float(summary.total_wallet_balance),
            "total_committed":      float(summary.total_committed),
            "available_balance":    float(summary.available_balance),
            "is_over_committed":    bool(summary.is_over_committed),
            "total_needed":         float(total_needed),
            "rows": [
                {
                    "project_name":   str(r.project_name),
                    "priority_level": str(r.priority_level) if r.priority_level else "—",
                    "wallet_name":    str(r.wallet_name),
                    "allocated_cost": float(r.allocated_cost),
                    "wallet_balance": float(r.wallet_balance),
                    "budget_status":  str(r.budget_status),
                    "estimated_cost": float(r.estimated_cost) if r.estimated_cost else 0.0,
                    "total_allocated":float(r.total_allocated),
                    "funds_needed":   float(r.funds_needed),
                }
                for r in summary.allocation_rows
            ],
        }
    except Exception as e:
        logger.error("project_budgets failed: %s", e, exc_info=True)
        # Return empty summary instead of 500 so the UI shows graceful empty state
        return {
            "total_wallet_balance": 0.0,
            "total_committed": 0.0,
            "available_balance": 0.0,
            "is_over_committed": False,
            "total_needed": 0.0,
            "rows": [],
            "error": str(e),
        }


# ═════════════════════════════════════════════════════════════════════════════
# DEBUG — remove after fixing
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/debug/projects")
def debug_projects(user=Depends(get_current_user)):
    """Returns detailed error info to diagnose the projects tab."""
    import traceback
    result = {"user_id": user["id"], "steps": []}
    try:
        from models.deadline import get_budgeted_deadlines
        deadlines = get_budgeted_deadlines(user["id"])
        result["steps"].append(f"get_budgeted_deadlines: {len(deadlines)} items")
        result["deadlines"] = [{"id": d.id, "name": d.project_name, "allocations": d.allocations} for d in deadlines]
    except Exception as e:
        result["steps"].append(f"get_budgeted_deadlines FAILED: {e}")
        result["traceback"] = traceback.format_exc()
        return result
    try:
        from services.analytics_service import get_wallet_balances
        wallets = get_wallet_balances(user["id"], "All Time")
        result["steps"].append(f"get_wallet_balances: {len(wallets)} wallets")
        result["wallets"] = wallets
    except Exception as e:
        result["steps"].append(f"get_wallet_balances FAILED: {e}")
        result["traceback"] = traceback.format_exc()
        return result
    try:
        summary = get_project_budget_summary(user["id"])
        result["steps"].append(f"get_project_budget_summary: {len(summary.allocation_rows)} rows")
        result["summary"] = {"total_wallet": summary.total_wallet_balance, "total_committed": summary.total_committed, "rows": len(summary.allocation_rows)}
    except Exception as e:
        result["steps"].append(f"get_project_budget_summary FAILED: {e}")
        result["traceback"] = traceback.format_exc()
    return result


# ═════════════════════════════════════════════════════════════════════════════
# BUY ADVISOR
# ═════════════════════════════════════════════════════════════════════════════

@app.post("/api/v1/advisor/analyze")
def advisor_analyze(body: AdvisorRequest, user=Depends(get_current_user)):
    try:
        result = analyse_purchase(
            user["id"], body.item_name, body.price,
            body.loan_months, body.interest_rate, body.salary_alloc_amount,
        )
        return {
            "verdict":               str(result.verdict),
            "verdict_reason":        str(result.verdict_reason),
            "salary":                float(result.salary),
            "avg_monthly_expenses":  float(result.avg_monthly_expenses),
            "total_fixed_bills":     float(result.total_fixed_bills),
            "true_disposable_income":float(result.true_disposable_income),
            "monthly_budget":        float(result.monthly_budget),
            "budget_remaining":      float(result.budget_remaining),
            "total_wallet_balance":  float(result.total_wallet_balance),
            "has_cash_today":        bool(result.has_cash_today),
            "monthly_loan_payment":  float(result.monthly_loan_payment),
            "total_loan_cost":       float(result.total_loan_cost),
            "interest_cost":         float(result.interest_cost),
            "payment_options": [
                {
                    "method":         str(o.method),
                    "feasible":       bool(o.feasible),
                    "label":          str(o.label),
                    "detail":         str(o.detail),
                    "monthly_impact": float(o.monthly_impact),
                }
                for o in result.payment_options
            ],
        }
    except Exception as e:
        logger.error("advisor_analyze failed: %s", e, exc_info=True)
        # Return a graceful degraded response based purely on wallet balance
        # when financial profile tables (salary, loans, cards) are not set up
        try:
            from services.analytics_service import get_wallet_balances
            wallets = get_wallet_balances(user["id"], "All Time")
            total_bal = float(sum(w["balance"] for w in wallets))
            has_cash  = total_bal >= body.price
            if has_cash and total_bal >= body.price * 1.2:
                verdict = "yes"
                reason  = f"Your total wallet balance is {fmt_php(total_bal)}. You have enough to cover {fmt_php(body.price)} with room to spare."
            elif has_cash:
                verdict = "caution"
                reason  = f"Your total wallet balance is {fmt_php(total_bal)}. You can afford {fmt_php(body.price)} but it will leave little buffer."
            else:
                verdict = "no"
                reason  = f"Your total wallet balance is {fmt_php(total_bal)}, which is less than {fmt_php(body.price)}. Consider saving more first."
            return {
                "verdict": verdict, "verdict_reason": reason,
                "salary": 0.0, "avg_monthly_expenses": 0.0,
                "total_fixed_bills": 0.0, "true_disposable_income": 0.0,
                "monthly_budget": 0.0, "budget_remaining": 0.0,
                "total_wallet_balance": total_bal, "has_cash_today": has_cash,
                "monthly_loan_payment": body.price / max(body.loan_months, 1),
                "total_loan_cost": body.price, "interest_cost": 0.0,
                "payment_options": [{
                    "method": "cash", "feasible": has_cash,
                    "label": f"{'✅' if has_cash else '❌'} Cash — wallet balance: {fmt_php(total_bal)}",
                    "detail": f"Total across all wallets: {fmt_php(total_bal)}. Item costs: {fmt_php(body.price)}.",
                    "monthly_impact": 0.0,
                }],
            }
        except Exception as e2:
            raise HTTPException(status_code=500, detail=f"Advisor failed: {e}. Fallback also failed: {e2}")

def fmt_php(n: float) -> str:
    return f"₱{n:,.2f}"


@app.get("/api/v1/advisor/purchases")
def list_purchases(user=Depends(get_current_user)):
    items = get_purchases(user["id"])
    return [
        {
            "id": p.id,
            "item_name": p.item_name,
            "price": p.price,
            "wallet": p.wallet,
            "payment_method": p.payment_method,
            "status": p.status,
            "notes": p.notes,
            "created_at": str(p.created_at),
        }
        for p in items
    ]


@app.post("/api/v1/advisor/purchases")
def create_purchase(body: PurchaseCreate, user=Depends(get_current_user)):
    ok = add_purchase(user["id"], body.item_name, body.price, body.wallet, body.payment_method, body.notes)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save purchase")
    return {"ok": True}


@app.patch("/api/v1/advisor/purchases/{purchase_id}/status")
def set_purchase_status(purchase_id: int, status: str, user=Depends(get_current_user)):
    ok = update_purchase_status(purchase_id, user["id"], status)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update status")
    return {"ok": True}


@app.delete("/api/v1/advisor/purchases/{purchase_id}")
def remove_purchase(purchase_id: int, user=Depends(get_current_user)):
    ok = delete_purchase(purchase_id, user["id"])
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete purchase")
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════════
# SETTINGS
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/settings/budget")
def get_budget(user=Depends(get_current_user)):
    return {"amount": get_latest_budget(user["id"]) or 0.0}


@app.post("/api/v1/settings/budget")
def save_budget(body: BudgetSet, user=Depends(get_current_user)):
    ok = set_budget(user["id"], body.amount)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to save budget")
    return {"ok": True}


@app.get("/api/v1/settings/fixed-bills")
def list_fixed_bills(user=Depends(get_current_user)):
    return get_fixed_bills(user["id"])


@app.post("/api/v1/settings/fixed-bills")
def create_fixed_bill(body: FixedBillCreate, user=Depends(get_current_user)):
    ok = add_fixed_bill(user["id"], body.name, body.amount, body.wallet)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to add bill")
    return {"ok": True}


@app.put("/api/v1/settings/fixed-bills/{bill_id}")
def edit_fixed_bill(bill_id: int, body: FixedBillUpdate, user=Depends(get_current_user)):
    ok = update_fixed_bill(bill_id, body.name, body.amount, body.wallet)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to update bill")
    return {"ok": True}


@app.delete("/api/v1/settings/fixed-bills/{bill_id}")
def remove_fixed_bill(bill_id: int, user=Depends(get_current_user)):
    ok = delete_fixed_bill(bill_id)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to delete bill")
    return {"ok": True}


@app.get("/api/v1/settings/categories")
def list_categories(user=Depends(get_current_user)):
    from config import DEFAULT_CATEGORIES
    return get_user_categories(user["id"], DEFAULT_CATEGORIES)


@app.post("/api/v1/settings/categories")
def create_category(body: CategoryCreate, user=Depends(get_current_user)):
    ok = add_custom_category(user["id"], body.name)
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to add category")
    return {"ok": True}


@app.get("/api/v1/settings/db-config")
def get_db_config(user=Depends(get_current_user)):
    cfg = load_db_config()
    cfg.pop("password", None)  # never send password back
    return cfg


@app.post("/api/v1/settings/db-config")
def save_db_config_endpoint(body: DbConfigSave, user=Depends(get_current_user)):
    from db.connection import save_db_config, init_pool
    cfg = {"host": body.host, "port": body.port, "user": body.user,
           "password": body.password, "database": body.database}
    save_db_config(cfg)
    try:
        init_pool(cfg)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Config saved but reconnect failed: {e}")
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════════
# HEALTH CHECK
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/v1/health")
def health():
    from db.connection import is_connected
    return {"status": "ok", "db": "connected" if is_connected() else "disconnected"}


@app.get("/api/v1/admin/migrate")
@app.post("/api/v1/admin/migrate")
def run_migration():  # No auth required — only creates tables, no data access
    """Run database migrations to create any missing tables."""
    sql_statements = [
        """CREATE TABLE IF NOT EXISTS financial_profile (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            user_id        INT            NOT NULL UNIQUE,
            monthly_salary DECIMAL(12,2)  NOT NULL DEFAULT 0,
            updated_at     DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP
                                          ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS loans (
            id               INT AUTO_INCREMENT PRIMARY KEY,
            user_id          INT            NOT NULL,
            loan_name        VARCHAR(200)   NOT NULL,
            bank             VARCHAR(200)   NOT NULL DEFAULT '',
            total_amount     DECIMAL(12,2)  NOT NULL DEFAULT 0,
            monthly_payment  DECIMAL(12,2)  NOT NULL DEFAULT 0,
            months_remaining INT            NOT NULL DEFAULT 0,
            interest_rate    DECIMAL(5,2)   NOT NULL DEFAULT 0,
            created_at       DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS credit_cards (
            id                  INT AUTO_INCREMENT PRIMARY KEY,
            user_id             INT            NOT NULL,
            card_name           VARCHAR(200)   NOT NULL,
            bank                VARCHAR(200)   NOT NULL DEFAULT '',
            credit_limit        DECIMAL(12,2)  NOT NULL DEFAULT 0,
            current_balance     DECIMAL(12,2)  NOT NULL DEFAULT 0,
            minimum_payment_pct DECIMAL(5,2)   NOT NULL DEFAULT 2.00,
            payment_due_day     TINYINT        NOT NULL DEFAULT 1,
            created_at          DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS planned_purchases (
            id             INT AUTO_INCREMENT PRIMARY KEY,
            user_id        INT            NOT NULL,
            item_name      VARCHAR(300)   NOT NULL,
            price          DECIMAL(12,2)  NOT NULL,
            wallet         VARCHAR(100)   NOT NULL DEFAULT '',
            payment_method VARCHAR(20)    NOT NULL DEFAULT 'cash',
            status         VARCHAR(20)    NOT NULL DEFAULT 'planned',
            notes          TEXT,
            created_at     DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )""",
    ]
    results = []
    try:
        from db.connection import get_connection
        with get_connection() as conn:
            cursor = conn.cursor()
            for sql in sql_statements:
                try:
                    cursor.execute(sql)
                    table = sql.split("IF NOT EXISTS")[1].split("(")[0].strip()
                    results.append(f"✓ {table}")
                except Exception as e:
                    results.append(f"✗ Error: {e}")
            conn.commit()
            cursor.close()
        return {"ok": True, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    import sys
    import os

    # ── Windows auto-start on boot setup ────────────────────────────────────
    if "--install" in sys.argv:
        script_dir  = os.path.dirname(os.path.abspath(__file__))
        script_path = os.path.abspath(__file__)
        python_exe  = sys.executable

        # Write the bat file (with MySQL wait + logging)
        bat_path = os.path.join(script_dir, "expensis_autostart.bat")
        log_path = os.path.join(script_dir, "expensis_startup.log")
        bat_content = (
            "@echo off\n"
            "setlocal EnableDelayedExpansion\n"
            f'cd /d "{script_dir}"\n'
            f'echo [%date% %time%] Starting >> "{log_path}"\n'
            "set READY=0\n"
            "for /L %%i in (1,1,30) do (\n"
            "    if !READY!==0 (\n"
            "        netstat -an 2>nul | find \"3306\" | find \"LISTENING\" >nul\n"
            "        if !errorlevel!==0 (\n"
            "            set READY=1\n"
            f'            echo [%date% %time%] MySQL ready >> "{log_path}"\n'
            "        ) else (\n"
            f'            echo [%date% %time%] Waiting MySQL %%i/30 >> "{log_path}"\n'
            "            timeout /t 3 /nobreak >nul\n"
            "        )\n"
            "    )\n"
            ")\n"
            f'echo [%date% %time%] Launching API >> "{log_path}"\n'
            f'"{python_exe}" "{script_path}" >> "{log_path}" 2>&1\n'
            f'echo [%date% %time%] API stopped >> "{log_path}"\n'
        )
        with open(bat_path, "w") as f:
            f.write(bat_content)

        # Use Task Scheduler — far more reliable than registry Run key
        task_name = "ExpensisProAPI"
        # Delete existing task if any
        os.system("schtasks /delete /tn " + task_name + " /f >nul 2>&1")
        # Create new task: runs at login, with 30s delay, as current user
        cmd = " ".join([
            "schtasks /create",
            "/tn", task_name,
            "/tr", '"' + bat_path + '"',
            "/sc onlogon",
            "/delay 0000:30",
            "/ru %USERNAME%",
            "/f"
        ])
        result = os.system(cmd)
        if result == 0:
            print("✓ Expensis Pro added to Windows Task Scheduler.")
            print(f"  It will start 30 seconds after you log in.")
            print(f"  Log file: {log_path}")
            print()
            print("To test right now:")
            print(f'  schtasks /run /tn "{task_name}"')
        else:
            print("✗ Task Scheduler failed. Falling back to registry...")
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(key, task_name, 0, winreg.REG_SZ, f'"{bat_path}"')
            winreg.CloseKey(key)
            print("✓ Added to registry startup instead.")
        sys.exit(0)

    if "--uninstall" in sys.argv:
        task_name = "ExpensisProAPI"
        # Remove from Task Scheduler
        r1 = os.system(f'schtasks /delete /tn "{task_name}" /f')
        # Also remove from registry just in case
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_SET_VALUE)
            winreg.DeleteValue(key, task_name)
            winreg.CloseKey(key)
        except Exception:
            pass
        print("✓ Expensis Pro removed from Windows startup.")
        sys.exit(0)

    # ── Normal run ───────────────────────────────────────────────────────────
    print("Starting Expensis Pro API on http://0.0.0.0:8000 ...")
    uvicorn.run("api:app", host="0.0.0.0", port=8000, reload=False)