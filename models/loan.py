# models/loan.py — Loan CRUD
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from db import get_connection

logger = logging.getLogger(__name__)


@dataclass
class Loan:
    id: int
    user_id: int
    loan_name: str
    bank: str
    total_amount: float
    monthly_payment: float
    months_remaining: int
    interest_rate: float
    created_at: datetime


def get_loans(user_id: int) -> list[Loan]:
    try:
        with get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM loans WHERE user_id=%s ORDER BY created_at ASC",
                (user_id,),
            )
            rows = cursor.fetchall()
            cursor.close()
        return [Loan(
            id=r["id"], user_id=r["user_id"], loan_name=r["loan_name"],
            bank=r["bank"], total_amount=float(r["total_amount"]),
            monthly_payment=float(r["monthly_payment"]),
            months_remaining=r["months_remaining"],
            interest_rate=float(r["interest_rate"]),
            created_at=r["created_at"],
        ) for r in rows]
    except Exception as e:
        logger.error("get_loans failed: %s", e)
        return []


def add_loan(user_id: int, loan_name: str, bank: str, total_amount: float,
             monthly_payment: float, months_remaining: int,
             interest_rate: float) -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO loans (user_id, loan_name, bank, total_amount, "
                "monthly_payment, months_remaining, interest_rate) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (user_id, loan_name, bank, total_amount,
                 monthly_payment, months_remaining, interest_rate),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("add_loan failed: %s", e)
        return False


def update_loan(loan_id: int, user_id: int, loan_name: str, bank: str,
                total_amount: float, monthly_payment: float,
                months_remaining: int, interest_rate: float) -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE loans SET loan_name=%s, bank=%s, total_amount=%s, "
                "monthly_payment=%s, months_remaining=%s, interest_rate=%s "
                "WHERE id=%s AND user_id=%s",
                (loan_name, bank, total_amount, monthly_payment,
                 months_remaining, interest_rate, loan_id, user_id),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("update_loan failed: %s", e)
        return False


def delete_loan(loan_id: int, user_id: int) -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM loans WHERE id=%s AND user_id=%s",
                (loan_id, user_id),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("delete_loan failed: %s", e)
        return False


def get_total_monthly_loan_payments(user_id: int) -> float:
    """Sum of all active monthly loan payments."""
    loans = get_loans(user_id)
    return sum(l.monthly_payment for l in loans if l.months_remaining > 0)
