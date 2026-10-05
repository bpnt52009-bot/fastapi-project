"""เทสต์ส่วนผู้ใช้: สิทธิ์ admin, CRUD, โปรไฟล์ตัวเอง"""

import pytest

TEST_NEW_USER = {"username": "alice", "password": "alice-pass-123", "role": "user"}


def find_user(client, name: str) -> dict:
    return next(u for u in client.get("/users").json() if u["name"] == name)


class TestUsersAuthz:
    def test_collection_requires_login(self, client):
        assert client.get("/users").status_code == 401
        assert client.post("/users", json=TEST_NEW_USER).status_code == 401

    def test_normal_user_is_forbidden(self, other_client):
        assert other_client.get("/users").status_code == 403
        assert other_client.post("/users", json=TEST_NEW_USER).status_code == 403
        assert other_client.get("/users/1").status_code == 403
        assert other_client.patch("/users/1", json={"role": "admin"}).status_code == 403
        assert other_client.delete("/users/1").status_code == 403

    def test_me_is_readable_by_normal_user(self, other_client):
        body = other_client.get("/users/me").json()
        assert body["name"] == "Other"
        assert body["role"] == "user"

    def test_me_requires_login(self, client):
        assert client.get("/users/me").status_code == 401

    def test_me_is_not_confused_with_id_route(self, other_client):
        assert other_client.get("/users/me").json()["id"] > 0


class TestCreateUser:
    def test_admin_can_create(self, admin_client):
        response = admin_client.post("/users", json=TEST_NEW_USER)
        assert response.status_code == 201
        assert response.json()["name"] == "alice"
        assert response.json()["role"] == "user"
        assert find_user(admin_client, "alice")

    def test_created_user_can_login(self, admin_client, make_client):
        admin_client.post("/users", json=TEST_NEW_USER)
        client = make_client()
        assert client.post(
            "/login", json={"username": "alice", "password": TEST_NEW_USER["password"]}
        ).status_code == 200

    def test_role_defaults_to_user(self, admin_client):
        payload = {**TEST_NEW_USER, "username": "bob"}
        payload.pop("role")
        assert admin_client.post("/users", json=payload).json()["role"] == "user"

    def test_duplicate_username_is_409(self, admin_client):
        admin_client.post("/users", json=TEST_NEW_USER)
        assert admin_client.post("/users", json=TEST_NEW_USER).status_code == 409

    def test_admin_can_create_another_admin(self, admin_client):
        payload = {**TEST_NEW_USER, "username": "root2", "role": "admin"}
        assert admin_client.post("/users", json=payload).json()["role"] == "admin"

    @pytest.mark.parametrize(
        "payload",
        [
            {"username": "short", "password": "123"},
            {"username": "", "password": "long-enough-pass"},
            {"username": "   ", "password": "long-enough-pass"},
            {"username": "ok", "password": "long-enough-pass", "role": "superuser"},
        ],
    )
    def test_invalid_payload_is_422(self, admin_client, payload):
        assert admin_client.post("/users", json=payload).status_code == 422

    def test_username_is_trimmed(self, admin_client):
        payload = {**TEST_NEW_USER, "username": "  carol  "}
        assert admin_client.post("/users", json=payload).json()["name"] == "carol"

    def test_password_is_hashed_not_stored(self, admin_client):
        from app.db import get_conn

        admin_client.post("/users", json=TEST_NEW_USER)
        with get_conn() as conn:
            stored = conn.execute(
                "SELECT password_hash FROM users WHERE username = 'alice'"
            ).fetchone()["password_hash"]
        assert stored != TEST_NEW_USER["password"]
        assert stored.startswith("pbkdf2_sha256$")


class TestReadUser:
    def test_get_by_id(self, admin_client):
        created = admin_client.post("/users", json=TEST_NEW_USER).json()
        assert admin_client.get(f"/users/{created['id']}").json() == created

    def test_unknown_id_is_404(self, admin_client):
        assert admin_client.get("/users/9999").status_code == 404

    @pytest.mark.parametrize("user_id", [0, -1])
    def test_invalid_id_is_422(self, admin_client, user_id):
        assert admin_client.get(f"/users/{user_id}").status_code == 422


