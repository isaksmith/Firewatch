"""Phone app endpoints (docs/mobile/FW1-CODEC.md): region packs and the tiny FW1 feed. No auth, read-only."""

import hashlib
import json
import logging
import re
from contextlib import asynccontextmanager

from fastapi import APIRouter, HTTPException, Query, Request, Response

from . import fw1
from .config import DATA_DIR
from .db import connect

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(_app):
    """One startup line: are FW1 codes signed, and with which public key (or why not)."""
    status = fw1.signing_status()
    (log.info if fw1.signing_key() else log.warning)(status)
    yield


router = APIRouter(prefix="/api/m", lifespan=_lifespan)
PACKS_DIR = DATA_DIR / "packs"
FEED_MAX = 50
CODE_RE = re.compile(r"^[a-z0-9-]{1,32}$")


def _not_modified(request: Request, etag: str) -> bool:
    return etag in [t.strip() for t in request.headers.get("if-none-match", "").split(",")]


@router.get("/packs")
def list_packs(request: Request):
    path = PACKS_DIR / "index.json"
    body = path.read_bytes() if path.exists() else b"[]"
    etag = f'"{hashlib.sha256(body).hexdigest()}"'
    if _not_modified(request, etag):
        return Response(status_code=304, headers={"ETag": etag})
    return Response(body, media_type="application/json", headers={"ETag": etag, "Cache-Control": "no-cache"})


@router.get("/packs/{code}")
def get_pack(code: str, request: Request):
    path = PACKS_DIR / f"{code}.json"
    if not CODE_RE.match(code) or not path.exists():
        raise HTTPException(404, "We don't have a map pack with that name. Check the list of packs and try again.")
    body = path.read_bytes()
    etag = f'"{hashlib.sha256(body).hexdigest()}"'
    if _not_modified(request, etag):
        return Response(status_code=304, headers={"ETag": etag})
    return Response(body, media_type="application/json", headers={"ETag": etag, "Cache-Control": "no-cache"})


@router.get("/feed")
def feed(request: Request, pack: str | None = Query(None, max_length=32), since: int = Query(0, ge=0)):
    """`<seq> <code>` per line, oldest first, at most 50. Ask again with since=<last seq>."""
    q, args = "SELECT seq, code FROM fw1_feed WHERE seq > ?", [since]
    if pack:
        q += " AND pack = ?"
        args.append(pack)
    q += " ORDER BY seq LIMIT ?"
    args.append(FEED_MAX)
    with connect() as conn:
        rows = conn.execute(q, args).fetchall()
    key = fw1.signing_key()  # rows from before the key existed are signed on the way out; signed ones pass as is
    body = "".join(f"{r['seq']} {fw1.sign(r['code'], key) if key else r['code']}\n" for r in rows)
    etag = f'"{hashlib.sha256(body.encode()).hexdigest()[:24]}"'
    if _not_modified(request, etag):
        return Response(status_code=304, headers={"ETag": etag})
    return Response(body, media_type="text/plain", headers={"ETag": etag, "Cache-Control": "no-cache"})
