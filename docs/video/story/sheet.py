"""Contact sheet of a recording plus its marks: python3 sheet.py <name> [seconds per tile]"""
import json, subprocess, sys
from pathlib import Path
REC = Path(__file__).resolve().parent / "build/rec"
name = sys.argv[1]; every = sys.argv[2] if len(sys.argv) > 2 else "2"
out = REC.parent / f"{name}-sheet.png"
subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(REC / f"{name}.mp4"), "-vf", f"fps=1/{every},scale=480:-1,tile=5x5", "-frames:v", "1", str(out)], check=True)
d = json.loads((REC / f"{name}.json").read_text())
print(out, "ok" if d.get("ok") else "FAILED", round(d["duration"], 1), "s")
print(" ".join(f"{m['what']}@{m['t']:.1f}" for m in d["marks"] if m["what"] != "t"))
