from fastapi import APIRouter

router = APIRouter()

@router.get("/orders")
def get_orders():
    return [
        {"order_id": 101, "item": "Mouse", "amount": 2},
        {"order_id": 102, "item": "Keyboard", "amount": 1}
    ]
    