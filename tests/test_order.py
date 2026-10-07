import pytest

DEFAULT_ITEM = {"item_name": "เมาส์", "quantity": 2, "price": "499.00"}


def create_order(client, items=None, owner=None):
    """สร้างออเดอร์ผ่านผู้ดูแลระบบ ถ้าระบุ owner จะผูกออเดอร์ให้เป็นของผู้ใช้คนนั้น"""
    body = {"items": items or [DEFAULT_ITEM]}
    if owner is not None:
        body["user_id"] = owner
    return client.post("/orders", json=body)


class TestAuthz:
    def test_order_routes_require_login(self, client):
        body = {"items": [DEFAULT_ITEM]}
        assert client.get("/orders").status_code == 401
        assert client.post("/orders", json=body).status_code == 401
        assert client.get("/orders/1").status_code == 401
        assert client.patch("/orders/1/status", json={"status": "paid"}).status_code == 401
        assert client.delete("/orders/1").status_code == 401

    def test_users_requires_login(self, client):
        assert client.get("/users").status_code == 401


class TestRouting:
    @pytest.mark.parametrize("path", ["/orders", "/orders/", "/users", "/users/"])
    def test_collection_routes_do_not_redirect(self, client, path):
        response = client.get(path, follow_redirects=False)
        assert response.status_code != 307

    @pytest.mark.parametrize("path", ["/orders", "/orders/"])
    def test_create_order_does_not_redirect(self, admin_client, path):
        response = admin_client.post(
            path, json={"items": [DEFAULT_ITEM]}, follow_redirects=False
        )
        assert response.status_code == 201


class TestCreateOrder:
    def test_creates_order(self, admin_client):
        response = create_order(admin_client)
        assert response.status_code == 201
        body = response.json()
        assert body["status"] == "pending"
        assert body["user_id"] == "Admin"
        assert body["total_price"] == 998.0
        assert body["items"] == [
            {"item_name": "เมาส์", "quantity": 2, "price": 499.0}
        ]

    def test_total_uses_decimal_not_float(self, admin_client):
        response = create_order(
            admin_client,
            [
                {"item_name": "a", "quantity": 1, "price": "0.10"},
                {"item_name": "b", "quantity": 1, "price": "0.20"},
            ],
        )
        assert response.json()["total_price"] == 0.3

    def test_accepts_price_as_json_number(self, admin_client):
        response = create_order(
            admin_client, [{"item_name": "a", "quantity": 1, "price": 0.1}]
        )
        assert response.status_code == 201
        assert response.json()["total_price"] == 0.1

    def test_rejects_price_with_more_than_two_decimals(self, admin_client):
        response = create_order(
            admin_client, [{"item_name": "a", "quantity": 1, "price": 10.005}]
        )
        assert response.status_code == 422

    def test_rejects_empty_items(self, admin_client):
        assert admin_client.post("/orders", json={"items": []}).status_code == 422

    def test_rejects_zero_quantity(self, admin_client):
        assert create_order(
            admin_client, [{"item_name": "a", "quantity": 0, "price": "1.00"}]
        ).status_code == 422

    def test_rejects_negative_price(self, admin_client):
        assert create_order(
            admin_client, [{"item_name": "a", "quantity": 1, "price": "-1.00"}]
        ).status_code == 422

    def test_rejects_blank_item_name(self, admin_client):
        assert create_order(
            admin_client, [{"item_name": "", "quantity": 1, "price": "1.00"}]
        ).status_code == 422


class TestReadOrders:
    def test_list_is_empty_initially(self, admin_client):
        assert admin_client.get("/orders").json() == {
            "total": 0,
            "limit": 50,
            "offset": 0,
            "items": [],
        }

    def test_get_by_id(self, admin_client):
        order_id = create_order(admin_client).json()["id"]
        assert admin_client.get(f"/orders/{order_id}").json()["id"] == order_id

    def test_get_missing_order_is_404(self, admin_client):
        assert admin_client.get("/orders/9999").status_code == 404

    def test_get_non_numeric_id_is_422(self, admin_client):
        assert admin_client.get("/orders/abc").status_code == 422

    def test_filter_by_status(self, admin_client):
        order_id = create_order(admin_client).json()["id"]
        admin_client.patch(f"/orders/{order_id}/status", json={"status": "paid"})

        assert admin_client.get("/orders", params={"status": "pending"}).json()["total"] == 0
        assert admin_client.get("/orders", params={"status": "paid"}).json()["total"] == 1

    def test_invalid_status_filter_is_422(self, admin_client):
        response = admin_client.get("/orders", params={"status": "bogus"})
        assert response.status_code == 422

    def test_pagination(self, admin_client):
        for _ in range(5):
            create_order(admin_client)

        first = admin_client.get("/orders", params={"limit": 2, "offset": 0}).json()
        second = admin_client.get("/orders", params={"limit": 2, "offset": 2}).json()

        assert first["total"] == second["total"] == 5
        assert len(first["items"]) == len(second["items"]) == 2
        assert {o["id"] for o in first["items"]}.isdisjoint(
            {o["id"] for o in second["items"]}
        )

    def test_limit_above_maximum_is_422(self, admin_client):
        assert admin_client.get("/orders", params={"limit": 100_000}).status_code == 422


