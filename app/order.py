"""จัดการคำสั่งซื้อ: เงินใช้ Decimal, สถานะต้องเป็นค่าที่กำหนด, ทุก query ผูกกับเจ้าของเสมอ"""

import json
import time
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.auth import require_user
from app.db import get_conn
from app.money import to_cents, to_decimal

router = APIRouter(prefix="/orders", tags=["Orders"])


class OrderStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    SHIPPED = "shipped"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


# เส้นทางของสถานะที่อนุญาตให้เปลี่ยนได้ (กันการย้อนสถานะหรือเด้งสุ่ม ๆ)
ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.COMPLETED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}


EXAMPLE_ITEM = {"item_name": "เมาส์", "quantity": 2, "price": "499.00"}


class OrderItem(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": EXAMPLE_ITEM})

    item_name: str = Field(..., min_length=1, max_length=200, description="ชื่อสินค้า")
    quantity: int = Field(..., gt=0, le=10_000, description="จำนวนต้องมากกว่า 0")
    price: Decimal = Field(
        ..., ge=0, max_digits=12, decimal_places=2, description="ราคาต่อหน่วย"
    )

    @field_serializer("price")
    def _serialize_price(self, value: Decimal) -> float:
        return float(value)

    def to_storage(self) -> dict[str, object]:
        return {
            "item_name": self.item_name,
            "quantity": self.quantity,
            "price": format(self.price, "f"),
        }


class OrderCreate(BaseModel):
    items: list[OrderItem] = Field(
        ..., min_length=1, max_length=100, description="ต้องมีสินค้าอย่างน้อย 1 รายการ"
    )


class OrderStatusUpdate(BaseModel):
    status: OrderStatus = Field(..., description="สถานะใหม่ของคำสั่งซื้อ")


class OrderResponse(BaseModel):
    id: int
    user_id: str
    items: list[OrderItem]
    total_price: Decimal
    status: OrderStatus
    created_at: int
    updated_at: int

    @field_serializer("total_price")
    def _serialize_total(self, value: Decimal) -> float:
        return float(value)


class OrderPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[OrderResponse]


OrderId = Annotated[int, Path(gt=0, description="เลขออเดอร์")]
Limit = Annotated[int, Query(ge=1, le=1000, description="จำนวนรายการต่อหน้า")]
Offset = Annotated[int, Query(ge=0, description="ข้ามไปกี่รายการ")]


def _row_to_order(row) -> OrderResponse:
    return OrderResponse(
        id=row["id"],
        user_id=row["user_id"],
        items=[OrderItem(**item) for item in json.loads(row["items"])],
        total_price=to_decimal(row["total_price"]),
        status=OrderStatus(row["status"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _fetch_owned_order(conn, order_id: int, user_name: str):
    return conn.execute(
        "SELECT id, user_id, items, total_price, status, created_at, updated_at"
        " FROM orders WHERE id = ? AND user_id = ?",
        (order_id, user_name),
    ).fetchone()


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="ไม่พบรายการคำสั่งซื้อนี้ หรือคุณไม่มีสิทธิ์เข้าถึง",
    )


# ลงทะเบียนทั้งแบบมีและไม่มี slash ท้าย เพื่อไม่ให้ client ต้องเจอ 307 redirect
@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
@router.post(
    "/",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_order(payload: OrderCreate, user_name: str = Depends(require_user)):
    total = sum((to_cents(item.price) * item.quantity for item in payload.items), 0)
    items_json = json.dumps([item.to_storage() for item in payload.items], ensure_ascii=False)
    now = int(time.time())

    with get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO orders (user_id, items, total_price, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user_name, items_json, total, OrderStatus.PENDING.value, now, now),
        )
        new_id = cursor.lastrowid
        row = _fetch_owned_order(conn, new_id, user_name)

    return _row_to_order(row)


@router.get("", response_model=OrderPage)
@router.get("/", response_model=OrderPage, include_in_schema=False)
def list_orders(
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    limit: Limit = 50,
    offset: Offset = 0,
    user_name: str = Depends(require_user),
):
    with get_conn() as conn:
        if status_filter is None:
            total = conn.execute(
                "SELECT COUNT(*) FROM orders WHERE user_id = ?", (user_name,)
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT id, user_id, items, total_price, status, created_at, updated_at"
                " FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                (user_name, limit, offset),
            ).fetchall()
        else:
            total = conn.execute(
                "SELECT COUNT(*) FROM orders WHERE user_id = ? AND status = ?",
                (user_name, status_filter.value),
            ).fetchone()[0]
            rows = conn.execute(
                "SELECT id, user_id, items, total_price, status, created_at, updated_at"
                " FROM orders WHERE user_id = ? AND status = ?"
                " ORDER BY id DESC LIMIT ? OFFSET ?",
                (user_name, status_filter.value, limit, offset),
            ).fetchall()

    return OrderPage(
        total=total,
        limit=limit,
        offset=offset,
        items=[_row_to_order(row) for row in rows],
    )


@router.get("/{order_id}", response_model=OrderResponse)
def get_order_by_id(order_id: OrderId, user_name: str = Depends(require_user)):
    with get_conn() as conn:
        row = _fetch_owned_order(conn, order_id, user_name)
    if row is None:
        raise _not_found()
    return _row_to_order(row)


@router.patch("/{order_id}/status", response_model=OrderResponse)
def update_order_status(
    order_id: OrderId,
    payload: OrderStatusUpdate,
    user_name: str = Depends(require_user),
):
    with get_conn() as conn:
        row = _fetch_owned_order(conn, order_id, user_name)
        if row is None:
            raise _not_found()

        current = OrderStatus(row["status"])
        if payload.status not in ALLOWED_TRANSITIONS[current]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"เปลี่ยนสถานะจาก '{current.value}' ไปเป็น '{payload.status.value}' ไม่ได้"
                ),
            )

        # WHERE ยังผูก user_id ไว้ด้วย เพื่อกัน race ระหว่าง SELECT กับ UPDATE
        conn.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (payload.status.value, int(time.time()), order_id, user_name),
        )
        updated = _fetch_owned_order(conn, order_id, user_name)

    return _row_to_order(updated)


@router.delete("/{order_id}", status_code=status.HTTP_200_OK)
def cancel_order(order_id: OrderId, user_name: str = Depends(require_user)):
    with get_conn() as conn:
        row = _fetch_owned_order(conn, order_id, user_name)
        if row is None:
            raise _not_found()

        order = _row_to_order(row)
        # WHERE ผูก user_id ไว้เหมือนกัน
        conn.execute(
            "DELETE FROM orders WHERE id = ? AND user_id = ?", (order_id, user_name)
        )

    return {"message": f"ยกเลิกคำสั่งซื้อ ID {order_id} เรียบร้อยแล้ว", "order": order}
