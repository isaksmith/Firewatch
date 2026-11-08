"""Firewatch product video: the shot engine and the story cut (out/Firewatch-Story.mp4).

No narration: short on-screen captions over app recordings, 3D graphics and deck slides.
Pipeline: recordings (rec_*.mjs -> build/rec/*.mp4 + *.json marks) and deck slides (render_slides.py) in,
caption PNGs (HTML via render_cards.mjs) overlaid with ffmpeg (no drawtext here), one mp4 per shot, joined with
the concat demuxer.  build_tour.py reuses build() below.

    cd docs/video/story && npm install && build/venv/bin/python build_video.py
"""

from __future__ import annotations

import base64
import hashlib
import html
import io
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
REC = BUILD / "rec"
SLIDES = BUILD / "slides"
CARDS = BUILD / "cards"
OUT = HERE / "out"
ASSETS = HERE / "assets"
FFMPEG = "/opt/homebrew/bin/ffmpeg"
FONTS = HERE.parents[2] / "frontend/node_modules/@fontsource"
W, H, FPS = 1920, 1080, 30
UI_LAG = 1.5  # the dashboard polls, so it shows a scenario minute about this long after the API reports it
C = dict(ember="#ff5a36", amber="#ffb21a", sky="#5cc8ff", ok="#3ddc97", violet="#b18cff", text="#e6e8eb", muted="#8b939d")


@dataclass
class Cap:
    text: str
    chip: tuple | None = None  # (tag, label, colour)
    color: str = C["ember"]


@dataclass
class Shot:
    kind: str  # clip | still | phone
    src: str  # recording name | "slide:sol-03" | "card:name" | path (phone)
    caps: list[Cap] = field(default_factory=list)
    a: object = 0.0  # clip start: seconds or a mark spec (see at())
    b: object = None  # clip end; None = play to the end of the recording
    speed: float = 1.0
    fit: bool = False  # retime the span a..b so it lasts exactly as long as the captions take to read
    zoom: tuple = (1.0, 1.0, 0.5, 0.5)  # z_start, z_end, cx, cy (fractions of the frame)
    hold: float = 0.0  # minimum length; stills with no captions last this long
    pos: str = "left"  # caption side: left | right
    drift: bool = True  # slow 1.0 -> 1.03 push on stills


def read_time(text: str) -> float:
    return max(2.8, 1.0 + 0.3 * len(text.split()))


