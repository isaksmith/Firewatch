"""Builds the Firewatch story video (docs/video/firewatch-story.mp4): no narration, the story is told in
on-screen lines over the console replay, the 3D spread forecast, the sensor model and the pitch deck.

Each shot lasts as long as its lines take to read, so editing a line re-times the cut.
Inputs: recordings in build/rec (record_console.mjs, record_spread.mjs, record_viewer.mjs), the pitch deck
PDF, the phone screenshots and the sensor intro video. Text cards are HTML rendered by render_cards.mjs.

    (cd docs/video && npm install) && python3 docs/video/build_video.py
"""

from __future__ import annotations

import base64
import html
import io
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz
from PIL import Image

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
BUILD = HERE / "build"
REC = BUILD / "rec"
OUT = HERE / "firewatch-story.mp4"
DECK = REPO / "docs/pitch/Firewatch-Pitch.pdf"
INTRO = REPO / "sensors/video/firewatch-sensor-intro.mp4"
W, H, FPS = 1920, 1080, 30

LEAD, GAP, TAIL, FADE, TEXT_FADE = 0.5, 0.2, 0.6, 0.3, 0.25
CONSOLE_LAG = 1.45  # the console polls, so it shows a minute about this long after the API reports it
C = dict(void="#050607", bg="#08090B", text="#F2F4F5", muted="#9BA3AB", ember="#FF4B2B", amber="#FFB21A", ok="#3DDC97", sky="#5CC8FF")


@dataclass
class Shot:
    kind: str  # clip | still
    src: str  # recording name, file path, "slide:N" or a composite name
    lines: list[str] = field(default_factory=list)
    a: float = 0.0  # clip start in seconds, or scenario minute when minutes=True
    b: float | None = None  # clip end; None plays at 1x from a
    minutes: bool = False
    zoom: tuple = (1.0, 1.0, 0.5, 0.5)  # z_start, z_end, centre x, centre y (fractions of the frame)
    chip: tuple | None = None  # (tag, text, colour)
    hold: float = 0.0  # seconds on screen beyond its lines (the whole duration when there are none)
    to: str | None = None  # play at `speed` from mark `a@...` to this mark, holding the last frame if the lines need longer
    speed: float = 1.0
    pos: str = "left"  # where the lines sit: left | right


HOOK_CHIP = ("SCENARIO", "Comanche County, Kansas · red-flag Tuesday", C["ember"])

