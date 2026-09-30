"""Application settings, loaded from environment variables / .env."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Cyber-sec Project API"

    # ไม่บังคับที่นี่: ถ้าไม่ตั้งจะให้ระบบสร้างค่าสุ่มแล้วบันทึกลงฐานข้อมูล
    # ทำให้ session ไม่หลุดทุกครั้งที่ restart แต่ยังตั้งผ่าน env ได้
    # เวลาขึ้น production ควรตั้งค่านี้เองเสมอ
    secret_key: str | None = Field(default=None, min_length=32)

    session_ttl_seconds: int = Field(default=8 * 60 * 60, ge=60)
    session_cookie_name: str = "session"
    # False ตอน dev ที่รันบน http://localhost, True เมื่อขึ้น production ผ่าน https
    session_cookie_secure: bool = False

    login_max_attempts: int = Field(default=5, ge=1)
    login_window_seconds: int = Field(default=5 * 60, ge=1)
    login_lockout_seconds: int = Field(default=15 * 60, ge=1)

    password_rounds: int = Field(default=600_000, ge=10_000)

    admin_username: str = "Admin"
    # ค่าเริ่มต้นสำหรับ dev เท่านั้น ระบบจะเตือนตอน startup ถ้ายังใช้ค่านี้อยู่
    admin_password: str = "123456"  # noqa: S105

    database_path: Path = Field(default=PROJECT_DIR / "orders.db")
    sqlite_timeout_seconds: float = Field(default=10.0, gt=0)

    orders_default_limit: int = Field(default=50, ge=1, le=200)
    orders_max_limit: int = Field(default=200, ge=1, le=1000)

    @field_validator("secret_key", mode="before")
    @classmethod
    def _blank_secret_key_means_unset(cls, value: object) -> object:
        """ค่าว่างใน .env (แบบที่ .env.example ให้มา) = ยังไม่ได้ตั้ง ให้ระบบสร้างเอง"""
        if isinstance(value, str) and not value.strip():
            return None
        return value


settings = Settings()