class TestStatusUpdate:
    def test_valid_transition(self, admin_client):
        order_id = create_order(admin_client).json()["id"]
        response = admin_client.patch(
            f"/orders/{order_id}/status", json={"status": "paid"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "paid"

    def test_invalid_transition_is_409(self, admin_client):
        order_id = create_order(admin_client).json()["id"]
        admin_client.patch(f"/orders/{order_id}/status", json={"status": "paid"})
        response = admin_client.patch(
            f"/orders/{order_id}/status", json={"status": "pending"}
        )
        assert response.status_code == 409

    def test_completed_is_terminal(self, admin_client):
        order_id = create_order(admin_client).json()["id"]
        for step in ("paid", "shipped", "completed"):
            admin_client.patch(f"/orders/{order_id}/status", json={"status": step})
        response = admin_client.patch(
            f"/orders/{order_id}/status", json={"status": "cancelled"}
        )
        assert response.status_code == 409

    def test_cancelled_is_terminal(self, admin_client):
        order_id = create_order(admin_client).json()["id"]
        admin_client.patch(f"/orders/{order_id}/status", json={"status": "cancelled"})
        response = admin_client.patch(
            f"/orders/{order_id}/status", json={"status": "paid"}
        )
        assert response.status_code == 409

    def test_unknown_status_is_422(self, admin_client):
        order_id = create_order(admin_client).json()["id"]
        response = admin_client.patch(
            f"/orders/{order_id}/status", json={"status": "TOTALLY_BOGUS_VALUE"}
        )
        assert response.status_code == 422

    def test_missing_order_is_404(self, admin_client):
        assert (
            admin_client.patch("/orders/9999/status", json={"status": "paid"}).status_code
            == 404
        )


class TestDelete:
    def test_deletes_order(self, admin_client):
        order_id = create_order(admin_client).json()["id"]
        assert admin_client.delete(f"/orders/{order_id}").status_code == 200
        assert admin_client.get(f"/orders/{order_id}").status_code == 404

    def test_delete_missing_is_404(self, admin_client):
        assert admin_client.delete("/orders/9999").status_code == 404


class TestOwnershipIsolation:
    def test_user_sees_only_own_but_admin_sees_everything(self, admin_client, other_client):
        mine = create_order(admin_client).json()["id"]
        theirs = create_order(admin_client, owner="Other").json()["id"]

        seen_by_other = [
            o["id"] for o in other_client.get("/orders").json()["items"]
        ]
        assert seen_by_other == [theirs]

        seen_by_admin = [o["id"] for o in admin_client.get("/orders").json()["items"]]
        assert set(seen_by_admin) == {mine, theirs}

    def test_user_can_create_own_order_but_not_for_others(self, other_client):
        # ผู้ใช้ทั่วไปสร้างออเดอร์ของตัวเองได้
        response = other_client.post("/orders", json={"items": [DEFAULT_ITEM]})
        assert response.status_code == 201
        assert response.json()["status"] == "pending"
        assert response.json()["user_id"] == "Other"

        # แต่บังคับระบุเจ้าของเป็นคนอื่นไม่ได้ กันการสร้างออเดอร์แทนคนอื่น
        response = other_client.post(
            "/orders", json={"user_id": "Admin", "items": [DEFAULT_ITEM]}
        )
        assert response.status_code == 403

    def test_user_cannot_change_status_or_delete(self, admin_client, other_client):
        order_id = create_order(admin_client, owner="Other").json()["id"]

        # ผู้ใช้ทั่วไปเปลี่ยนสถานะ / ลบออเดอร์ไม่ได้
        assert (
            other_client.patch(f"/orders/{order_id}/status", json={"status": "paid"})
            .status_code
            == 403
        )
        assert other_client.delete(f"/orders/{order_id}").status_code == 403

        # แต่ยังอ่านออเดอร์ของตัวเองได้
        assert other_client.get(f"/orders/{order_id}").status_code == 200

    def test_user_cannot_read_or_change_a_foreign_order(self, admin_client, other_client):
        order_id = create_order(admin_client).json()["id"]

        assert other_client.get(f"/orders/{order_id}").status_code == 404

        # ของเจ้าของเดิมยังอยู่ครบ ไม่ถูกแตะต้อง
        assert admin_client.get(f"/orders/{order_id}").status_code == 200
        assert admin_client.get(f"/orders/{order_id}").json()["status"] == "pending"

    def test_status_filter_does_not_leak_counts(self, admin_client, other_client):
        create_order(admin_client)
        create_order(admin_client)
        create_order(admin_client, owner="Other")

        assert admin_client.get("/orders", params={"status": "pending"}).json()["total"] == 3
        assert other_client.get("/orders", params={"status": "pending"}).json()["total"] == 1

    def test_non_admin_cannot_filter_by_other_owner(self, other_client):
        assert other_client.get("/orders", params={"user": "Admin"}).status_code == 403

    def test_admin_can_filter_by_owner(self, admin_client, other_client):
        mine = create_order(admin_client).json()["id"]
        theirs = create_order(admin_client, owner="Other").json()["id"]

        body = admin_client.get("/orders", params={"user": "Other"}).json()
        assert [o["id"] for o in body["items"]] == [theirs]
        assert body["total"] == 1
        assert mine not in [o["id"] for o in body["items"]]

    def test_create_order_rejects_unknown_owner(self, admin_client):
        response = create_order(admin_client, owner="ไม่มีผู้ใช้นี้")
        assert response.status_code == 404
        assert "ไม่พบผู้ใช้" in response.json()["detail"]


class TestUsers:
    def test_list_users_requires_login(self, client):
        assert client.get("/users").status_code == 401

    def test_list_users(self, admin_client):
        body = admin_client.get("/users").json()
        assert {"id", "name", "role", "created_at"} == set(body[0])
        assert "Admin" in [u["name"] for u in body]

    def test_env_admin_has_admin_role(self, admin_client):
        by_name = {u["name"]: u for u in admin_client.get("/users").json()}
        assert by_name["Admin"]["role"] == "admin"
