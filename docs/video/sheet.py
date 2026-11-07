"""Contact sheet of a recording, with its marks, for checking a take: python3 docs/video/sheet.py tour-console [seconds per tile]"""

import subprocess
import sys

from build_video import BUILD, recording

name = sys.argv[1]
every = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
path, info = recording(name)
out = BUILD / f"{name}-sheet.png"
subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(path), "-vf", f"fps=1/{every},scale=480:-1,tile=6x6", "-frames:v", "1", str(out)], check=True)
print(out)
print(" ".join(f"{m['what']}{'=' + str(m['t_min']) if 't_min' in m else ''}@{m['t']:.1f}" for m in info["marks"] if m["what"] != "t" or m["t_min"] % 5 == 0))
