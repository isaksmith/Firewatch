"""Plain words from a language model on OpenRouter (docs/DESIGN.md section 5.11).

Two uses only: answers to questions people text or radio in (ask.py), and the situation updates posted to the mesh
channel (bulletin.py). Never the alerts themselves: those are fixed templates whose reply words and coordinates the
parser depends on. Every caller has a plain template to fall back on, so a missing key, a timeout or an answer that
fails the checks below only costs the wording.
"""

import logging
import re

import httpx

from .config import get_settings

log = logging.getLogger(__name__)
URL = "https://openrouter.ai/api/v1/chat/completions"
ALWAYS_OK_NUMBERS = {"911"}
_ASCII = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-",
                        "\u2026": "...", "\u00a0": " ", "~": "about "})
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def enabled() -> bool:
    return bool(get_settings().openrouter_api_key)


def numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text.replace(",", "")))


def clean(text: str, max_chars: int) -> str | None:
    """One line of plain ASCII (an SMS with a curly quote costs a 70-character segment), cut at a sentence end
    to fit; None when no whole sentence fits."""
    # Split first: some models put a narrow no-break space in "11 mi", which dropping non-ASCII would glue to "11mi".
    t = " ".join(re.sub(r"[*_`#>]", "", text.translate(_ASCII)).split())
    t = " ".join(t.encode("ascii", "ignore").decode().split()).strip(" \"'")
    if len(t) <= max_chars:
        return t or None
    head = t[:max_chars]
    end = max(head.rfind(". "), head.rfind("? "), head.rfind("! "))
    if head.endswith((".", "?", "!")):
        end = len(head) - 1
    return head[: end + 1] if end > 0 else None


def grounded(text: str, facts: str) -> bool:
    """Every number in the answer appears in the facts it was given (911 aside): a model that invents an acreage,
    a distance or a time fails this and the template goes out instead."""
    return numbers(text) <= numbers(facts) | ALWAYS_OK_NUMBERS


def complete(system: str, facts: str, request: str, max_chars: int) -> str | None:
    """The model's words for `request` from `facts`, or None if there is no key, the call fails, or the answer is
    too long or uses a number the facts don't have."""
    s = get_settings()
    if not s.openrouter_api_key:
        return None
    body = {
        "model": s.openrouter_model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": f"FACTS:\n{facts}\n\n{request}"}],
        # A thinking model can spend the whole budget thinking and return no answer at all.
        "reasoning": {"enabled": False},
        "max_tokens": 600,
        "temperature": 0.2,
    }
    headers = {"Authorization": f"Bearer {s.openrouter_api_key}", "X-Title": "Firewatch",
               "HTTP-Referer": s.public_base_url or "https://firewatch.local"}
    try:
        r = httpx.post(URL, headers=headers, json=body, timeout=s.openrouter_timeout_s)
        if r.status_code == 400 and "reasoning" in r.text.lower():
            # Some models (a router like openrouter/free may pick one) refuse to answer without thinking:
            # let them think, with room left over for the answer.
            body = {**body, "max_tokens": 2000}
            body.pop("reasoning")
            r = httpx.post(URL, headers=headers, json=body, timeout=s.openrouter_timeout_s)
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
    except httpx.HTTPError as e:
        code = getattr(getattr(e, "response", None), "status_code", None)
        log.warning("openrouter call failed: %s%s", type(e).__name__, f" (HTTP {code})" if code else "")
        return None
    except (KeyError, IndexError, TypeError, ValueError) as e:
        log.warning("openrouter answer unreadable: %s", type(e).__name__)
        return None
    text = clean(content or "", max_chars)
    if text is None:
        log.info("openrouter answer did not fit %d chars; using the template", max_chars)
        return None
    if not grounded(text, facts):
        log.info("openrouter answer used numbers not in the facts (%s); using the template",
                 ", ".join(sorted(numbers(text) - numbers(facts) - ALWAYS_OK_NUMBERS)))
        return None
    return text