class TestUpdateUser:
    def test_admin_can_change_role(self, admin_client):
        created = admin_client.post("/users", json=TEST_NEW_USER).json()
        response = admin_client.patch(f"/users/{created['id']}", json={"role": "admin"})
        assert response.json()["role"] == "admin"

    def test_admin_can_rename(self, admin_client):
        created = admin_client.post("/users", json=TEST_NEW_USER).json()
        response = admin_client.patch(
            f"/users/{created['id']}", json={"username": "alice2"}
        )
        assert response.json()["name"] == "alice2"
        assert find_user(admin_client, "alice2")

    def test_rename_to_existing_is_409(self, admin_client, other_client):
        target = find_user(admin_client, "Other")["id"]
        assert admin_client.patch(
            f"/users/{target}", json={"username": "Admin"}
        ).status_code == 409

    def test_rename_to_own_name_is_allowed(self, admin_client, other_client):
        target = find_user(admin_client, "Other")["id"]
        assert admin_client.patch(
            f"/users/{target}", json={"username": "Other"}
        ).status_code == 200

    def test_reset_password_allows_new_login(self, admin_client, make_client):
        admin_client.post("/users", json=TEST_NEW_USER)
        target = find_user(admin_client, "alice")["id"]
        assert admin_client.patch(
            f"/users/{target}", json={"password": "brand-new-pass-9"}
        ).status_code == 200

        client = make_client()
        assert client.post(
            "/login", json={"username": "alice", "password": "brand-new-pass-9"}
        ).status_code == 200

    def test_reset_password_revokes_existing_sessions(
        self, admin_client, other_client, login_as
    ):
        target = find_user(admin_client, "Other")["id"]
        assert other_client.get("/users/me").status_code == 200

        admin_client.patch(f"/users/{target}", json={"password": "changed-pass-1"})

        assert other_client.get("/users/me").status_code == 401
        assert login_as("Other", "changed-pass-1").get("/users/me").status_code == 200

    def test_empty_patch_is_422(self, admin_client):
        assert admin_client.patch("/users/1", json={}).status_code == 422

    def test_weak_password_is_422(self, admin_client):
        assert admin_client.patch("/users/1", json={"password": "abc"}).status_code == 422

    def test_admin_cannot_demote_self(self, admin_client):
        by_name = {u["name"]: u for u in admin_client.get("/users").json()}
        self_id = by_name["Admin"]["id"]
        assert admin_client.patch(
            f"/users/{self_id}", json={"role": "user"}
        ).status_code == 409

    def test_unknown_id_is_404(self, admin_client):
        assert admin_client.patch("/users/9999", json={"role": "user"}).status_code == 404


class TestDeleteUser:
    def test_admin_can_delete(self, admin_client):
        created = admin_client.post("/users", json=TEST_NEW_USER).json()
        assert admin_client.delete(f"/users/{created['id']}").status_code == 200
        assert admin_client.get(f"/users/{created['id']}").status_code == 404

    def test_delete_revokes_sessions(self, admin_client, login_as):
        victim = login_as("victim", "victim-pass-1")
        assert victim.get("/users/me").status_code == 200

        target = find_user(admin_client, "victim")["id"]
        admin_client.delete(f"/users/{target}")

        assert victim.get("/users/me").status_code == 401

    def test_admin_cannot_delete_self(self, admin_client):
        by_name = {u["name"]: u for u in admin_client.get("/users").json()}
        self_id = by_name["Admin"]["id"]
        assert admin_client.delete(f"/users/{self_id}").status_code == 409
        assert admin_client.get("/users/me").status_code == 200

    def test_delete_is_idempotent_after_first_call(self, admin_client):
        created = admin_client.post("/users", json=TEST_NEW_USER).json()
        assert admin_client.delete(f"/users/{created['id']}").status_code == 200
        assert admin_client.delete(f"/users/{created['id']}").status_code == 404

    def test_unknown_id_is_404(self, admin_client):
        assert admin_client.delete("/users/9999").status_code == 404
