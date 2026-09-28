from fastapi import FastAPI

app = FastAPI()

# เพิ่ม Endpoint สำหรับหน้าแรก
@app.get("/")
def read_root():
    return {"message": "Hello, FastAPI!"}

# เพิ่ม Endpoint แบบรับพารามิเตอร์
@app.get("/items/{item_id}")
def read_item(item_id: int, q: str | None = None):
    return {"item_id": item_id, "query": q}