SCENES: list[list[Shot]] = [
    [
        Shot("clip", "spread", a=0, b=0.5, zoom=(1.0, 1.1, 0.5, 0.47), chip=HOOK_CHIP, lines=[
            "1:50 PM. A power line falls into dry grass.",
        ]),
        Shot("clip", "spread", a=0.5, b=6.0, zoom=(1.1, 1.3, 0.5, 0.47), chip=HOOK_CHIP, lines=[
            "For 27 minutes, nobody sees it.",
        ]),
        Shot("clip", "spread", a=6.0, b=15.6, zoom=(1.3, 1.55, 0.5, 0.47), chip=HOOK_CHIP, lines=[
            "The first truck arrives an hour later, to a fire 2–3 miles long.",
        ]),
    ],
    [Shot("still", "slide:1", zoom=(1.0, 1.03, 0.5, 0.5), hold=4.5)],
    [Shot("still", "slide:2", zoom=(1.0, 1.03, 0.5, 0.45), hold=9)],
    [Shot("still", "slide:3", zoom=(1.0, 1.03, 0.5, 0.45), hold=10)],
    [
        Shot("clip", "console", a=0.8, b=2.5, minutes=True, lines=[
            "The same fire, replayed in the Firewatch console.",
        ]),
        Shot("clip", "console", a=2.5, b=7.8, minutes=True, zoom=(1.0, 1.7, 0.85, 0.55), chip=("DETECT", "1:50 PM · line lockout", C["amber"]), lines=[
            "The co-op's line locks out on a red-flag day. Firewatch opens an event and texts the nearest neighbors: see smoke?",
        ]),
        Shot("clip", "console", a=7.8, b=8.9, minutes=True, zoom=(1.7, 1.7, 0.85, 0.55), chip=("CONFIRM", "1:58 PM · a neighbor replies", C["sky"]), lines=[
            "A rancher a mile east replies 1: he sees smoke. Two independent signals, so it escalates.",
        ]),
        Shot("clip", "console", a=8.9, b=13.5, minutes=True, zoom=(1.0, 2.0, 0.14, 0.4), chip=("RESPOND", "1:59 PM · the duty officer pages", C["ember"]), lines=[
            "The duty officer replies PAGE. Volunteers, downwind ranchers and mutual aid get the word by text.",
        ]),
        Shot("clip", "console", a=13.5, b=40, minutes=True, zoom=(1.0, 1.6, 0.33, 0.12), lines=[
            "The satellite doesn't see it until minute 38, when the first truck is already on scene.",
        ]),
    ],
    [Shot("still", "slide:5", zoom=(1.0, 1.03, 0.5, 0.4), hold=9)],
    [Shot("still", "slide:6", zoom=(1.0, 1.03, 0.4, 0.45), hold=9)],
    [Shot("still", "phones", zoom=(1.0, 1.04, 0.62, 0.45), hold=8)],
    [
        Shot("clip", "viewer", a=0.3, chip=("SENSOR NODE", "CAD revision 2 · optional", C["ok"]), lines=[
            "Optional ground sensors: solar powered, on a pole or a stake. No power line, no cell signal.",
        ]),
        Shot("clip", "viewer@explode", a=0.0, chip=("SENSOR NODE", "CAD revision 2 · optional", C["ok"]), lines=[
            "Inside: gas and weather sensing, a battery and a long-range radio. The rich model adds a smoke sensor.",
        ]),
        Shot("clip", str(INTRO), a=62.6, b=67.4, zoom=(1.2, 1.28, 0.5, 0.42), lines=[
            "When it smells smoke, it radios the station. Firewatch still waits for a second signal before anyone is paged.",
        ]),
        Shot("still", "slide:8", zoom=(1.0, 1.03, 0.5, 0.45), hold=8),
    ],
    [Shot("still", "slide:9", zoom=(1.0, 1.03, 0.5, 0.45), hold=8)],
    [Shot("still", "slide:10", zoom=(1.0, 1.03, 0.5, 0.45), hold=7)],
    [Shot("still", "slide:11", zoom=(1.0, 1.04, 0.5, 0.45), hold=6)],
]


def run(cmd: list) -> None:
    subprocess.run([str(c) for c in cmd], check=True)


def read_time(text: str) -> float:
    return max(2.8, 1.0 + 0.3 * len(text.split()))


# Recordings ------------------------------------------------------------------------------------------

_recordings: dict[str, tuple[Path, dict]] = {}


def recording(name: str) -> tuple[Path, dict]:
    """The CDP frames of a recording as a constant-rate mp4, plus its marks in clip seconds."""
    if name in _recordings:
        return _recordings[name]
    data = json.loads((REC / f"{name}.json").read_text())
    frames = []
    for x in sorted(data["frames"], key=lambda x: x["ts"]):  # screencast frames can arrive out of order
        if not frames or x["ts"] > frames[-1]["ts"]:
            frames.append(x)
    t0 = frames[0]["ts"]
    out = BUILD / f"{name}.mp4"
    if not out.exists() or out.stat().st_mtime < (REC / f"{name}.json").stat().st_mtime:
        lst = BUILD / f"{name}.ffconcat"
        with lst.open("w") as f:
            f.write("ffconcat version 1.0\n")
            for x, y in zip(frames, frames[1:]):
                f.write(f"file '{x['f']}'\nduration {y['ts'] - x['ts']:.4f}\n")
            f.write(f"file '{frames[-1]['f']}'\nduration 0.1\nfile '{frames[-1]['f']}'\n")
        run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
             "-vf", f"fps={FPS},format=yuv420p", "-c:v", "libx264", "-crf", "16", "-preset", "fast", out])
    marks = [{**m, "t": m["ts"] - t0} for m in data.get("marks", [])]
    _recordings[name] = (out, {"marks": marks})
    return _recordings[name]


