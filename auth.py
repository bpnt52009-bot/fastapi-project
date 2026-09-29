import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

router = APIRouter()

COOKIE_NAME = "session"
SESSION_TTL = 60 * 60 * 8  # อายุ session 8 ชั่วโมง
PBKDF2_ROUNDS = 120_000

# ใช้ SECRET_KEY จาก env ถ้ามี ไม่งั้นสุ่มใหม่ทุกครั้งที่รัน (token เก่าจะใช้ไม่ได้)
SECRET_KEY = os.getenv("SECRET_KEY", "").encode() or secrets.token_bytes(32)

# ตัวอย่างบัญชี Admin / 123456 เก็บเป็น hash ไม่เก็บรหัสผ่านจริง
PASSWORD_SALT = b"fastapi-project-037-3"


def hash_password(password: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), PASSWORD_SALT, PBKDF2_ROUNDS).hex()


USERS = {"Admin": hash_password("123456")}


class LoginRequest(BaseModel):
    username: str
    password: str


def _sign(payload: str) -> str:
    mac = hmac.new(SECRET_KEY, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{mac}"


def _verify_signature(token: str) -> str | None:
    payload, _, mac = token.rpartition(".")
    expected = hmac.new(SECRET_KEY, payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    return payload


def current_user(request: Request) -> str | None:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    payload = _verify_signature(token)
    if not payload:
        return None
    username, _, expires = payload.partition(":")
    if username not in USERS or not expires.isdigit():
        return None
    if int(expires) < int(time.time()):
        return None
    return username


@router.get("/login", include_in_schema=False)
def login_page(request: Request):
    # ถ้ายังล็อกอินอยู่ให้ส่งต่อไปหน้าเว็บเลย
    if current_user(request):
        return RedirectResponse("/ui", status_code=303)
    return FileResponse(STATIC_DIR / "login.html")


@router.post("/login")
def login(payload: LoginRequest, response: Response):
    stored = USERS.get(payload.username)
    # เทียบ hash แม้กรณีไม่มีชื่อผู้ใช้ เพื่อไม่ให้เวลาตอบสนองต่างกัน
    candidate = stored or hash_password("dummy")
    if not hmac.compare_digest(hash_password(payload.password), candidate) or stored is None:
        raise HTTPException(status_code=401, detail="ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")
    token = _sign(f"{payload.username}:{int(time.time()) + SESSION_TTL}")
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL,
        path="/",
    )
    return {"message": "เข้าสู่ระบบสำเร็จ", "user": payload.username}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"message": "ออกจากระบบแล้ว"}


@router.get("/me", include_in_schema=False)
def me(request: Request):
    return {"user": current_user(request)}
