"""The public board: board routes only. The tunnel points here (port 8012), never at the main API or Vite."""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from starlette.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from . import routes_posts
from .db import init_db
from .ratelimit import Limiter

MAX_BODY = 16 * 1024
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
PUBLIC_DIR = Path(__file__).resolve().parents[2] / "frontend" / "public"
ROOT_FILES = ("favicon.svg", "icons.svg")

CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self'; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
HEADERS = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
           (b"x-frame-options", b"DENY"), (b"content-security-policy", CSP.encode())]


class Guard:
    """Pure ASGI: caps request bodies and adds security headers to every response."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        api = scope["path"].startswith("/api")
        started = False
        blocked = False

        async def send_wrap(msg):
            nonlocal started
            if blocked:
                return
            if msg["type"] == "http.response.start":
                started = True
                h = list(msg.get("headers", [])) + HEADERS
                if api:
                    h.append((b"cache-control", b"no-store"))
                msg = {**msg, "headers": h}
            await send(msg)

        async def too_big():
            await JSONResponse({"detail": "Request too large"}, status_code=413)(scope, receive, send_wrap)

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                if int(declared) > MAX_BODY:
                    return await too_big()
            except ValueError:
                return await too_big()

        seen = 0

        async def recv():
            nonlocal seen, blocked
            msg = await receive()
            if msg["type"] == "http.request" and not blocked:
                seen += len(msg.get("body", b""))
                if seen > MAX_BODY:
                    if not started:
                        await too_big()
                    blocked = True
                    return {"type": "http.disconnect"}
            return msg

        await self.app(scope, recv, send_wrap)


@asynccontextmanager
async def lifespan(app):
    init_db()
    yield


app = FastAPI(title="Firewatch board", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
app.state.limiter = Limiter()
app.include_router(routes_posts.public_router, prefix="/api")


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/board", status_code=307)


@app.get("/board", include_in_schema=False)
def board():
    index = DIST / "index.html"
    if not index.is_file():
        raise HTTPException(503, "run npm run build in frontend")
    return FileResponse(index)


def _root_file(name: str):
    def handler():
        for base in (DIST, PUBLIC_DIR):
            f = base / name
            if f.is_file():
                return FileResponse(f)
        raise HTTPException(404)
    return handler


for _n in ROOT_FILES:
    app.add_api_route("/" + _n, _root_file(_n), include_in_schema=False)


class Assets(StaticFiles):
    """Resolves DIST/assets at request time so tests can repoint DIST."""

    def __init__(self):
        super().__init__(directory=str(DIST / "assets"), check_dir=False)

    async def get_response(self, path, scope):
        self.directory = str(DIST / "assets")
        self.all_directories = self.get_directories(self.directory, self.packages)
        return await super().get_response(path, scope)


app.mount("/assets", Assets())
app.add_middleware(Guard)
