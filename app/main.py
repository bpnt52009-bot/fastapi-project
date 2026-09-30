"""จุดเริ่มต้นของแอป FastAPI"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.auth import get_current_username
from app.auth import router as auth_router
from app.config import settings
from app.db import init_db
from app.order import router as order_router
from app.users import router as users_router

STATIC_DIR = Path(__file__).resolve().parent / "static"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, version=__version__, lifespan=lifespan)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    return response


@app.get("/")
def read_root():
    return {"message": "Welcome to Cyber-sec Project API!"}


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok", "version": __version__}


@app.get("/ui", include_in_schema=False)
def read_ui(request: Request):
    if not get_current_username(request):
        return RedirectResponse("/login", status_code=303)
    return FileResponse(STATIC_DIR / "index.html")


app.include_router(users_router)
app.include_router(order_router)
app.include_router(auth_router)