def scenario_time(marks: list[dict], minute: float) -> float:
    """Clip seconds at which the console shows a scenario minute, interpolated between the logged clock ticks."""
    ticks = sorted((m["t_min"], m["t"] + CONSOLE_LAG) for m in marks if m["what"] == "t")
    if minute <= ticks[0][0]:
        return ticks[0][1]
    for (m0, t0), (m1, t1) in zip(ticks, ticks[1:]):
        if m0 <= minute <= m1:
            return t0 + (t1 - t0) * (minute - m0) / (m1 - m0)
    return ticks[-1][1]


def clip_source(shot: Shot) -> tuple[Path, float, float | None]:
    if Path(shot.src).is_absolute():
        return Path(shot.src), shot.a, shot.b
    name, _, at = shot.src.partition("@")
    path, info = recording(name)
    if shot.minutes:
        return path, scenario_time(info["marks"], shot.a), scenario_time(info["marks"], shot.b)
    mark = lambda what: next(m["t"] for m in info["marks"] if m["what"] == what)  # noqa: E731
    offset = mark(at) if at else 0.0
    if shot.to:
        return path, offset + shot.a, mark(shot.to)
    return path, offset + shot.a, None if shot.b is None else offset + shot.b


# Cards -----------------------------------------------------------------------------------------------

def data_uri(path: Path, width: int) -> str:
    im = Image.open(path).convert("RGB")
    im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


PAGE = f"<html><body style='margin:0;width:{W}px;height:{H}px;background:transparent;font-family:Arial,Helvetica,sans-serif;-webkit-font-smoothing:antialiased'>{{}}</body></html>"
MONO = "Menlo,monospace"


def line_card(text: str, chip: tuple | None, pos: str = "left") -> str:
    colour = chip[2] if chip else C["ember"]
    top = ""
    if chip:
        top = (f"<div style='display:inline-flex;align-items:center;gap:16px;margin-bottom:14px;background:rgba(5,6,7,.88);padding:9px 18px 9px 9px;border-radius:4px'>"
               f"<span style='background:{colour};color:{C['void']};font:700 21px {MONO};letter-spacing:3px;padding:6px 12px;border-radius:3px'>{html.escape(chip[0])}</span>"
               f"<span style='color:{C['text']};font:700 21px {MONO};letter-spacing:2px;text-transform:uppercase'>{html.escape(chip[1])}</span></div><br>")
    body = (f"<div style='display:inline-block;background:rgba(5,6,7,.88);border-left:7px solid {colour};padding:22px 32px;"
            f"color:{C['text']};font-size:44px;line-height:1.28;font-weight:700;max-width:1240px;text-align:left'>{html.escape(text)}</div>")
    side = "left:80px" if pos == "left" else "right:80px;text-align:right"
    return PAGE.format(f"<div style='position:absolute;{side};bottom:76px;max-width:1240px'>{top}{body}</div>")