def run(cmd: list, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


# Recordings and marks -----------------------------------------------------------------------------------
_meta: dict[str, dict] = {}


def meta(rec: str) -> dict:
    if rec not in _meta:
        _meta[rec] = json.loads((REC / f"{rec}.json").read_text())
    return _meta[rec]


def at(rec: str, spec) -> float:
    """Clip time in seconds. spec: a number; "mark"; "mark+1.5"; "t=20" (scenario minute 20 as the screen shows it)."""
    if isinstance(spec, (int, float)):
        return float(spec)
    off = 0.0
    if "+" in spec:
        spec, o = spec.split("+", 1)
        off = float(o)
    marks = meta(rec)["marks"]
    if spec.startswith("t="):
        m = float(spec[2:])
        hit = next(x for x in marks if x["what"] == "t" and x["t_min"] >= m)
        return hit["t"] + UI_LAG + off
    return next(x for x in marks if x["what"] == spec)["t"] + off


# Caption and card images --------------------------------------------------------------------------------
def b64font(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


def font_css() -> str:
    sans, mono = FONTS / "ibm-plex-sans/files", FONTS / "ibm-plex-mono/files"
    return (
        f"@font-face{{font-family:Plex;font-weight:400;src:url(data:font/woff2;base64,{b64font(sans / 'ibm-plex-sans-latin-400-normal.woff2')})}}"
        f"@font-face{{font-family:Plex;font-weight:700;src:url(data:font/woff2;base64,{b64font(sans / 'ibm-plex-sans-latin-700-normal.woff2')})}}"
        f"@font-face{{font-family:PlexMono;font-weight:600;src:url(data:font/woff2;base64,{b64font(mono / 'ibm-plex-mono-latin-600-normal.woff2')})}}"
    )


def caption_html(cap: Cap, pos: str) -> str:
    chip = ""
    if cap.chip:
        tag, label, col = cap.chip
        chip = f'<div class="chip" style="border-left-color:{col}"><b style="color:{col}">{html.escape(tag)}</b> {html.escape(label)}</div>'
    side = "left:64px" if pos == "left" else "right:64px"
    return (
        f"<html><head><style>{font_css()}"
        "html,body{margin:0;width:1920px;height:1080px;background:transparent;overflow:hidden}"
        f".wrap{{position:absolute;bottom:72px;{side};max-width:1040px;display:flex;flex-direction:column;align-items:flex-start;gap:10px}}"
        ".chip{background:rgba(5,6,7,.88);border-left:7px solid;padding:7px 16px;font:600 22px PlexMono;letter-spacing:.08em;color:#c9ced3;text-transform:uppercase}"
        ".chip b{margin-right:8px}"
        f".panel{{background:rgba(5,6,7,.88);border-left:7px solid {cap.color};padding:24px 34px;color:#fff;font:700 44px/1.22 Plex}}"
        f"</style></head><body><div class='wrap'>{chip}<div class='panel'>{html.escape(cap.text)}</div></div></body></html>"
    )


def img64(path: Path, height: int) -> str:
    im = Image.open(path).convert("RGB")
    im = im.resize((round(im.width * height / im.height), height), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


CARD_CSS = (
    "html,body{margin:0;width:1920px;height:1080px;background:#08090b;color:#e6e8eb;font-family:Plex;overflow:hidden}"
    ".k{font:600 24px PlexMono;letter-spacing:.1em;text-transform:uppercase}"
    "h1{font:700 64px/1.1 Plex;margin:0}"
    "li{font:400 38px/1.3 Plex;margin:0 0 26px;list-style:none;padding-left:34px;position:relative}"
    "li:before{content:'';position:absolute;left:0;top:18px;width:14px;height:14px;background:#ff5a36}"
)


def card_html(name: str) -> str:
    base = f"<html><head><style>{font_css()}{CARD_CSS}</style></head><body>"
    if name == "steps":  # how it works, three steps
        cols = [
            ("1  DETECT", C["amber"], "Something looks wrong", ["A power-line fault from the electric co-op", "Heat seen by satellites", "Texts from neighbours"]),
            ("2  CONFIRM", C["sky"], "Is it a real fire?", ["One signal only starts a text to the duty officer", "Burns the county already knows about stay quiet", "Every score shows its reasons"]),
            ("3  RESPOND", C["ember"], "Get people moving", ["Text the duty officer, then the chief", "The chief replies PAGE: the district is paged", "A forecast shows where it runs next"]),
        ]
        body = "".join(
            f"<div style='flex:1;border-top:8px solid {c};background:#0c0e11;padding:36px 36px 20px'><div class='k' style='color:{c}'>{t}</div>"
            f"<div style='font:700 44px/1.15 Plex;margin:18px 0 34px'>{s}</div><ul style='margin:0;padding:0'>{''.join(f'<li style=\"font-size:34px\">{html.escape(i)}</li>' for i in items)}</ul></div>"
            for t, c, s, items in cols
        )
        return base + f"<div style='padding:70px 80px'><div class='k' style='color:#8b939d'>How Firewatch works</div><h1 style='margin:12px 0 44px'>Three steps, one chain.</h1><div style='display:flex;gap:28px'>{body}</div></div></body></html>"
    if name == "phone":  # phone stills + bullets
        p1, p2 = img64(ASSETS / "ph1.png", 900), img64(ASSETS / "ph3.png", 900)
        return base + (
            f"<div style='display:flex;align-items:center;height:1080px;padding:0 90px;gap:60px'>"
            f"<img src='{p1}' style='height:900px;border-radius:44px;border:3px solid #2a3038'><img src='{p2}' style='height:900px;border-radius:44px;border:3px solid #2a3038'>"
            "<div style='flex:1'><div class='k' style='color:#ff5a36'>The chief's phone</div><h1 style='margin:12px 0 38px;font-size:56px'>One alert, one clear action.</h1><ul style='margin:0;padding:0'>"
            "<li>Big buttons and plain words</li><li>The map is saved on the phone, so it works with no signal</li>"
            "<li>The worst-case cone shows which way it runs</li><li>Nearest road named for the first truck</li></ul></div></div></body></html>"
        )
    if name == "phonebg":  # dark backdrop for the phone video
        return base + "<div style='height:1080px;background:radial-gradient(circle at 78% 50%,#161a20,#08090b 60%)'></div></body></html>"
    if name == "tour":
        feats = ["Live scenario: from a line fault to a paged district", "False alarms: permitted burns stay quiet", "3D spread preview", "Community board", "FireNode planner", "Results: today versus Firewatch", "The chief's phone"]
        lis = "".join(f"<li>{i + 1}. {html.escape(f)}</li>" for i, f in enumerate(feats))
        return base + ("<div style='height:1080px;display:flex;flex-direction:column;justify-content:center;padding:0 140px'><div class='k' style='color:#ff5a36'>Firewatch · feature tour</div>"
                       "<h1 style='font-size:80px;margin:20px 0 40px'>What the chief can do today</h1><ul style='margin:0;padding:0'>" + lis + "</ul></div></body></html>")
    if name == "close":
        return base + (
            "<div style='height:1080px;display:flex;flex-direction:column;justify-content:center;padding:0 140px'>"
            "<div class='k' style='color:#ff5a36'>Firewatch · team Watch Dogs</div>"
            "<h1 style='font-size:88px;margin:22px 0 30px'>Find the fire in minutes,<br>not 27 minutes later.</h1>"
            "<div style='font:400 40px/1.35 Plex;color:#c9ced3;max-width:1300px'>Free public data. One text to the people who can act. A human decides, every time.</div></div></body></html>"
        )
    raise KeyError(name)


def ensure_cards(shots: list[Shot]) -> dict[str, Path]:
    """Render every caption and card the shots need (once, cached by content) and return their paths."""
    jobs, paths = [], {}
    for s in shots:
        for c in s.caps:
            h = hashlib.sha1(caption_html(c, s.pos).encode()).hexdigest()[:12]
            p = CARDS / f"cap-{h}.png"
            paths[(c.text, s.pos, c.chip, c.color)] = p
            if not p.exists():
                jobs.append({"out": str(p), "html": caption_html(c, s.pos), "transparent": True})
        if s.src.startswith("card:") or s.kind == "phone":
            name = "phonebg" if s.kind == "phone" else s.src[5:]
            p = CARDS / f"card-{name}.png"
            paths[name] = p
            jobs.append({"out": str(p), "html": card_html(name), "transparent": False})
    if jobs:
        CARDS.mkdir(parents=True, exist_ok=True)
        uniq = list({j['out']: j for j in jobs}.values())
        (CARDS / "jobs.json").write_text(json.dumps(uniq))
        run(["node", HERE / "render_cards.mjs", CARDS / "jobs.json"], cwd=HERE)
    return paths


# Shot rendering -----------------------------------------------------------------------------------------
def zoom_filter(z: tuple, frames: int) -> str:
    z0, z1, cx, cy = z
    if z0 == 1.0 and z1 == 1.0:
        return ""
    if z0 == z1:
        return f"crop=w=iw/{z0}:h=ih/{z0}:x='clip({cx}*iw-iw/{z0}/2,0,iw-iw/{z0})':y='clip({cy}*ih-ih/{z0}/2,0,ih-ih/{z0})',scale={W}:{H}:flags=lanczos,"
    n = max(frames - 1, 1)
    zz = f"({z0}+({z1}-{z0})*(1-cos(PI*min(on/{n},1)))/2)"
    return (f"scale={W * 2}:{H * 2}:flags=bicubic,zoompan=z='{zz}':x='clip({cx}*iw-iw/{zz}/2,0,iw-iw/{zz})':y='clip({cy}*ih-ih/{zz}/2,0,ih-ih/{zz})':d=1:s={W}x{H}:fps={FPS},")


def plan(s: Shot) -> dict:
    """Work out the shot's duration, source span and speed, and when each caption shows."""
    reads = [read_time(c.text) for c in s.caps]
    need = max(sum(reads), s.hold)
    p = {"reads": reads}
    if s.kind in ("clip", "phone"):
        if s.kind == "clip":
            a = at(s.src, s.a)
            b = at(s.src, s.b) if s.b is not None else meta(s.src)["duration"]
        else:
            a, b = float(s.a), float(s.b)
        span = max(b - a, 0.2)
        speed = s.speed
        if s.fit and need > 0:
            speed = min(8.0, max(0.12, span / need))
        dur = max(need, span / speed)
        p.update(a=a, span=span, speed=speed)
    else:
        dur = max(need, s.hold, 2.0)
    p["dur"] = round(dur * FPS) / FPS
    return p


def render_shot(s: Shot, idx: int, out: Path, paths: dict, fade_in: float, fade_out: float) -> float:
    p = plan(s)
    dur, frames = p["dur"], round(p["dur"] * FPS)
    cmd = [FFMPEG, "-nostdin", "-v", "error", "-y"]
    chain = ""
    if s.kind == "clip":
        cmd += ["-ss", f"{p['a']:.3f}", "-t", f"{p['span']:.3f}", "-i", REC / f"{s.src}.mp4"]
        chain = f"[0:v]setpts=(PTS-STARTPTS)/{p['speed']:.4f},fps={FPS},{zoom_filter(s.zoom, frames)}tpad=stop_mode=clone:stop_duration=120,format=yuv420p[v0]"
        n = 1
    elif s.kind == "phone":
        cmd += ["-loop", "1", "-framerate", str(FPS), "-i", paths["phonebg"], "-ss", f"{p['a']:.3f}", "-t", f"{p['span']:.3f}", "-i", ASSETS / "Firewatch-iPhone.mp4"]
        chain = (f"[1:v]setpts=(PTS-STARTPTS)/{p['speed']:.4f},fps={FPS},scale=-2:1000,tpad=stop_mode=clone:stop_duration=120[ph];"
                 f"[0:v][ph]overlay=1230:40:shortest=0,format=yuv420p[v0]")
        n = 2
    else:
        img = SLIDES / f"{s.src[6:]}.png" if s.src.startswith("slide:") else paths[s.src[5:]]
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", img]
        z = (1.0, 1.03, s.zoom[2], s.zoom[3]) if (s.drift and s.zoom[0] == s.zoom[1] == 1.0) else s.zoom
        frame = f"scale=1382:777:flags=lanczos,pad={W}:{H}:269:16:color=0x08090b," if s.src.startswith("slide:") else ""
        chain = f"[0:v]{frame}{zoom_filter(z, frames)}format=yuv420p[v0]"
        n = 1
    last, t = "v0", 0.0
    for i, c in enumerate(s.caps):
        slot = dur * p["reads"][i] / sum(p["reads"])
        t0, t1 = t, t + slot
        t = t1
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", f"{dur:.3f}", "-i", paths[(c.text, s.pos, c.chip, c.color)]]
        in_st = t0 + (0.0 if i == 0 else 0.0)
        chain += (f";[{n}:v]format=rgba,fade=t=in:st={in_st:.3f}:d=0.25:alpha=1,fade=t=out:st={max(t1 - 0.25, in_st + 0.3):.3f}:d=0.25:alpha=1[c{i}];"
                  f"[{last}][c{i}]overlay=0:0:format=auto:eof_action=pass[o{i}]")
        last = f"o{i}"
        n += 1
    fades = ""
    if fade_in:
        fades += f",fade=t=in:st=0:d={fade_in}"
    if fade_out:
        fades += f",fade=t=out:st={dur - fade_out:.3f}:d={fade_out}"
    chain += f";[{last}]format=yuv420p{fades}[vout]"
    cmd += ["-filter_complex", chain, "-map", "[vout]", "-frames:v", str(frames), "-r", str(FPS), "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p", "-an", out]
    run(cmd)
    return dur


def build(scenes: list[list[Shot]], out_name: str, tag: str) -> Path:
    """Render every shot, fade through black between scenes, and join them into out/<out_name>."""
    OUT.mkdir(exist_ok=True)
    sd = BUILD / f"shots-{tag}"
    sd.mkdir(parents=True, exist_ok=True)
    for old in sd.glob("*.mp4"):
        old.unlink()
    flat = [s for sc in scenes for s in sc]
    paths = ensure_cards(flat)
    jobs, k = [], 0
    for si, sc in enumerate(scenes):
        for j, s in enumerate(sc):
            fin = (1.2 if False else (0.8 if si == 0 else 0.25)) if j == 0 else 0.0
            fout = (1.2 if si == len(scenes) - 1 else 0.25) if j == len(sc) - 1 else 0.0
            jobs.append((s, k, sd / f"{k:03d}.mp4", fin, fout))
            k += 1
    with ThreadPoolExecutor(3) as ex:
        durs = list(ex.map(lambda a: render_shot(a[0], a[1], a[2], paths, a[3], a[4]), jobs))
    lst = sd / "list.txt"
    lst.write_text("".join(f"file '{j[2]}'\n" for j in jobs))
    out = OUT / out_name
    run([FFMPEG, "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out])
    total = sum(durs)
    print(f"{out.name}: {total:.1f} s, {out.stat().st_size / 1e6:.1f} MB, {len(jobs)} shots")
    (BUILD / f"{tag}-timeline.txt").write_text("\n".join(f"{i:03d} {sum(durs[:i]):7.1f}s {d:5.1f}s {jobs[i][0].src:14s} " + " | ".join(c.text for c in jobs[i][0].caps) for i, d in enumerate(durs)))
    return out


# The story ----------------------------------------------------------------------------------------------
HOOK = ("THE DAY", "Tue Mar 17 · red flag warning", C["amber"])
DET = lambda l: ("DETECT", l, C["amber"])
CON = lambda l: ("CONFIRM", l, C["sky"])
RES = lambda l: ("RESPOND", l, C["ember"])
RESULT = lambda l: ("RESULT", l, C["ok"])
TRUST = lambda l: ("TRUST", l, C["violet"])


def story() -> list[list[Shot]]:
    live, f3d = "live", "spread3d"
    return [
        # a) hook
        [Shot("still", "slide:sol-02", [
            Cap("1:50 pm. A power line falls into dry grass on a red flag day.", HOOK, C["amber"]),
            Cap("Nobody knows for 27 minutes. The first truck arrives at 2:52, 62 minutes later.", HOOK, C["amber"]),
        ], pos="left", zoom=(1.0, 1.0, 0.5, 0.45))],
        # b) the problem
        [Shot("still", "slide:sol-03", [
            Cap("Cottonwood Creek: 450 square miles, 18 volunteers, and only 5 can leave work on a weekday.", ("PROBLEM", "the chief's district", C["ember"])),
            Cap("One bar of cell signal. No fiber. Two permitted burns the same day make smoke look normal.", ("PROBLEM", "the chief's district", C["ember"])),
        ], zoom=(1.0, 1.0, 0.5, 0.45))],
        # c) how it works
        [
            Shot("still", "card:steps", [], hold=13),
            Shot("still", "slide:sol-09", [Cap("Built for one bar of signal: short texts get through, and the county radio pager needs no cell.", ("FIELD", "one bar, no fiber", C["sky"]), C["sky"])],
                 zoom=(1.0, 1.0, 0.5, 0.45)),
        ],
        # d) product in use
        [
            Shot("clip", live, [Cap("The packet's day, replayed in the dashboard. 1:50 pm: the co-op's line locks out.", DET("1:50 pm · line fault"), C["amber"])],
                 a="run", b="alert_opened", fit=True, pos="left", zoom=(1.0, 1.0, 0.5, 0.5)),
            Shot("clip", live, [Cap("The duty officer gets a text first. No reply in 3 minutes, so the chief gets one, with a link.", RES("1:50 to 1:53 pm · texts"), C["ember"])],
                 a="alert_opened", b="chief_page", fit=True, pos="left", zoom=(1.0, 1.0, 0.5, 0.5)),
            Shot("clip", live, [Cap("The chief texts PAGE. Volunteers text R for responding. We simulate those replies here.", RES("1:57 pm · the district is paged"), C["ember"])],
                 a="chief_page", b="scroll_texts", fit=True, zoom=(1.0, 1.0, 0.5, 0.5)),
            Shot("clip", live, [Cap("Every text is kept in the alert, in order, so nothing is lost on a busy afternoon.", RES("the alert's text log"), C["ember"])],
                 a="texts_visible+-2.5", b="texts_visible+3", fit=True, zoom=(1.35, 1.35, 0.85, 0.5), pos="left"),
            Shot("clip", f3d, [Cap("The 3D forecast shows the next 60 minutes. Change the wind and it redraws.", RES("spread forecast"), C["ember"])],
                 a="speed4", b="wind_set+3", fit=True, pos="left", zoom=(1.0, 1.0, 0.5, 0.5)),
            Shot("clip", f3d, [Cap("It is an estimate, not a prediction crews should bet on. The app says so on screen.", TRUST("honest about limits"), C["violet"])],
                 a="orbit", b="orbit+5", zoom=(1.0, 1.35, 0.3, 0.2), pos="right"),
            Shot("phone", "phone", [Cap("The chief's phone: one alert, big buttons, a map saved for no signal.", RES("in the truck"), C["ember"])],
                 a=33.0, b=62.0, fit=True, pos="left"),
            Shot("still", "card:phone", [], hold=9),
            Shot("clip", "board", [Cap("Neighbours can post what they see. Others confirm with one tap: I see it too.", DET("community board"), C["amber"])],
                 a="typed", b="confirm+2.5", fit=True, zoom=(1.0, 1.0, 0.5, 0.5), pos="left"),
        ],
        # e) results
        [
            Shot("clip", "timeline", [Cap("Today: seen at minute 27, 911 at 31, trucks on scene at 62, at about 830 acres.", RESULT("the old chain · replay"), C["ok"])],
                 a="today_lane", b="today_lane+6", zoom=(1.35, 1.35, 0.7, 0.1), pos="right"),
            Shot("clip", "timeline", [Cap("With Firewatch in this replay: paged at minute 7, on scene at 36, at about 270 acres.", RESULT("the new chain · replay"), C["ok"])],
                 a="firewatch_lane", b="worst_case+3", zoom=(1.35, 1.35, 0.7, 0.1), pos="right"),
            # Not deck slide sol-04: it still says "18 minutes sooner"; the replay gives 26.
            Shot("clip", "timeline", [Cap("That is 26 minutes sooner and about a third of the size. A simulated replay, not a real fire.", RESULT("what we can and cannot claim"), C["ok"])],
                 a="firewatch_lane", b="worst_case+3", zoom=(1.12, 1.12, 0.6, 0.12), pos="right"),
        ],
        # f) trust and false alarms
        [
            Shot("clip", "falsealarm", [Cap("Smoke is normal in March. Logged burns keep smoke near them quiet.", TRUST("false alarms"), C["violet"])],
                 a="suppressed_tab", b="burns_on_file+3", fit=True, zoom=(1.0, 1.0, 0.5, 0.5), pos="left"),
            Shot("still", "slide:sol-12", [
                Cap("When a feed fails, the screen says so. A gap is never shown as no fire.", TRUST("when it fails"), C["violet"]),
                Cap("A person decides, every override is logged, and 911 stays the main path.", TRUST("when it fails"), C["violet"]),
            ], zoom=(1.0, 1.0, 0.5, 0.45)),
        ],
        # g) cost
        [
            Shot("still", "slide:sol-14", [
                Cap("The district pays $0 for the software: free public data, hosted once for the region.", ("COST", "who pays", C["ok"]), C["ok"]),
                Cap("Camera detection runs about $50,000 per station per year. Co-ops pay for line sensors.", ("COST", "who pays", C["ok"]), C["ok"]),
            ], zoom=(1.0, 1.0, 0.5, 0.45)),
            Shot("clip", "planner", [Cap("Optional ground sensors: 10 plots, 90 nodes, about $14,200 of hardware (our estimate).", ("COST", "optional sensors", C["ok"]), C["ok"])],
                 a="map", b="plots10+2", fit=True, zoom=(1.0, 1.0, 0.5, 0.5), pos="right"),
        ],
        # h) close
        [
            Shot("still", "slide:sol-15", [Cap("The weather service reports 83 percent of satellite alerts beat the 911 call.", ("EVIDENCE", "reported by Wildfire Today", C["sky"]), C["sky"])],
                 zoom=(1.0, 1.0, 0.5, 0.45)),
            Shot("still", "slide:sol-15", [Cap("Next: pilot with an electric co-op, and measure how fast satellites see small fires.", ("NEXT", "what we build next", C["sky"]), C["sky"])],
                 zoom=(1.0, 1.0, 0.5, 0.45)),
            Shot("still", "card:close", [], hold=6),
        ],
    ]


if __name__ == "__main__":
    build(story(), "Firewatch-Story.mp4", "story")
