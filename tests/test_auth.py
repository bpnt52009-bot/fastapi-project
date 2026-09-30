from app.config import settings
from app.db import get_conn

TEST_ADMIN = ("Admin", "123456")
TEST_OTHER = ("Other", "other-pass-456")


def login(client, username, password):
    return client.post("/login", json={"username": username, "password": password})


class TestLogin:
    def test_success_sets_httponly_cookie(self, client):
        response = login(client, *TEST_ADMIN)
        assert response.status_code == 200
        header = response.headers["set-cookie"]
        assert "HttpOnly" in header
        assert "samesite=lax" in header.lower()
        assert "session=" in header

    def test_wrong_password_is_401(self, client):
        assert login(client, TEST_ADMIN[0], "nope").status_code == 401

    def test_unknown_user_is_401(self, client):
        assert login(client, "ghost", "whatever").status_code == 401

    def test_unknown_user_and_wrong_password_have_same_detail(self, client):
        unknown = login(client, "ghost", "whatever")
        wrong = login(client, TEST_ADMIN[0], "nope")
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json()["detail"] == wrong.json()["detail"]

    def test_cookie_secure_flag_follows_settings(self, client, monkeypatch):
        monkeypatch.setattr(settings, "session_cookie_secure", True)
        header = login(client, *TEST_ADMIN).headers["set-cookie"]
        assert "secure" in header.lower()

    def test_login_is_locked_out_after_too_many_failures(self, client):
        for _ in range(settings.login_max_attempts):
            assert login(client, TEST_ADMIN[0], "nope").status_code == 401
        blocked = login(client, TEST_ADMIN[0], "nope")
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers

    def test_lockout_does_not_block_other_usernames(self, client, make_user):
        make_user(*TEST_OTHER)
        for _ in range(settings.login_max_attempts):
            login(client, TEST_ADMIN[0], "nope")
        assert login(client, *TEST_ADMIN).status_code == 429
        assert login(client, *TEST_OTHER).status_code == 200


class TestSession:
    def test_me_requires_login(self, client):
        assert client.get("/me").status_code == 401

    def test_me_returns_username(self, admin_client):
        assert admin_client.get("/me").json() == {"user": "Admin"}

    def test_logout_revokes_the_token(self, client):
        login(client, *TEST_ADMIN)
        cookie = client.cookies.get("session")
        assert cookie

        assert client.post("/logout").status_code == 200
        assert client.get("/me").status_code == 401

        # token เดิมถูกลบออกจากฐานข้อมูลแล้ว แม้จะยังอยู่ในเครื่องผู้ใช้ก็ใช้ไม่ได้
        client.cookies.clear()
        client.cookies.set("session", cookie)
        assert client.get("/me").status_code == 401

    def test_tampered_cookie_is_rejected(self, admin_client):
        cookie = admin_client.cookies.get("session")
        flipped = ("aa" if not cookie.endswith("aa") else "bb")
        admin_client.cookies.set("session", cookie[:-2] + flipped)
        assert admin_client.get("/me").status_code == 401

    def test_forged_cookie_is_rejected(self, client):
        client.cookies.set("session", "forged-token.deadbeef")
        assert client.get("/me").status_code == 401

    def test_expired_session_is_rejected(self, client):
        login(client, *TEST_ADMIN)
        assert client.get("/me").status_code == 200

        with get_conn() as conn:
            conn.execute("UPDATE sessions SET expires_at = 1")

        assert client.get("/me").status_code == 401

    def test_ui_redirects_to_login_when_anonymous(self, client):
        response = client.get("/ui", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_ui_serves_page_when_logged_in(self, admin_client):
        response = admin_client.get("/ui")
        assert response.status_code == 200
        assert "Cyber-sec Project" in response.text

    def test_login_page_is_public(self, client):
        response = client.get("/login")
        assert response.status_code == 200
        assert "login-form" in response.text


class TestSecurityHeaders:
    def test_headers_present(self, client):
        headers = client.get("/").headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "no-referrer"


class TestHealth:
    def test_health_is_public(self, client):
        assert client.get("/health").json()["status"] == "ok"


class TestSecretKeyBootstrap:
    def test_login_works_without_lifespan_or_env_secret(self, tmp_path, monkeypatch):
        """ต้องไม่ crash แม้ secret_key ยังเป็น None และไม่ได้รัน lifespan"""
        from fastapi.testclient import TestClient

        from app import db
        from app.config import settings
        from app.main import app

        monkeypatch.setattr(settings, "database_path", tmp_path / "bootstrap.db")
        monkeypatch.setattr(settings, "secret_key", None)
        monkeypatch.setattr(settings, "password_rounds", 1_000)
        db.reset_db_cache()

        client = TestClient(app)  # ไม่ใช้ with -> lifespan ไม่ทำงาน
        try:
            assert client.post(
                "/login", json={"username": "Admin", "password": "123456"}
            ).status_code == 200
            assert settings.secret_key, "ระบบควรสร้าง secret key ให้อัตโนมัติ"
        finally:
            client.close()
            db.reset_db_cache()

    def test_generated_key_is_persisted_across_restarts(self, tmp_path, monkeypatch):
        from app import db
        from app.config import settings

        monkeypatch.setattr(settings, "database_path", tmp_path / "persist.db")
        monkeypatch.setattr(settings, "password_rounds", 1_000)

        monkeypatch.setattr(settings, "secret_key", None)
        db.reset_db_cache()
        db.init_db()
        first = settings.secret_key

        monkeypatch.setattr(settings, "secret_key", None)
        db.reset_db_cache()
        db.init_db()
        assert settings.secret_key == first
        db.reset_db_cache()
