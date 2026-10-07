"""จัดการคำสั่งซื้อ: เงินใช้ Decimal, สถานะต้องเป็นค่าที่กำหนด, ทุก query ผูกกับเจ้าของเสมอ

สิทธิ์: user ทั่วไปอ่านได้เฉพาะออเดอร์ของตัวเอง ส่วนการสร้าง/เปลี่ยนสถานะ/ยกเลิก
ทำได้เฉพาะผู้ดูแลระบบ และผู้ดูแลระบบอ่านได้ทุกรายการ
"""

import json
import time
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.auth import is_admin, require_admin, require_user
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
    user_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        description="เจ้าของออเดอร์ ถ้าไม่ระบุจะใช้ชื่อผู้ดูแลระบบ",
    )
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


def _scope_owner(user_name: str, *, admin: bool, owner_filter: str | None) -> str | None:
    """คิดค่า 'เจ้าของ' ที่ใช้บังคับขอบเขตการมองเห็น

    - user ทั่วไป  → บังคับเป็นชื่อตัวเองเสมอ (ไม่เชื่อพารามิเตอร์จาก client)
    - admin + ฟิลเตอร์ → เฉพาะเจ้าของที่เลือก
    - admin ไม่ฟิลเตอร์ → None คือดูได้ทุกคน
    """
    if not admin:
        return user_name
    return owner_filter or None


def _fetch_visible_order(
    conn, order_id: int, user_name: str, *, admin: bool, owner_filter: str | None = None
):
    """ดึงออเดอร์ตาม id โดยบังคับขอบเขตเสมอ: user ทั่วไปเห็นแค่ของตัวเอง admin เห็นทุกคน

    ใช้ named parameter กับ SQL ที่เขียนตายตัวไว้แล้ว จึงไม่มีการต่อสตริงเข้าไปใน query
    """
    owner = _scope_owner(user_name, admin=admin, owner_filter=owner_filter)
    return conn.execute(
        "SELECT id, user_id, items, total_price, status, created_at, updated_at"
        " FROM orders"
        " WHERE id = :id AND (:owner IS NULL OR user_id = :owner)",
        {"id": order_id, "owner": owner},
    ).fetchone()


def _list_visible_orders(
    conn,
    user_name: str,
    *,
    admin: bool,
    status_filter: OrderStatus | None,
    owner_filter: str | None,
    limit: int,
    offset: int,
) -> tuple[int, list]:
    """นับและดึงรายการตามขอบเขตสิทธิ์ คืน (จำนวนทั้งหมด, แถวของหน้านี้)"""
    owner = _scope_owner(user_name, admin=admin, owner_filter=owner_filter)
    state = status_filter.value if status_filter is not None else None
    scope = {"owner": owner, "state": state}

    total = conn.execute(
        "SELECT COUNT(*) FROM orders"
        " WHERE (:owner IS NULL OR user_id = :owner)"
        "   AND (:state IS NULL OR status = :state)",
        scope,
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT id, user_id, items, total_price, status, created_at, updated_at"
        " FROM orders"
        " WHERE (:owner IS NULL OR user_id = :owner)"
        "   AND (:state IS NULL OR status = :state)"
        " ORDER BY id DESC LIMIT :limit OFFSET :offset",
        {**scope, "limit": limit, "offset": offset},
    ).fetchall()
    return total, rows


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
    """สร้างออเดอร์ — ผู้ที่ล็อกอินทุกคนสร้างออเดอร์ของตัวเองได้

    ผู้ดูแลระบบสามารถเลือกเจ้าของออเดอร์ได้ (user_id) แต่ผู้ใช้ทั่วไปถูกบังคับ
    ให้เป็นชื่อตัวเองเสมอ เพราะไม่ควรสร้างออเดอร์แทนคนอื่นได้
    """
    if not is_admin(user_name) and payload.user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ระบุเจ้าของออเดอร์ได้เฉพาะผู้ดูแลระบบเท่านั้น",
        )
    owner = payload.user_id or user_name
    total = sum((to_cents(item.price) * item.quantity for item in payload.items), 0)
    items_json = json.dumps(
        [item.to_storage() for item in payload.items], ensure_ascii=False
    )
    now = int(time.time())

    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (owner,)
        ).fetchone()
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"ไม่พบผู้ใช้ '{owner}'",
            )

        cursor = conn.execute(
            "INSERT INTO orders (user_id, items, total_price, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (owner, items_json, total, OrderStatus.PENDING.value, now, now),
        )
        row = _fetch_visible_order(conn, cursor.lastrowid, user_name, admin=True)

    return _row_to_order(row)


