# models/purchase.py — Planned purchases CRUD
import logging
from dataclasses import dataclass
from datetime import datetime
from db import get_connection

logger = logging.getLogger(__name__)

STATUS_PLANNED   = "planned"
STATUS_BOUGHT    = "bought"
STATUS_CANCELLED = "cancelled"

METHOD_CASH   = "cash"
METHOD_CREDIT = "credit"
METHOD_LOAN   = "loan"


@dataclass
class PlannedPurchase:
    id: int
    user_id: int
    item_name: str
    price: float
    wallet: str
    payment_method: str
    status: str
    notes: str
    created_at: datetime


def get_purchases(user_id: int) -> list[PlannedPurchase]:
    try:
        with get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT * FROM planned_purchases WHERE user_id=%s "
                "ORDER BY created_at DESC",
                (user_id,),
            )
            rows = cursor.fetchall()
            cursor.close()
        return [PlannedPurchase(
            id=r["id"], user_id=r["user_id"], item_name=r["item_name"],
            price=float(r["price"]), wallet=r["wallet"],
            payment_method=r["payment_method"], status=r["status"],
            notes=r["notes"] or "", created_at=r["created_at"],
        ) for r in rows]
    except Exception as e:
        logger.error("get_purchases failed: %s", e)
        return []


def add_purchase(user_id: int, item_name: str, price: float, wallet: str,
                 payment_method: str, notes: str = "") -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO planned_purchases "
                "(user_id, item_name, price, wallet, payment_method, notes) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (user_id, item_name, price, wallet, payment_method, notes),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("add_purchase failed: %s", e)
        return False


def update_purchase_status(purchase_id: int, user_id: int, status: str) -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE planned_purchases SET status=%s "
                "WHERE id=%s AND user_id=%s",
                (status, purchase_id, user_id),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("update_purchase_status failed: %s", e)
        return False


def delete_purchase(purchase_id: int, user_id: int) -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM planned_purchases WHERE id=%s AND user_id=%s",
                (purchase_id, user_id),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("delete_purchase failed: %s", e)
        return False
