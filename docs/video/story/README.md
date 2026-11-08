# Firewatch videos

Reproducible, no-narration, captioned product videos. Story beats and final captions: [STORY.md](STORY.md).

- `out/Firewatch-Story.mp4`: the 2:42 story cut (hook, problem, three steps, product, results, trust, cost, close). `build/venv/bin/python build_video.py`
- `out/Firewatch-Tour.mp4`: the 2:34 feature tour, one segment per feature. `build/venv/bin/python build_tour.py`

Rebuild from scratch (backend on :8031 in sample mode with a scratch database, dashboard on :5181):

```
cd docs/video/story && npm install
python3 -m venv build/venv && build/venv/bin/pip install pymupdf pillow
build/venv/bin/python render_slides.py                 # deck PDFs -> build/slides/*.png
node rec_live.mjs && node rec_timeline.mjs && node rec_3d.mjs && node rec_board.mjs && node rec_planner.mjs && node rec_falsealarm.mjs
build/venv/bin/python build_video.py && build/venv/bin/python build_tour.py
build/venv/bin/python sheet.py live 5                  # contact sheet and marks for any recording
```

Recorders (`lib.mjs`: Chromium + CDP screencast at 1280x720 CSS px, device scale 1.5, drawn cursor, named marks):
`rec_live` runs the scenario and sends simulated texts, `rec_falsealarm` seeds two burns, `rec_board` makes one test post.
All texts are simulated (sample mode). Re-running `rec_live` replaces the scenario events and sample burns in the scratch
database, so record the others after it. The team's earlier pipeline (`../record_*.mjs`, `../build_video.py`, etc.) is separate and untouched.