@router.get("", response_model=OrderPage)
@router.get("/", response_model=OrderPage, include_in_schema=False)
def list_orders(
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    user_filter: Annotated[
        str | None,
        Query(
            alias="user",
            min_length=1,
            max_length=64,
            description="กรองตามเจ้าของออเดอร์ (ผู้ดูแลระบบเท่านั้น)",
        ),
    ] = None,
    limit: Limit = 50,
    offset: Offset = 0,
    user_name: str = Depends(require_user),
):
    """รายการออเดอร์ — user ทั่วไปเห็นแค่ของตัวเอง ส่วน admin เห็นทุกคนและกรองด้วย ?user="""
    admin = is_admin(user_name)
    if not admin and user_filter is not None and user_filter != user_name:
        # ไม่ใช่ admin พยายามกรองของคนอื่น — ปฏิเสธชัดเจนแทนที่จะเงียบ ๆ กรองให้เหมือนไม่มีพารามิเตอร์
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="กรองตามเจ้าของออเดอร์ได้เฉพาะผู้ดูแลระบบเท่านั้น",
        )

    with get_conn() as conn:
        total, rows = _list_visible_orders(
            conn,
            user_name,
            admin=admin,
            status_filter=status_filter,
            owner_filter=user_filter if admin else None,
            limit=limit,
            offset=offset,
        )

    return OrderPage(
        total=total,
        limit=limit,
        offset=offset,
        items=[_row_to_order(row) for row in rows],
    )


@router.get("/{order_id}", response_model=OrderResponse)
def get_order_by_id(order_id: OrderId, user_name: str = Depends(require_user)):
    admin = is_admin(user_name)
    with get_conn() as conn:
        row = _fetch_visible_order(conn, order_id, user_name, admin=admin)
    if row is None:
        raise _not_found()
    return _row_to_order(row)


@router.patch("/{order_id}/status", response_model=OrderResponse)
def update_order_status(
    order_id: OrderId,
    payload: OrderStatusUpdate,
    user_name: str = Depends(require_admin),
):
    """เปลี่ยนสถานะ — เฉพาะผู้ดูแลระบบ และต้องเป็นการเปลี่ยนที่กฎอนุญาต"""
    with get_conn() as conn:
        row = _fetch_visible_order(conn, order_id, user_name, admin=True)
        if row is None:
            raise _not_found()

        current = OrderStatus(row["status"])
        if payload.status not in ALLOWED_TRANSITIONS[current]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"เปลี่ยนสถานะจาก '{current.value}' ไปเป็น '{payload.status.value}' ได้ไม่"
                ),
            )

        conn.execute(
            "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (payload.status.value, int(time.time()), order_id),
        )
        updated = _fetch_visible_order(conn, order_id, user_name, admin=True)

    return _row_to_order(updated)


@router.delete("/{order_id}", status_code=status.HTTP_200_OK)
def cancel_order(order_id: OrderId, user_name: str = Depends(require_admin)):
    """ยกเลิก/ลบออเดอร์ — เฉพาะผู้ดูแลระบบ"""
    with get_conn() as conn:
        row = _fetch_visible_order(conn, order_id, user_name, admin=True)
        if row is None:
            raise _not_found()

        order = _row_to_order(row)
        conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))

    return {"message": f"ยกเลิกคำสั่งซื้อ ID {order_id} เรียบร้อยแล้ว", "order": order}
