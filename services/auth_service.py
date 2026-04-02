# services/auth_service.py — Authentication logic
#
# 💎 Dev: bcrypt lives here, not in the UI class.
#   UI calls authenticate() and register() — it never touches password hashes.

import logging

import bcrypt

from db import get_connection

logger = logging.getLogger(__name__)


def authenticate(username: str, password: str) -> dict | None:
    """
    Returns user dict {"id": int, "username": str} on success, None on failure.
    Raises ConnectionError if DB is unreachable (so UI can show correct message).
    """
    try:
        with get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, password_hash FROM users WHERE username=%s", (username,)
            )
            user = cursor.fetchone()
            cursor.close()
    except Exception as e:
        logger.error("authenticate DB error: %s", e)
        raise ConnectionError(f"Could not reach database: {e}") from e

    if user and bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        return {"id": user["id"], "username": username}

    return None


def register(username: str, password: str) -> bool:
    """
    Create a new user. Returns True on success, False if username already exists.
    Raises ConnectionError on DB failure.
    """
    if not username or not password:
        raise ValueError("Username and password are required.")

    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                (username, hashed),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        # MySQL error 1062 = duplicate entry
        if "1062" in str(e):
            return False
        logger.error("register DB error: %s", e)
        raise ConnectionError(f"Could not reach database: {e}") from e


def delete_account(user_id: int) -> bool:
    """Permanently delete user and all their data (cascades via FK)."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE id=%s", (user_id,))
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("delete_account failed: %s", e)
        return False


def get_user_categories(user_id: int, defaults: list[str]) -> list[str]:
    """Return custom categories for user, or defaults if none set."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT category_name FROM custom_categories WHERE user_id=%s", (user_id,)
            )
            cats = [r[0] for r in cursor.fetchall()]
            cursor.close()
        return cats if cats else defaults
    except Exception as e:
        logger.error("get_user_categories failed: %s", e)
        return defaults


def add_custom_category(user_id: int, category_name: str) -> bool:
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO custom_categories (user_id, category_name) VALUES (%s, %s)",
                (user_id, category_name),
            )
            conn.commit()
            cursor.close()
        return True
    except Exception as e:
        logger.error("add_custom_category failed: %s", e)
        return False
