"""Send alerts through Apprise. Dry-run unless FIREWATCH_NOTIFY_LIVE=1.

Apprise URLs carry secrets. They are never logged, returned or put in error text: only the scheme and
a masked host are shown (see mask_url / redact).
"""

import contextlib
import logging
import os
import re

import apprise

from . import messages

log = logging.getLogger(__name__)

CHANNELS = ("push", "sms", "pager", "mesh")
_PUSH = {"ntfy", "ntfys"}
_PAGER = {"mailto", "mailtos"}
_ANY_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://\S+")
MESH_QUEUE: list[dict] = []  # stub: a Meshtastic bridge would drain this


def is_live() -> bool:
    return os.environ.get("FIREWATCH_NOTIFY_LIVE") == "1"


def _urls() -> list[str]:
    return [u.strip() for u in os.environ.get("FIREWATCH_NOTIFY_URLS", "").split(",") if u.strip()]


def _scheme(url: str) -> str:
    return url.split("://", 1)[0].lower() if "://" in url else "unknown"


def mask_url(url: str) -> str:
    """scheme://ab*** only. Never includes credentials, path or query."""
    if "://" not in url:
        return "unknown://***"
    rest = url.split("://", 1)[1]
    rest = re.split(r"[/?#]", rest, maxsplit=1)[0]
    host = rest.rsplit("@", 1)[-1].split(":")[0]
    return f"{_scheme(url)}://{host[:2]}***"


def redact(text: str) -> str:
    """Remove any URL, and any configured URL fragment, from a message."""
    for u in _urls():
        text = text.replace(u, mask_url(u))
    return _ANY_URL.sub(lambda m: mask_url(m.group(0)), text)


def channel_of(url: str) -> str:
    s = _scheme(url)
    return "push" if s in _PUSH else "pager" if s in _PAGER else "sms"


class _Mute(logging.Filter):
    """Apprise logs raw URLs and credentials in its own error lines. Drop them while we send."""

    def filter(self, record: logging.LogRecord) -> bool:
        return False


@contextlib.contextmanager
def _quiet_apprise():
    names = [n for n in logging.root.manager.loggerDict if n == "apprise" or n.startswith("apprise.")]
    loggers = [logging.getLogger(n) for n in names] or [logging.getLogger("apprise")]
    f = _Mute()
    for lg in loggers:
        lg.addFilter(f)
    try:
        yield
    finally:
        for lg in loggers:
            lg.removeFilter(f)


def _row(channel, to, text, status, error=None, via=None) -> dict:
    return {"channel": channel, "to": to, "text": text, "status": status, "error": error, "via": via}


def _default_text(event: dict) -> str:
    return messages.chief_text(event) if event.get("recommendation") == "escalate" else messages.quiet_notice(event)


def send(event: dict, recipients: list[dict], channels: list[str]) -> list[dict]:
    """One result per recipient and channel.

    recipients: dicts with name, phone (optional) and text (optional; defaults to the chief text or the
    quiet notice by recommendation). Returns [{channel, to, text, status, error, via}].
    """
    live = is_live()
    urls = _urls()
    results = []
    for ch in channels:
        if ch not in CHANNELS:
            results.append(_row(ch, "-", "", "failed", f"unknown channel {ch}"))
            continue
        ch_urls = [u for u in urls if channel_of(u) == ch]
        via = ", ".join(mask_url(u) for u in ch_urls) or None
        for r in recipients:
            text = r.get("text") or _default_text(event)
            to = r.get("phone") if ch in ("sms",) and r.get("phone") else r.get("name", "unknown")
            if ch == "mesh":
                if live:
                    MESH_QUEUE.append({"to": to, "text": text})
                results.append(_row(ch, to, text, "sent" if live else "dry_run", "queued for mesh" if live else None, "mesh stub"))
                continue
            if not live:
                results.append(_row(ch, to, text, "dry_run", None, via))
                continue
            if not ch_urls:
                results.append(_row(ch, to, text, "failed", "no destination configured for this channel", None))
                continue
            try:
                with _quiet_apprise():
                    ap = apprise.Apprise()
                    bad = [u for u in ch_urls if not ap.add(u)]
                    if bad:
                        results.append(_row(ch, to, text, "failed",
                                            "could not set up " + ", ".join(mask_url(u) for u in bad), via))
                        continue
                    ok = ap.notify(body=text, title="Firewatch" if ch != "sms" else "")
                results.append(_row(ch, to, text, "sent" if ok else "failed", None if ok else "delivery failed", via))
            except Exception as exc:  # never let a URL leak out of an exception
                err = redact(f"{type(exc).__name__}: {exc}")[:200]
                log.warning("notify failed on %s: %s", ch, err)
                results.append(_row(ch, to, text, "failed", err, via))
    return results
