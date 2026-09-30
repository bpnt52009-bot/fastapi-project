"""รายชื่อผู้ใช้ในระบบ (ต้องล็อกอินก่อนดู)"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth import require_user
from app.db import get_conn

router = APIRouter(prefix="/users", tags=["Users"])


class UserSummary(BaseModel):
    id: int
    name: str


@router.get("", response_model=list[UserSummary])
@router.get("/", response_model=list[UserSummary], include_in_schema=False)
def list_users(_: str = Depends(require_user)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, username FROM users ORDER BY id"
        ).fetchall()
    return [{"id": row["id"], "name": row["username"]} for row in rows]
