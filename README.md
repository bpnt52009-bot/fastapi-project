# Cyber-sec Project API

FastAPI + SQLite สำหรับจัดการคำสั่งซื้อ พร้อมระบบล็อกอินแบบ cookie session

## สิ่งที่ระบบนี้ทำ

- ล็อกอิน / ออกจากระบบ ด้วย session ที่เก็บในฐานข้อมูล (logout แล้วใช้ token เดิมต่อไม่ได้)
- CRUD คำสั่งซื้อ แยกข้อมูลตามเจ้าของ (ผู้ใช้อ่าน/แก้/ลบได้เฉพาะออเดอร์ของตัวเอง)
- เงินคำนวณด้วย `Decimal` และเก็บเป็นจำนวนเต็ม (สตางค์) ไม่มี error ทศนิยม
- สถานะออเดอร์เป็น `StrEnum` พร้อมกฎการเปลี่ยนสถานะ
- จำกัดความถี่การเดารหัสผ่าน (429 + `Retry-After`)
- เพิ่ม security headers ทุก response

## โครงสร้างโปรเจค

```
app/
  __init__.py
  config.py     ตั้งค่าจาก env / .env
  security.py   hash รหัสผ่าน (PBKDF2 + salt สุ่มต่อ user) และการลงลายเซ็น token
  db.py         SQLite: schema, migration, connection lifecycle
  money.py      แปลงเงิน Decimal <-> สตางค์
  auth.py       session, login rate limit
  order.py      คำสั่งซื้อ
  users.py      รายชื่อผู้ใช้
  main.py       จุดเริ่มต้นแอป
  static/       หน้าเว็บ (HTML/CSS/JS ธรรมดา ไม่มี build step)
tests/          pytest
```

## วิธีรัน

```bash
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
pip install -r requirements-dev.txt   # ถ้าจะรันเทสต์ด้วย

copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux

uvicorn app.main:app --reload
```

เปิด <http://127.0.0.1:8000> → จะถูกพาไปหน้า `/login`
บัญชีเริ่มต้น `Admin` / `123456` (ตั้งค่าใหม่ได้ใน `.env`)

เอกสาร API อัตโนมัติที่ <http://127.0.0.1:8000/docs>

## รันเทสต์และ lint

```bash
pytest
ruff check app tests
```

## ตัวแปรตั้งค่า

ทั้งหมดอ่านจาก `.env` ดูตัวอย่างที่ `.env.example`

| ตัวแปร | ค่าเริ่มต้น | หมายเหตุ |
| --- | --- | --- |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | `Admin` / `123456` | sync เข้า DB ทุกครั้งที่แอปเริ่ม ระบบจะ log เตือนถ้ายังใช้รหัสเริ่มต้น |
| `SECRET_KEY` | สุ่มแล้วเก็บใน DB | เว้นว่างได้ตอน dev — ถ้าตั้งเองต้องยาวอย่างน้อย 32 ตัวอักษร |
| `SESSION_TTL_SECONDS` | `28800` (8 ชม.) | อายุ session |
| `SESSION_COOKIE_SECURE` | `false` | **ต้องเป็น `true` เมื่อขึ้น production** (บังคับ https) |
| `LOGIN_MAX_ATTEMPTS` | `5` | จำนวนครั้งที่ล็อกอินพลาดได้ก่อนถูกล็อก |
| `LOGIN_WINDOW_SECONDS` | `300` | ช่วงเวลานับความผิดพลาด |
| `LOGIN_LOCKOUT_SECONDS` | `900` | ระยะเวลาที่ถูกล็อก |
| `DATABASE_PATH` | `orders.db` ในโฟลเดอร์โปรเจค | ถ้าตั้งเองให้ใช้พาธแบบ absolute |

## API หลัก

| Method | Path | หมายเหตุ |
| --- | --- | --- |
| `GET` | `/` | public |
| `GET` | `/health` | public |
| `GET` | `/login` | หน้าเว็บล็อกอิน |
| `POST` | `/login` | ตั้ง cookie session |
| `POST` | `/logout` | revoke session จริง |
| `GET` | `/me` | ผู้ใช้ปัจจุบัน |
| `GET` | `/users` | ต้องล็อกอิน |
| `GET` | `/orders` | ต้องล็อกอิน รองรับ `?status=` `?limit=` `?offset=` |
| `POST` | `/orders` | ต้องล็อกอิน |
| `GET` | `/orders/{id}` | เจ้าของเท่านั้น |
| `PATCH` | `/orders/{id}/status` | เจ้าของเท่านั้น |
| `DELETE` | `/orders/{id}` | เจ้าของเท่านั้น |

## หมายเหตุด้านความปลอดภัย

- รหัสผ่านถูกเก็บเป็น PBKDF2-HMAC-SHA256 600,000 รอบ พร้อม salt ที่สุ่มใหม่ต่อผู้ใช้
- ในฐานข้อมูลเก็บแค่ SHA-256 ของ session token ไม่เก็บ token จริง
- ทุก query ของออเดอร์ผูก `user_id` ทั้งตอนอ่านและตอนเขียน
- เมื่อขึ้น production ต้องตั้ง `SECRET_KEY`, `SESSION_COOKIE_SECURE=true`
  และเสิร์ฟหลัง reverse proxy ที่ทำ TLS
- ระบบตั้ง `SameSite=Lax` และรับเฉพาะ JSON body จึงกัน CSRF จากฟอร์มข้ามโดเมนได้ในระดับพื้นฐาน