def phones_card() -> str:
    shots = ["08-home-radio-alert.png", "09-alert-by-radio.png", "10-board.png"]
    phones = "".join(
        f"<img src='{data_uri(REPO / 'mobile/shots' / s, 600)}' style='height:780px;border-radius:30px;border:3px solid #2A3038'>"
        for s in shots)
    rows = [
        (C["sky"], "Plain text messages", "Reply PAGE, 1, 2 or 3. Works on any phone, about 1 cent a text."),
        (C["ok"], "Mesh radios", "Meshtastic LoRa radios carry the same texts to trucks and ranches with no cell at all. Tested on real radios."),
        (C["amber"], "Phone app", "Alerts by text or radio, an offline map of where it's heading, and a board for neighbors' reports."),
    ]
    items = "".join(
        f"<div style='margin-top:42px;border-left:6px solid {c};padding-left:22px'>"
        f"<div style='font-size:34px;font-weight:700;color:{C['text']}'>{h}</div>"
        f"<div style='font-size:25px;line-height:1.4;color:{C['muted']};margin-top:8px'>{t}</div></div>"
        for c, h, t in rows)
    left = (f"<div style='width:600px;flex:none'><div style='font:700 21px {MONO};letter-spacing:4px;color:{C['sky']}'>BUILT FOR ONE BAR OF CELL</div>"
            f"<div style='font-size:62px;font-weight:700;line-height:1.1;color:{C['text']};margin-top:18px'>Reaches people where cell doesn't</div>{items}</div>")
    return (f"<html><body style='margin:0;width:{W}px;height:{H}px;background:{C['bg']};font-family:Arial,Helvetica,sans-serif;"
            f"display:flex;align-items:center;justify-content:space-between;padding:0 90px;box-sizing:border-box'>"
            f"{left}<div style='display:flex;gap:26px'>{phones}</div></body></html>")


def render_cards(cards: list[dict], work: Path) -> None:
    spec = work / "cards.json"
    spec.write_text(json.dumps(cards))
    run(["node", HERE / "render_cards.mjs", spec])


def render_slides() -> None:
    doc = fitz.open(DECK)
    for i, page in enumerate(doc, start=1):
        zoom = W / page.rect.width
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(BUILD / "img" / f"slide-{i}.png")


def still_path(src: str) -> Path:
    if src.startswith("slide:"):
        return BUILD / "img" / f"slide-{src.split(':')[1]}.png"
    return BUILD / "img" / f"{src}.png"


# Shots -----------------------------------------------------------------------------------------------

def plan(scenes: list[list[Shot]], work: Path) -> list[dict]:
    """Every shot with its duration and the on-screen windows of its lines."""
    out = []
    for si, scene in enumerate(scenes):
        for hi, shot in enumerate(scene):
            first, last = hi == 0, hi == len(scene) - 1
            lead = LEAD if first else 0.15
            reads = [read_time(t) for t in shot.lines]
            text = sum(reads) + GAP * max(0, len(reads) - 1)
            dur = (lead + text if reads else 0.0) + shot.hold + (TAIL if last and reads else 0.0)
            if shot.to:
                _, a, b = clip_source(shot)
                dur = max(dur, (b - a) / shot.speed)
            dur = round(max(dur, 1.0) * FPS) / FPS
            # Lines share whatever time the shot has, in proportion to how long each takes to read.
            room = dur - lead - (TAIL if last else 0.3)
            stretch = max(1.0, room / text) if reads else 1.0
            lines, t = [], lead
            for li, (txt, d) in enumerate(zip(shot.lines, reads)):
                lines.append({"text": txt, "s": t, "e": t + d * stretch, "png": work / "cards" / f"s{si:02d}-{hi}-{li}.png"})
                t += (d + GAP) * stretch
            out.append({"shot": shot, "scene": si, "last_scene": si == len(scenes) - 1, "dur": dur, "lines": lines,
                        "fade_in": first, "fade_out": last, "out": work / "shots" / f"s{si:02d}-{hi}.mp4"})
    return out


