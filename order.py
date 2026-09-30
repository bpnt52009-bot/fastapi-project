from fastapi import APIRouter, HTTPException, status, Request, Query
from pydantic import BaseModel, Field
from typing import List, Optional
import sqlite3
import json
import auth  # เชื่อมต่อกับระบบล็อกอินของเพื่อน

router = APIRouter(
    prefix="/orders",
    tags=["Orders"]
)

# --- 1. Database Setup (SQLite) ---
DB_NAME = "orders.db"

def init_db():
    """สร้างตาราง orders ใน SQLite หากยังไม่มี"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            items TEXT NOT NULL,
            total_price REAL NOT NULL,
            status TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()

# เรียกสร้างตารางฐานข้อมูลทันทีเมื่อเริ่มต้นไฟล์
init_db()


# --- 2. Schemas (โครงสร้างข้อมูล) ---
class OrderItem(BaseModel):
    item_name: str
    quantity: int = Field(..., gt=0, description="จำนวนต้องมากกว่า 0")
    price: float = Field(..., ge=0, description="ราคาต้องไม่ติดลบ")

class OrderCreate(BaseModel):
    items: List[OrderItem] = Field(..., min_items=1, description="ต้องมีสินค้าอย่างน้อย 1 รายการ")

class OrderStatusUpdate(BaseModel):
    status: str  # เช่น 'pending', 'paid', 'shipped', 'completed', 'cancelled'

class OrderResponse(BaseModel):
    id: int
    user_id: str
    items: List[OrderItem]
    total_price: float
    status: str


# --- Helper Function ---
def get_user_from_auth(request: Request):
    """ตรวจสอบการเข้าสู่ระบบและดึงข้อมูลผู้ใช้"""
    user = auth.current_user(request)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="กรุณาเข้าสู่ระบบก่อนดำเนินการ"
        )
    return user


# --- 3. Endpoints ---

# [POST] สร้างคำสั่งซื้อใหม่ (บันทึกลง SQLite)
@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(order_data: OrderCreate, request: Request):
    current_user = get_user_from_auth(request)
    user_name = current_user.get("username", "user") if isinstance(current_user, dict) else str(current_user)
    
    total = sum(item.price * item.quantity for item in order_data.items)
    items_json = json.dumps([item.model_dump() for item in order_data.items])
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO orders (user_id, items, total_price, status) VALUES (?, ?, ?, ?)",
        (user_name, items_json, total, "pending")
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    
    return {
        "id": new_id,
        "user_id": user_name,
        "items": order_data.items,
        "total_price": total,
        "status": "pending"
    }


# [GET] ดึงรายการออเดอร์ทั้งหมด (รองรับตัวกรอง ?status=pending)
@router.get("/", response_model=List[OrderResponse])
def get_my_orders(request: Request, status_filter: Optional[str] = Query(None, alias="status")):
    current_user = get_user_from_auth(request)
    user_name = current_user.get("username", "user") if isinstance(current_user, dict) else str(current_user)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    if status_filter:
        cursor.execute(
            "SELECT id, user_id, items, total_price, status FROM orders WHERE user_id = ? AND status = ?",
            (user_name, status_filter)
        )
    else:
        cursor.execute(
            "SELECT id, user_id, items, total_price, status FROM orders WHERE user_id = ?",
            (user_name,)
        )
        
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            "id": row[0],
            "user_id": row[1],
            "items": json.loads(row[2]),
            "total_price": row[3],
            "status": row[4]
        }
        for row in rows
    ]


# [GET] ค้นหาออเดอร์ตาม ID
@router.get("/{order_id}", response_model=OrderResponse)
def get_order_by_id(order_id: int, request: Request):
    current_user = get_user_from_auth(request)
    user_name = current_user.get("username", "user") if isinstance(current_user, dict) else str(current_user)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, user_id, items, total_price, status FROM orders WHERE id = ? AND user_id = ?",
        (order_id, user_name)
    )
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="ไม่พบรายการคำสั่งซื้อนี้ หรือคุณไม่มีสิทธิ์เข้าถึง"
        )
        
    return {
        "id": row[0],
        "user_id": row[1],
        "items": json.loads(row[2]),
        "total_price": row[3],
        "status": row[4]
    }


# [PATCH] อัปเดตสถานะออเดอร์
@router.patch("/{order_id}/status", response_model=OrderResponse)
def update_order_status(order_id: int, status_update: OrderStatusUpdate, request: Request):
    current_user = get_user_from_auth(request)
    user_name = current_user.get("username", "user") if isinstance(current_user, dict) else str(current_user)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, user_id, items, total_price, status FROM orders WHERE id = ? AND user_id = ?",
        (order_id, user_name)
    )
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="ไม่พบรายการคำสั่งซื้อนี้"
        )
        
    cursor.execute(
        "UPDATE orders SET status = ? WHERE id = ?",
        (status_update.status, order_id)
    )
    conn.commit()
    conn.close()
    
    return {
        "id": row[0],
        "user_id": row[1],
        "items": json.loads(row[2]),
        "total_price": row[3],
        "status": status_update.status
    }


# [DELETE] ยกเลิกคำสั่งซื้อ
@router.delete("/{order_id}", status_code=status.HTTP_200_OK)
def cancel_order(order_id: int, request: Request):
    current_user = get_user_from_auth(request)
    user_name = current_user.get("username", "user") if isinstance(current_user, dict) else str(current_user)
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, user_id, items, total_price, status FROM orders WHERE id = ? AND user_id = ?",
        (order_id, user_name)
    )
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="ไม่พบรายการคำสั่งซื้อนี้"
        )
        
    cursor.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()
    
    return {
        "message": f"ยกเลิกคำสั่งซื้อ ID {order_id} เรียบร้อยแล้ว",
        "order": {
            "id": row[0],
            "user_id": row[1],
            "items": json.loads(row[2]),
            "total_price": row[3],
            "status": row[4]
        }
    }