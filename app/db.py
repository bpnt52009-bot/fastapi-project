"""SQLite access layer: schema, migrations, connection lifecycle."""

import secrets
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from logging import getLogger

from app.config import settings

logger = getLogger(__name__)

_lock = threading.Lock()
_initialised = False

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_secret (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    created_at    INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT    PRIMARY KEY,
    username   TEXT    NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions (expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_username ON sessions (username);

CREATE TABLE IF NOT EXISTS orders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      TEXT    NOT NULL,
    items        TEXT    NOT NULL,
    total_price  INTEGER NOT NULL,
    status       TEXT    NOT NULL,
    created_at   INTEGER NOT NULL,
    updated_at   INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_orders_user       ON orders (user_id);
CREATE INDEX IF NOT EXISTS idx_orders_user_state ON orders (user_id, status);
"""

LEGACY_ORDERS_COLUMNS = {
    "id",
    "user_id",
    "items",
    "total_price",
    "status",
}


def _open() -> sqlite3.Connection:
    """เปิด connection ดิบ โดยไม่แตะ schema (ใช้ใน init_db เพื่อเลี่ยงการเรียกซ้ำ)"""
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        settings.database_path,
        timeout=settings.sqlite_timeout_seconds,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """เปิด connection แล้ว commit/rollback/close ให้อัตโนมัติเสมอ

    ตรวจให้แน่ใจว่า schema พร้อมก่อนเสมอ กันเคสถูกเรียกนอก lifecycle ของแอป
    """
    init_db()
    conn = _open()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _migrate_legacy_orders(conn: sqlite3.Connection) -> None:
    """ย้ายตาราง orders เวอร์ชันแรก (total_price เป็น REAL) ไปเก็บไว้เป็น orders_legacy_v1"""
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='orders'"
    ).fetchone()
    if existing is None:
        return

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(orders)")}
    if columns == LEGACY_ORDERS_COLUMNS:
        conn.execute("ALTER TABLE orders RENAME TO orders_legacy_v1")


def _resolve_secret_key(conn: sqlite3.Connection) -> str:
    """ใช้ค่าจาก env ถ้ามี ไม่งั้นอ่าน/สร้างค่าถาวรไว้ในฐานข้อมูล (ไม่ให้ session หลุดทุกครั้งที่ restart)"""
    if settings.secret_key:
        return settings.secret_key

    row = conn.execute(
        "SELECT value FROM app_secret WHERE key = 'secret_key'"
    ).fetchone()
    if row:
        settings.secret_key = row["value"]
        return row["value"]

    value = secrets.token_urlsafe(48)
    conn.execute(
        "INSERT INTO app_secret (key, value) VALUES ('secret_key', ?)", (value,)
    )
    settings.secret_key = value
    return value


def _bootstrap_admin(conn: sqlite3.Connection) -> None:
    """สร้างบัญชีผู้ดูแลระบบจากค่าใน env เสมอ เพื่อให้เปลี่ยนรหัสผ่านผ่าน env แล้วมีผล"""
    from app.security import hash_password

    if settings.admin_password == "123456":  # noqa: S105
        logger.warning(
            "ADMIN_PASSWORD ยังเป็นค่าเริ่มต้น '123456' — กรุณาตั้งค่าใน .env ก่อนใช้งานจริง"
        )

    conn.execute(
        """
        INSERT INTO users (username, password_hash, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT (username) DO UPDATE SET password_hash = excluded.password_hash
        """,
        (
            settings.admin_username,
            hash_password(settings.admin_password),
            int(time.time()),
        ),
    )


def init_db() -> None:
    """สร้าง/อัปเดตโครงสร้างฐานข้อมูล เรียกซ้ำได้โดยไม่ทำงานเพิ่ม (idempotent)"""
    global _initialised
    with _lock:
        if _initialised:
            return
        conn = _open()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            _migrate_legacy_orders(conn)
            conn.executescript(SCHEMA)
            _resolve_secret_key(conn)
            _bootstrap_admin(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        _initialised = True


def reset_db_cache() -> None:
    """ใช้ในเทสต์เพื่อบังคับให้ init_db ทำงานใหม่"""
    global _initialised
    with _lock:
        _initialised = False
