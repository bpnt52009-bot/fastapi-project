from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import users  # อิมพอร์ตไฟล์ users ของเพื่อนเข้ามา[cite: 6]
import order  # เพิ่มการอิมพอร์ตไฟล์ order เข้ามา
import auth  # ระบบล็อกอินก่อนเข้าหน้าเว็บ

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# เสิร์ฟไฟล์หน้าเว็บ (CSS/JS) จากโฟลเดอร์ static
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# เพิ่มเส้นทางหน้าแรก (Root) เพื่อไม่ให้ขึ้น 404 ตอนเข้าเว็บตรงๆ
@app.get("/")
def read_root():
    return {"message": "Welcome to Cyber-sec Project API!"}

# เปิดหน้าเว็บหน้าแรกของ Frontend (ต้องล็อกอินก่อน)
@app.get("/ui", include_in_schema=False)
def read_ui(request: Request):
    if not auth.current_user(request):
        return RedirectResponse("/login", status_code=303)
    return FileResponse(STATIC_DIR / "index.html")

# ดึง API ของเพื่อนเข้ามารัน
app.include_router(users.router)  #[cite: 6]
app.include_router(order.router)  # ดึง Router ของ order เข้ามาใช้งาน
app.include_router(auth.router)  # ระบบล็อกอิน