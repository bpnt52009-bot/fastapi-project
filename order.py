from fastapi import APIRouter, HTTPException, status, Request
from pydantic import BaseModel
from typing import List
import auth  # เชื่อมต่อกับระบบล็อกอินของเพื่อน

router = APIRouter(
    prefix="/orders",
    tags=["Orders"]
)

# --- 1. Schemas (โครงสร้างข้อมูล) ---
class OrderItem(BaseModel):
    item_name: str
    quantity: int
    price: float

class OrderCreate(BaseModel):
    items: List[OrderItem]

class OrderStatusUpdate(BaseModel):
    status: str  # เช่น 'pending', 'paid', 'shipped', 'completed', 'cancelled'

class OrderResponse(BaseModel):
    id: int
    user_id: str
    items: List[OrderItem]
    total_price: float
    status: str


# ฐานข้อมูลจำลอง (In-Memory Database)
db_orders = []


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


# --- 2. Endpoints ---

# [POST] สร้างคำสั่งซื้อใหม่
@router.post("/", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
def create_order(order_data: OrderCreate, request: Request):
    current_user = get_user_from_auth(request)
    user_name = current_user.get("username", "user") if isinstance(current_user, dict) else str(current_user)
    
    total = sum(item.price * item.quantity for item in order_data.items)
    
    new_order = {
        "id": len(db_orders) + 1,
        "user_id": user_name,
        "items": order_data.items,
        "total_price": total,
        "status": "pending"
    }
    db_orders.append(new_order)
    return new_order


# [GET] ดึงรายการออเดอร์ทั้งหมดของผู้ใช้ที่ล็อกอินอยู่
@router.get("/", response_model=List[OrderResponse])
def get_my_orders(request: Request):
    current_user = get_user_from_auth(request)
    user_name = current_user.get("username", "user") if isinstance(current_user, dict) else str(current_user)
    
    return [order for order in db_orders if order["user_id"] == user_name]


# [GET] ค้นหาและดูรายละเอียดออเดอร์ตาม ID
@router.get("/{order_id}", response_model=OrderResponse)
def get_order_by_id(order_id: int, request: Request):
    current_user = get_user_from_auth(request)
    user_name = current_user.get("username", "user") if isinstance(current_user, dict) else str(current_user)
    
    for order in db_orders:
        if order["id"] == order_id and order["user_id"] == user_name:
            return order
            
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, 
        detail="ไม่พบรายการคำสั่งซื้อนี้ หรือคุณไม่มีสิทธิ์เข้าถึง"
    )


# [PATCH] อัปเดตสถานะออเดอร์ (เช่น ชำระเงินแล้ว หรือ ยกเลิก)
@router.patch("/{order_id}/status", response_model=OrderResponse)
def update_order_status(order_id: int, status_update: OrderStatusUpdate, request: Request):
    current_user = get_user_from_auth(request)
    user_name = current_user.get("username", "user") if isinstance(current_user, dict) else str(current_user)
    
    for order in db_orders:
        if order["id"] == order_id and order["user_id"] == user_name:
            order["status"] = status_update.status
            return order
            
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, 
        detail="ไม่พบรายการคำสั่งซื้อนี้"
    )


# [DELETE] ยกเลิกคำสั่งซื้อ
@router.delete("/{order_id}", status_code=status.HTTP_200_OK)
def cancel_order(order_id: int, request: Request):
    current_user = get_user_from_auth(request)
    user_name = current_user.get("username", "user") if isinstance(current_user, dict) else str(current_user)
    
    for index, order in enumerate(db_orders):
        if order["id"] == order_id and order["user_id"] == user_name:
            deleted_order = db_orders.pop(index)
            return {
                "message": f"ยกเลิกคำสั่งซื้อ ID {order_id} เรียบร้อยแล้ว", 
                "order": deleted_order
            }
            
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, 
        detail="ไม่พบรายการคำสั่งซื้อนี้"
    )