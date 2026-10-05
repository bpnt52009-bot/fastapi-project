"""จัดการผู้ใช้: ดู/สร้าง/แก้/ลบ (ผู้ดูแลระบบ) และโปรไฟล์ของตัวเอง"""

import time
from enum import StrEnum
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field, field_validator

from app.auth import require_admin, require_user
from app.db import get_conn
from app.security import hash_password

router = APIRouter(prefix="/users", tags=["Users"])

MIN_PASSWORD_LENGTH = 8


class UserRole(StrEnum):
    ADMIN = "admin"
    USER = "user"


def _normalise_username(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("ชื่อผู้ใช้ห้ามเป็นช่องว่างล้วน")
    if len(cleaned) > 64:
        raise ValueError("ชื่อผู้ใช้ยาวเกิน 64 ตัวอักษร")
    return cleaned


class UserSummary(BaseModel):
    """ข้อมูลผู้ใช้แบบย่อ ใช้ในรายการและหน้ารายละเอียด"""

    id: int
    name: str
    role: UserRole
    created_at: int


class UserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH, max_length=256)
    role: UserRole = Field(default=UserRole.USER, description="ค่าเริ่มต้นเป็น user")

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str) -> str:
        return _normalise_username(value)


class UserUpdate(BaseModel):
    """แก้ไขผู้ใช้: ส่งเฉพาะฟิลด์ที่ต้องการเปลี่ยน ถ้าไม่ส่งรหัสผ่านมาแปลว่าไม่เปลี่ยน"""

    username: str | None = Field(default=None, min_length=1, max_length=64)
    password: str | None = Field(
        default=None, min_length=MIN_PASSWORD_LENGTH, max_length=256
    )
    role: UserRole | None = None

    @field_validator("username")
    @classmethod
    def _check_username(cls, value: str | None) -> str | None:
        return None if value is None else _normalise_username(value)

    def changes(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True)


UserId = Annotated[int, Path(gt=0, description="เลข id ของผู้ใช้")]


def _row_to_user(row) -> UserSummary:
    return UserSummary(
        id=row["id"],
        name=row["username"],
        role=UserRole(row["role"]),
        created_at=row["created_at"],
    )


def _fetch_user(conn, user_id: int):
    return conn.execute(
        "SELECT id, username, role, created_at FROM users WHERE id = ?", (user_id,)
    ).fetchone()


def _require_user_row(conn, user_id: int):
    row = _fetch_user(conn, user_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ไม่พบผู้ใช้นี้"
        )
    return row


@router.get("/me", response_model=UserSummary)
def read_my_profile(user_name: str = Depends(require_user)):
    """โปรไฟล์ของผู้ที่ล็อกอินอยู่ ใครก็อ่านได้ของตัวเอง"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, username, role, created_at FROM users WHERE username = ?",
            (user_name,),
        ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="ไม่พบผู้ใช้นี้"
        )
    return _row_to_user(row)


@router.get("", response_model=list[UserSummary])
@router.get("/", response_model=list[UserSummary], include_in_schema=False)
def list_users(_: str = Depends(require_admin)):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, username, role, created_at FROM users ORDER BY id"
        ).fetchall()
    return [_row_to_user(row) for row in rows]


@router.post("", response_model=UserSummary, status_code=status.HTTP_201_CREATED)
@router.post(
    "/",
    response_model=UserSummary,
    status_code=status.HTTP_201_CREATED,
    include_in_schema=False,
)
def create_user(payload: UserCreate, _: str = Depends(require_admin)):
    password_hash = hash_password(payload.password)
    now = int(time.time())

    with get_conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (payload.username,)
        ).fetchone()
        if exists is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="ชื่อผู้ใช้นี้ถูกใช้แล้ว"
            )

        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, role, created_at)"
            " VALUES (?, ?, ?, ?)",
            (payload.username, password_hash, payload.role.value, now),
        )
        row = _require_user_row(conn, cursor.lastrowid)

    return _row_to_user(row)


@router.get("/{user_id}", response_model=UserSummary)
def get_user(user_id: UserId, _: str = Depends(require_admin)):
    with get_conn() as conn:
        row = _require_user_row(conn, user_id)
    return _row_to_user(row)


@router.patch("/{user_id}", response_model=UserSummary)
def update_user(
    user_id: UserId, payload: UserUpdate, admin_name: str = Depends(require_admin)
):
    changes = payload.changes()
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ไม่มีฟิลด์ที่ต้องการแก้ไข",
        )

    with get_conn() as conn:
        row = _require_user_row(conn, user_id)

        if "username" in changes:
            clash = conn.execute(
                "SELECT 1 FROM users WHERE username = ? AND id != ?",
                (changes["username"], user_id),
            ).fetchone()
            if clash is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="ชื่อผู้ใช้นี้ถูกใช้แล้ว"
                )

        if "role" in changes and row["username"] == admin_name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ไม่สามารถเปลี่ยนสิทธิ์ของบัญชีที่กำลังล็อกอินอยู่ได้",
            )

        if "password" in changes:
            conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(str(changes["password"])), user_id),
            )
            # บังคับให้ session เดิมหมดอายุ เพื่อไม่ให้คนที่รู้รหัสเก่ายังใช้งานได้
            conn.execute("DELETE FROM sessions WHERE username = ?", (row["username"],))

        if "username" in changes:
            conn.execute(
                "UPDATE users SET username = ? WHERE id = ?",
                (changes["username"], user_id),
            )
            conn.execute(
                "UPDATE sessions SET username = ? WHERE username = ?",
                (changes["username"], row["username"]),
            )

        if "role" in changes:
            conn.execute(
                "UPDATE users SET role = ? WHERE id = ?", (changes["role"], user_id)
            )

        updated = _require_user_row(conn, user_id)

    return _row_to_user(updated)


@router.delete("/{user_id}", status_code=status.HTTP_200_OK)
def delete_user(user_id: UserId, admin_name: str = Depends(require_admin)):
    with get_conn() as conn:
        row = _require_user_row(conn, user_id)

        if row["username"] == admin_name:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="ไม่สามารถลบบัญชีตัวเองได้"
            )

        conn.execute("DELETE FROM sessions WHERE username = ?", (row["username"],))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

    return {"message": f"ลบผู้ใช้ {row['username']} เรียบร้อยแล้ว", "id": user_id}
