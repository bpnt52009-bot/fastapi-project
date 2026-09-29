from fastapi import FastAPI
import users  # อิมพอร์ตไฟล์ของเพื่อนเข้ามา

app = FastAPI()

app.include_router(users.router)  # ดึง API ของเพื่อนมารัน