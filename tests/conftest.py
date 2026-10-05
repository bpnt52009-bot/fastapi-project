"""Fixture กลางสำหรับเทสต์: แยกฐานข้อมูลและตั้งค่าความปลอดภัยให้เร็ว"""

import time

import pytest
from fastapi.testclient import TestClient

from app import auth, db
from app.config import settings
from app.main import app
from app.security import hash_password

TEST_ADMIN = ("Admin", "123456")
TEST_OTHER = ("Other", "other-pass-456")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "test.db")
    monkeypatch.setattr(settings, "password_rounds", 1_000)
    monkeypatch.setattr(settings, "secret_key", "test-secret-key-0123456789-0123456789")
    monkeypatch.setattr(settings, "session_cookie_secure", False)
    monkeypatch.setattr(settings, "login_max_attempts", 5)
    monkeypatch.setattr(settings, "login_window_seconds", 300)
    monkeypatch.setattr(settings, "login_lockout_seconds", 900)

    db.reset_db_cache()
    db.init_db()

    auth.throttle = auth.LoginThrottle(
        max_attempts=settings.login_max_attempts,
        window=settings.login_window_seconds,
        lockout=settings.login_lockout_seconds,
    )

    yield

    db.reset_db_cache()


@pytest.fixture
def make_client():
    """สร้าง TestClient ใหม่ทุกครั้ง เพื่อไม่ให้ cookie jar ปนกันระหว่างเทสต์"""
    clients: list[TestClient] = []

    def _make() -> TestClient:
        client = TestClient(app)
        clients.append(client)
        return client

    yield _make

    for client in clients:
        client.close()


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture
def make_user():
    def _make(username: str, password: str, role: str = "user") -> None:
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT (username) DO UPDATE SET"
                "   password_hash = excluded.password_hash",
                (
                    username,
                    hash_password(password, rounds=1_000),
                    role,
                    int(time.time()),
                ),
            )

    return _make


@pytest.fixture
def login_as(make_client, make_user):
    """สร้างผู้ใช้ (ถ้ายังไม่มี) แล้วคืน TestClient ที่ล็อกอินแล้วคนละตัวกับอื่น"""

    def _login(username: str, password: str) -> TestClient:
        make_user(username, password)
        client = make_client()
        response = client.post(
            "/login", json={"username": username, "password": password}
        )
        assert response.status_code == 200, response.text
        return client

    return _login


@pytest.fixture
def admin_client(login_as):
    return login_as(*TEST_ADMIN)


@pytest.fixture
def other_client(login_as):
    return login_as(*TEST_OTHER)
