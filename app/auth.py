"""ระบบล็อกอิน: session ฝังในฐานข้อมูล (เลิกใช้งานได้จริงตอน logout) + จำกัดความถี่การเดารหัสผ่าน"""

import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.db import get_conn
from app.security import (
    generate_token,
    hash_password,
    sign,
    token_fingerprint,
    unsign,
    verify_password,
)

router = APIRouter(tags=["Auth"])

STATIC_DIR = Path(__file__).resolve().parent / "static"

# hash ของรหัสผ่านที่ไม่มีอยู่จริง ใช้เทียบเวลาให้เหมือนกันทั้งกรณีชื่อผู้ใช้มี/ไม่มี
_DUMMY_HASH = hash_password("not-a-real-password")


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=256)


class LoginThrottle:
    """จำกัดจำนวนครั้งที่ล็อกอินไม่สำเร็จ ต่อ 1 คู่ (IP + ชื่อผู้ใช้)"""

    def __init__(self, max_attempts: int, window: int, lockout: int) -> None:
        self._max_attempts = max_attempts
        self._window = window
        self._lockout = lockout
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._locked_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def _prune(self, bucket: deque[float], now: float) -> None:
        while bucket and now - bucket[0] > self._window:
            bucket.popleft()

    def retry_after(self, key: str) -> int:
        now = time.time()
        with self._lock:
            until = self._locked_until.get(key, 0.0)
            if until <= now:
                self._locked_until.pop(key, None)
                return 0
            return max(1, int(until - now))

    def record_failure(self, key: str) -> None:
        now = time.time()
        with self._lock:
            bucket = self._failures[key]
            self._prune(bucket, now)
            bucket.append(now)
            if len(bucket) >= self._max_attempts:
                self._locked_until[key] = now + self._lockout
                bucket.clear()

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)


throttle = LoginThrottle(
    max_attempts=settings.login_max_attempts,
    window=settings.login_window_seconds,
    lockout=settings.login_lockout_seconds,
)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _throttle_key(request: Request, username: str) -> str:
    return f"{_client_ip(request)}::{username}"


def _purge_expired_sessions(conn) -> None:
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))


def create_session(username: str) -> str:
    with get_conn() as conn:
        _purge_expired_sessions(conn)
        token = generate_token()
        now = int(time.time())
        conn.execute(
            "INSERT INTO sessions (token_hash, username, created_at, expires_at)"
            " VALUES (?, ?, ?, ?)",
            (token_fingerprint(token), username, now, now + settings.session_ttl_seconds),
        )
    return sign(token)


def revoke_session(signed_token: str | None) -> None:
    if not signed_token:
        return
    token = unsign(signed_token)
    if not token:
        return
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM sessions WHERE token_hash = ?", (token_fingerprint(token),)
        )


def get_current_username(request: Request) -> str | None:
    """คืนชื่อผู้ใช้ที่ล็อกอินอยู่ หรือ None ถ้า session ไม่ถูกต้อง/หมดอายุ"""
    signed_token = request.cookies.get(settings.session_cookie_name)
    if not signed_token:
        return None

    token = unsign(signed_token)
    if not token:
        return None

    with get_conn() as conn:
        row = conn.execute(
            "SELECT username, expires_at FROM sessions WHERE token_hash = ?",
            (token_fingerprint(token),),
        ).fetchone()

    if row is None:
        return None
    if row["expires_at"] <= int(time.time()):
        revoke_session(signed_token)
        return None
    return row["username"]


def require_user(request: Request) -> str:
    """Dependency: บังคับให้ต้องล็อกอิน ไม่งั้นตอบ 401"""
    username = get_current_username(request)
    if not username:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="กรุณาเข้าสู่ระบบก่อนดำเนินการ",
        )
    return username


def is_admin(username: str) -> bool:
    """เช็ค role จากฐานข้อมูล ไม่เชื่อค่าที่ส่งมาจาก client"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT role FROM users WHERE username = ?", (username,)
        ).fetchone()
    return row is not None and row["role"] == "admin"


def require_admin(request: Request) -> str:
    """Dependency: ต้องล็อกอิน และต้องเป็นผู้ดูแลระบบ (401 ถ้ายังไม่ล็อกอิน, 403 ถ้าไม่ใช่ admin)"""
    username = require_user(request)
    if not is_admin(username):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ต้องเป็นผู้ดูแลระบบเท่านั้น",
        )
    return username


CurrentUser = Depends(require_user)
CurrentAdmin = Depends(require_admin)


@router.get("/login", include_in_schema=False)
def login_page(request: Request):
    if get_current_username(request):
        return RedirectResponse("/ui", status_code=303)
    return FileResponse(STATIC_DIR / "login.html")


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    key = _throttle_key(request, payload.username)

    retry_after = throttle.retry_after(key)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="ลองใส่รหัสผ่านผิดบ่อยเกินไป กรุณารอสักครู่แล้วลองใหม่",
            headers={"Retry-After": str(retry_after)},
        )

    with get_conn() as conn:
        row = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?",
            (payload.username,),
        ).fetchone()

    stored_hash = row["password_hash"] if row is not None else _DUMMY_HASH
    password_ok = verify_password(payload.password, stored_hash)

    if row is None or not password_ok:
        throttle.record_failure(key)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง",
        )

    throttle.reset(key)
    signed_token = create_session(payload.username)
    response.set_cookie(
        key=settings.session_cookie_name,
        value=signed_token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    return {"message": "เข้าสู่ระบบสำเร็จ", "user": payload.username}


@router.post("/logout")
def logout(request: Request, response: Response):
    revoke_session(request.cookies.get(settings.session_cookie_name))
    response.delete_cookie(key=settings.session_cookie_name, path="/", samesite="lax")
    return {"message": "ออกจากระบบแล้ว"}


@router.get("/me", include_in_schema=False)
def me(user: str = CurrentUser):
    return {"user": user}
