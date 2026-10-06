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

## สิทธิ์ของผู้ใช้

| ความสามารถ | admin | user |
| --- | --- | --- |
| ดูออเดอร์ของตัวเอง | ได้ | ได้ |
| ดูออเดอร์ของทุกคน + กรอง `?user=` | ได้ | ไม่ได้ (403) |
| สร้างคำสั่งซื้อ | ได้ (เลือกเจ้าของได้) | ไม่ได้ (403) |
| เปลี่ยนสถานะ / ยกเลิกออเดอร์ | ได้ | ไม่ได้ (403) |
| ดู เพิ่ม แก้ ลบผู้ใช้ | ได้ | ไม่ได้ (403) |

หน้าเว็บซ่อนปุ่มที่ใช้ไม่ได้ให้อัตโนมัติ แต่การตรวจสิทธิ์จริงเป็นฝั่ง server
เพราะฝั่ง client แก้ได้ทุกเมื่อ — ลองเรียก API ตรง ๆ แล้วจะได้ 403 เสมอ

## API หลัก

| Method | Path | สิทธิ์ | หมายเหตุ |
| --- | --- | --- | --- |
| `GET` | `/` | public | |
| `GET` | `/health` | public | |
| `GET` | `/login` | public | หน้าเว็บล็อกอิน |
| `POST` | `/login` | public | ตั้ง cookie session |
| `POST` | `/logout` | ทุกคน | revoke session จริง |
| `GET` | `/me` | ทุกคน | ผู้ใช้ปัจจุบัน |
| `GET` | `/users/me` | ทุกคน | โปรไฟล์ตัวเอง มี `role` |
| `GET` | `/users` | admin | |
| `POST` | `/users` | admin | รหัสผ่านยาวอย่างน้อย 8 ตัว |
| `GET` | `/users/{id}` | admin | |
| `PATCH` | `/users/{id}` | admin | แก้ชื่อ/รหัสผ่าน/สิทธิ์ |
| `DELETE` | `/users/{id}` | admin | ลบและปิด session ทั้งหมด |
| `GET` | `/orders` | ทุกคน | `?status=` `?user=` (admin) `?limit=` `?offset=` |
| `POST` | `/orders` | admin | `user_id` เลือกเจ้าของได้ |
| `GET` | `/orders/{id}` | เจ้าของ / admin | |
| `PATCH` | `/orders/{id}/status` | admin | |
| `DELETE` | `/orders/{id}` | admin | |

## หน้าเว็บที่ `/ui`

**สำหรับ admin**

- **เพิ่มผู้ใช้** — กรอกชื่อ รหัสผ่าน (อย่างน้อย 8 ตัว) และเลือกสิทธิ์ `user` / `admin`
- **จัดการสิทธิ์** — ปุ่มสลับ `user` ↔ `admin` (กดกับบัญชีตัวเองไม่ได้ ได้ 409 จาก server)
- **ลบผู้ใช้** — มี `window.confirm` ยืนยัน และ session ของเขาจะถูกปิดทันที
- **สร้างคำสั่งซื้อ** — กรอกสินค้าได้หลายรายการ เลือกเจ้าของออเดอร์ได้
- **กรองออเดอร์ตามเจ้าของ** — dropdown ข้างหัวตารางคำสั่งซื้อ
- **เปลี่ยนสถานะ** — dropdown จะแสดงเฉพาะสถานะที่เปลี่ยนได้จริงตามกฎของ backend
  ถ้าสถานะสุดท้าย (`completed` / `cancelled`) จะแสดงเป็นป้ายแทน dropdown
- **ยกเลิกออเดอร์** — มี `window.confirm` ยืนยันก่อน

**สำหรับ user**

- ดูออเดอร์ของตัวเองได้อย่างเดียว ส่วนฟอร์มและปุ่มจัดการจะถูกซ่อนทั้งหมด
- ถ้าลองยิง API เองจะได้ 403

ทุกการกระทำจะโหลดตารางใหม่อัตโนมัติ และข้อความ error จาก API แสดงเป็นภาษาไทย

ตารางสถานะใน `app/static/app.js` (`NEXT_STATUS`) ต้องตรงกับ `ALLOWED_TRANSITIONS`
ใน `app/order.py` เสมอ มีเทสต์คอยเช็คให้อยู่แล้ว

## หมายเหตุด้านความปลอดภัย

- รหัสผ่านถูกเก็บเป็น PBKDF2-HMAC-SHA256 600,000 รอบ พร้อม salt ที่สุ่มใหม่ต่อผู้ใช้
- ในฐานข้อมูลเก็บแค่ SHA-256 ของ session token ไม่เก็บ token จริง
- role ถูกอ่านจากฐานข้อมูลทุกครั้ง ไม่เชื่อค่าที่ส่งมาจาก client
- ทุก query ของออเดอร์บังคับขอบเขตด้วย `user_id` ทั้งตอนอ่านและตอนเขียน
- ผู้ดูแลระบบเปลี่ยนสิทธิ์หรือรหัสผ่านของตัวเองไม่ได้ (409) กันการตัดสิทธิ์ตัวเองถาวร
- ชื่อ `ADMIN_USERNAME` ถูกสงวนไว้ สร้างหรือ rename เป็นชื่อนี้ไม่ได้
  เพราะ bootstrap จะรีเซ็ตรหัสผ่านและสิทธิ์ของชื่อนี้เป็น admin ทุกครั้งที่ restart
- เมื่อขึ้น production ต้องตั้ง `SECRET_KEY`, `SESSION_COOKIE_SECURE=true`
  และเสิร์ฟหลัง reverse proxy ที่ทำ TLS
- ระบบตั้ง `SameSite=Lax` และรับเฉพาะ JSON body จึงกัน CSRF จากฟอร์มข้ามโดเมนได้ในระดับพื้นฐาน
