# models/credit_card.py — Credit card CRUD
import logging
from dataclasses import dataclass
from datetime import datetime
from db import get_connection

logger = logging.getLogger(__name__)


@dataclass
class CreditCard:
    id: int
    user_id: int
    card_name: str
    bank: str
    credit_limit: float
    current_balance: float
    minimum_payment_pct: float
    payment_due_day: int
    created_at: datetime

    @property
    def available_credit(self) -> float:
        return max(0.0, self.credit_limit - self.current_balance)

    @property
    def minimum_payment(self) -> float:
        return self.current_balance * (self.minimum_payment_pct / 100)

    @property
    def utilization_pct(self) -> float:
        if self.credit_limit <= 0:
            return 0.0
        return (self.current_balance / self.credit_limit) * 100


def get_credit_cards(user_id: int) -> list[CreditCard]:
    try:
        with get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM credit_cards WHERE user_id=%s ORDER BY created_at ASC",
                (user_id,),
            )
            rows = cursor.fetchall()
            cursor.close()
        return [CreditCard(
            id=r["id"], user_id=r["user_id"], card_name=r["card_name"],
            bank=r["bank"], credit_limit=float(r["credit_limit"]),
            current_balance=float(r["current_balance"]),
            minimum_payment_pct=float(r["minimum_payment_pct"]),
            payment_due_day=r["payment_due_day"],
            created_at=r["created_at"],
        ) for r in rows]
    except Exception as e:
        logger.error("get_credit_cards failed: %s", e)
        return []


def add_credit_card(user_id: int, card_name: str, bank: str,
                    credit_limit: float, current_balance: float,
                    minimum_payment_pct: float, payment_due_day: int) -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO credit_cards (user_id, card_name, bank, credit_limit, "
                "current_balance, minimum_payment_pct, payment_due_day) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (user_id, card_name, bank, credit_limit, current_balance,
                 minimum_payment_pct, payment_due_day),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("add_credit_card failed: %s", e)
        return False


def update_credit_card(card_id: int, user_id: int, card_name: str, bank: str,
                       credit_limit: float, current_balance: float,
                       minimum_payment_pct: float, payment_due_day: int) -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE credit_cards SET card_name=%s, bank=%s, credit_limit=%s, "
                "current_balance=%s, minimum_payment_pct=%s, payment_due_day=%s "
                "WHERE id=%s AND user_id=%s",
                (card_name, bank, credit_limit, current_balance,
                 minimum_payment_pct, payment_due_day, card_id, user_id),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("update_credit_card failed: %s", e)
        return False


def delete_credit_card(card_id: int, user_id: int) -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM credit_cards WHERE id=%s AND user_id=%s",
                (card_id, user_id),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("delete_credit_card failed: %s", e)
        return False


def get_total_minimum_payments(user_id: int) -> float:
    """Sum of all minimum credit card payments due this month."""
    cards = get_credit_cards(user_id)
    return sum(c.minimum_payment for c in cards)
