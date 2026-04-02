# db/connection.py — Connection pool + DB config management
#
# 🏛️ Architect: This module owns ALL database connectivity.
#   - Single pool shared across the entire app (no per-request connections)
#   - Config loaded once from JSON, saved back on change
#   - get_connection() is the ONLY way to get a DB connection (cursor ops)
#   - get_engine() returns a SQLAlchemy engine for pandas read_sql() calls
#
# 💎 Dev: SQLAlchemy engine added alongside the existing mysql.connector pool.
#   pandas requires SQLAlchemy for read_sql() — raw DBAPI2 connections trigger
#   UserWarning and may break in future pandas versions. All cursor-based ops
#   (INSERT/UPDATE/DELETE) still use the mysql.connector pool unchanged.

import json
import logging
import os
from contextlib import contextmanager

import mysql.connector
from mysql.connector import pooling, Error as MySQLError

from config import (
    DB_CONFIG_FILE,
    DB_DEFAULTS,
    DB_POOL_NAME,
    DB_POOL_SIZE,
    DB_CONNECTION_TIMEOUT,
)

logger = logging.getLogger(__name__)

# Module-level pool — initialized once, shared everywhere
_pool: pooling.MySQLConnectionPool | None = None

# SQLAlchemy engine — for pandas read_sql() calls
_engine = None


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_db_config() -> dict:
    """Load DB config from JSON file, falling back to defaults."""
    if os.path.exists(DB_CONFIG_FILE):
        try:
            with open(DB_CONFIG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not read db config file: %s — using defaults", e)
    return dict(DB_DEFAULTS)


def save_db_config(config: dict) -> None:
    """Persist DB config to JSON file."""
    try:
        with open(DB_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        logger.info("DB config saved.")
    except OSError as e:
        logger.error("Failed to save DB config: %s", e)


# ---------------------------------------------------------------------------
# Pool management
# ---------------------------------------------------------------------------

def init_pool(config: dict | None = None) -> None:
    """
    Initialize (or re-initialize) the connection pool and SQLAlchemy engine.
    Call once at startup, and again after DB settings change.
    """
    global _pool, _engine
    cfg = config or load_db_config()

    # Tear down existing pool gracefully
    if _pool is not None:
        logger.info("Reinitializing DB connection pool...")
        _pool = None

    # Tear down existing engine
    if _engine is not None:
        try:
            _engine.dispose()
        except Exception:
            pass
        _engine = None

    try:
        _pool = pooling.MySQLConnectionPool(
            pool_name=DB_POOL_NAME,
            pool_size=DB_POOL_SIZE,
            pool_reset_session=True,
            host=cfg["host"],
            port=int(cfg.get("port", 3306)),
            user=cfg["user"],
            password=cfg["password"],
            database=cfg["database"],
            connection_timeout=DB_CONNECTION_TIMEOUT,
        )
        logger.info("DB pool initialized (size=%d, host=%s)", DB_POOL_SIZE, cfg["host"])
    except MySQLError as e:
        logger.error("Failed to initialize DB pool: %s", e)
        _pool = None
        raise

    # Build SQLAlchemy engine using pymysql dialect (pandas-compatible)
    try:
        from sqlalchemy import create_engine
        url = (
            f"mysql+pymysql://{cfg['user']}:{cfg['password']}"
            f"@{cfg['host']}:{int(cfg.get('port', 3306))}/{cfg['database']}"
        )
        _engine = create_engine(url, pool_pre_ping=True)
        logger.info("SQLAlchemy engine initialized.")
    except Exception as e:
        logger.warning("SQLAlchemy engine could not be initialized: %s", e)
        _engine = None


def get_engine():
    """
    Return the SQLAlchemy engine for use with pandas read_sql().
    Falls back to None if SQLAlchemy is not available — callers should
    handle this by using get_connection() instead.

    Usage in models:
        engine = get_engine()
        if engine:
            df = pd.read_sql(sql, engine, params=(...))
        else:
            with get_connection() as conn:
                df = pd.read_sql(sql, conn, params=(...))
    """
    return _engine


def is_connected() -> bool:
    """Quick non-blocking check — tries to borrow a connection from the pool."""
    try:
        with get_connection() as conn:
            return conn.is_connected()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Connection context manager — the ONE way to get a cursor-based connection
# ---------------------------------------------------------------------------

@contextmanager
def get_connection():
    """
    Usage:
        with get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(...)

    Automatically returns the connection to the pool on exit.
    Raises RuntimeError if pool is not initialized.
    """
    if _pool is None:
        raise RuntimeError(
            "DB pool is not initialized. Call db.connection.init_pool() at startup."
        )

    conn = None
    try:
        conn = _pool.get_connection()
        yield conn
    except MySQLError as e:
        logger.error("DB error: %s", e)
        raise
    finally:
        if conn is not None:
            try:
                conn.close()  # Returns to pool, does not close TCP connection
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def load_db_config() -> dict:
    """Load DB config from JSON file, falling back to defaults."""
    if os.path.exists(DB_CONFIG_FILE):
        try:
            with open(DB_CONFIG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not read db config file: %s — using defaults", e)
    return dict(DB_DEFAULTS)


def save_db_config(config: dict) -> None:
    """Persist DB config to JSON file."""
    try:
        with open(DB_CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)
        logger.info("DB config saved.")
    except OSError as e:
        logger.error("Failed to save DB config: %s", e)


# ---------------------------------------------------------------------------
# Pool management
# ---------------------------------------------------------------------------

def init_pool(config: dict | None = None) -> None:
    """
    Initialize (or re-initialize) the connection pool.
    Call once at startup, and again after DB settings change.
    """
    global _pool
    cfg = config or load_db_config()

    # Tear down existing pool gracefully
    if _pool is not None:
        logger.info("Reinitializing DB connection pool...")
        _pool = None

    try:
        _pool = pooling.MySQLConnectionPool(
            pool_name=DB_POOL_NAME,
            pool_size=DB_POOL_SIZE,
            pool_reset_session=True,
            host=cfg["host"],
            port=int(cfg.get("port", 3306)),
            user=cfg["user"],
            password=cfg["password"],
            database=cfg["database"],
            connection_timeout=DB_CONNECTION_TIMEOUT,
        )
        logger.info("DB pool initialized (size=%d, host=%s)", DB_POOL_SIZE, cfg["host"])
    except MySQLError as e:
        logger.error("Failed to initialize DB pool: %s", e)
        _pool = None
        raise


def is_connected() -> bool:
    """Quick non-blocking check — tries to borrow a connection from the pool."""
    try:
        with get_connection() as conn:
            return conn.is_connected()
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Connection context manager — the ONE way to get a connection
# ---------------------------------------------------------------------------

@contextmanager
def get_connection():
    """
    Usage:
        with get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute(...)

    Automatically returns the connection to the pool on exit.
    Raises RuntimeError if pool is not initialized.
    """
    if _pool is None:
        raise RuntimeError(
            "DB pool is not initialized. Call db.connection.init_pool() at startup."
        )

    conn = None
    try:
        conn = _pool.get_connection()
        yield conn
    except MySQLError as e:
        logger.error("DB error: %s", e)
        raise
    finally:
        if conn is not None:
            try:
                conn.close()  # Returns to pool, does not close TCP connection
            except Exception:
                pass
