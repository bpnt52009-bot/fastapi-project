"""Password hashing (per-user random salt) and token signing helpers."""

import base64
import hashlib
import hmac
import secrets

from app.config import settings

ALGORITHM = "pbkdf2_sha256"
TOKEN_BYTES = 32


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str, *, rounds: int | None = None) -> str:
    """คืนรหัสผ่านแบบ `pbkdf2_sha256$rounds$salt$hash` โดยสุ่ม salt ใหม่ทุกครั้ง"""
    rounds = rounds or settings.password_rounds
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"{ALGORITHM}${rounds}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """เทียบรหัสผ่านกับ hash ที่เก็บไว้ แบบ constant-time"""
    try:
        algorithm, rounds_text, salt_text, hash_text = encoded.split("$")
        if algorithm != ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), _b64decode(salt_text), int(rounds_text)
        )
    except (AttributeError, TypeError, ValueError):
        return False
    return hmac.compare_digest(digest, _b64decode(hash_text))


def generate_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_fingerprint(token: str) -> str:
    """เอา SHA-256 ของ token ไว้ในฐานข้อมูล เพื่อไม่เก็บ token จริง"""
    return hashlib.sha256(token.encode()).hexdigest()


def get_secret_key() -> str:
    """คืน secret key ที่ใช้งานอยู่ โดยเตรียมฐานข้อมูลให้อัตโนมัติถ้ายังไม่ได้ init

    db.init_db() เป็น idempotent และจะสร้าง + บันทึก key ถาวรไว้ในฐานข้อมูล
    ทำให้ระบบไม่พังแม้ถูกเรียกนอก lifecycle ของแอป
    """
    if settings.secret_key:
        return settings.secret_key

    from app import db  # import ช้า เพื่อเลี่ยง circular import

    db.init_db()
    if not settings.secret_key:
        raise RuntimeError(
            "ยังไม่ได้ตั้ง SECRET_KEY และเตรียมฐานข้อมูลไม่สำเร็จ — "
            "ตรวจสอบว่า DATABASE_PATH ชี้ไปยังโฟลเดอร์ที่เขียนได้"
        )
    return settings.secret_key


def sign(value: str) -> str:
    mac = hmac.new(
        get_secret_key().encode(), value.encode(), hashlib.sha256
    ).hexdigest()
    return f"{value}.{mac}"


def unsign(signed: str) -> str | None:
    value, _, mac = signed.rpartition(".")
    if not value or not settings.secret_key:
        return None
    expected = hmac.new(
        get_secret_key().encode(), value.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    return value