def render_shot(p: dict) -> None:
    shot, dur = p["shot"], p["dur"]
    n = round(dur * FPS)
    args = ["ffmpeg", "-nostdin", "-v", "error", "-y"]
    if shot.kind == "clip":
        src, a, b = clip_source(shot)
        if shot.to:
            length = b - a
            args += ["-ss", f"{a:.3f}", "-t", f"{length + 0.2:.3f}", "-i", src]
            chain = (f"[0:v]setpts=(PTS-STARTPTS)/{shot.speed},fps={FPS},tpad=stop_mode=clone:stop_duration={dur + 1:.2f},"
                     f"scale={W}:{H}:flags=lanczos,setsar=1")
        else:
            length = dur if b is None else b - a
            k = dur / length
            if not 0.12 <= k <= 8:
                print(f"  warning: {shot.src} {shot.a}-{shot.b} plays at {1 / k:.2f}x")
            args += ["-ss", f"{a:.3f}", "-t", f"{length + 0.5:.3f}", "-i", src]
            chain = f"[0:v]setpts=(PTS-STARTPTS)*{k:.5f},fps={FPS},tpad=stop_mode=clone:stop_duration=1,scale={W}:{H}:flags=lanczos,setsar=1"
    else:
        args += ["-loop", "1", "-framerate", FPS, "-t", f"{dur + 0.5:.3f}", "-i", still_path(shot.src)]
        chain = f"[0:v]fps={FPS},scale={W}:{H}:flags=lanczos,setsar=1"
    z0, z1, cx, cy = shot.zoom
    if (z0, z1) != (1.0, 1.0):
        ease = f"(0.5-0.5*cos(PI*min(1,on/{n})))"
        chain += (f",scale={2 * W}:{2 * H}:flags=lanczos,zoompan=z='{z0}+({z1 - z0})*{ease}'"
                  f":x='max(0,min(iw-iw/zoom,{cx}*iw-iw/zoom/2))':y='max(0,min(ih-ih/zoom,{cy}*ih-ih/zoom/2))'"
                  f":d=1:s={W}x{H}:fps={FPS}")
    chain += f",trim=end_frame={n},setpts=PTS-STARTPTS,format=yuv420p[v0]"
    graph = [chain]
    for j, ln in enumerate(p["lines"], start=1):
        s, e = ln["s"], ln["e"]
        args += ["-loop", "1", "-framerate", FPS, "-t", f"{dur + 0.5:.3f}", "-i", ln["png"]]
        graph.append(f"[{j}:v]format=rgba,fade=t=in:st={s:.3f}:d={TEXT_FADE}:alpha=1,"
                     f"fade=t=out:st={e - TEXT_FADE:.3f}:d={TEXT_FADE}:alpha=1[c{j}]")
        graph.append(f"[v{j - 1}][c{j}]overlay=0:0:enable='between(t,{s:.3f},{e:.3f})'[v{j}]")
    last = f"v{len(p['lines'])}"
    fades = []
    if p["fade_in"]:
        fades.append(f"fade=t=in:st=0:d={0.8 if p['scene'] == 0 else FADE}")
    if p["fade_out"]:
        d = 1.2 if p["last_scene"] else FADE
        fades.append(f"fade=t=out:st={dur - d:.3f}:d={d}")
    graph.append(f"[{last}]{','.join(fades + ['format=yuv420p'])}[out]")
    args += ["-filter_complex", ";".join(graph), "-map", "[out]", "-frames:v", n, "-r", FPS,
             "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p", p["out"]]
    run(args)


def build(scenes: list[list[Shot]], out: Path, cut: str) -> None:
    work = BUILD / cut
    for d in ("cards", "shots"):
        shutil.rmtree(work / d, ignore_errors=True)
        (work / d).mkdir(parents=True)
    (BUILD / "img").mkdir(parents=True, exist_ok=True)
    render_slides()
    shots = plan(scenes, work)
    cards = [{"out": str(BUILD / "img" / "phones.png"), "html": phones_card()}]
    for p in shots:
        for ln in p["lines"]:
            cards.append({"out": str(ln["png"]), "html": line_card(ln["text"], p["shot"].chip, p["shot"].pos), "transparent": True})
    render_cards(cards, work)
    for i, p in enumerate(shots, start=1):
        print(f"shot {i}/{len(shots)}: {p['shot'].src} {p['dur']:.1f} s")
        render_shot(p)
    lst = work / "shots.txt"
    lst.write_text("".join(f"file '{p['out']}'\n" for p in shots))
    run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", "-movflags", "+faststart", out])
    print(f"{out.relative_to(REPO)}: {sum(p['dur'] for p in shots):.1f} s")


if __name__ == "__main__":
    build(SCENES, OUT, "story")
