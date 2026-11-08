"""Firewatch feature tour (out/Firewatch-Tour.mp4): one segment per feature, in the order a chief would meet them.
Reuses the shot engine in build_video.py.   build/venv/bin/python build_tour.py"""

from build_video import C, Cap, Shot, build

FEAT = lambda n, name, col=C["ember"]: (f"FEATURE {n} OF 7", name, col)


def tour() -> list[list[Shot]]:
    L = "live"
    f1, f2, f3, f4, f5, f6, f7 = (FEAT(1, "live scenario"), FEAT(2, "false alarms", C["violet"]), FEAT(3, "3D spread preview", C["sky"]),
                                  FEAT(4, "community board", C["amber"]), FEAT(5, "FireNode planner", C["ok"]), FEAT(6, "results", C["ok"]), FEAT(7, "phone app", C["sky"]))
    return [
        [Shot("still", "card:tour", [], hold=7)],
        [
            Shot("clip", L, [Cap("Pick the packet scenario and press Run. The replay starts at 1:50 pm with a line fault.", f1)], a="run", b="alert_opened"),
            Shot("clip", L, [Cap("A text goes to the duty officer. With no reply in 3 minutes, the chief gets one too.", f1)], a="alert_opened", b="chief_page", speed=1.5),
            Shot("clip", L, [Cap("The chief replies PAGE and volunteers reply R. These replies are simulated for the demo.", f1)], a="chief_page", b="scroll_texts", speed=1.5),
            Shot("clip", L, [Cap("The alert keeps every text, in order.", f1)], a="texts_visible+-2.5", b="texts_visible+4", zoom=(1.35, 1.35, 0.85, 0.5)),
            Shot("clip", L, [Cap("The fire keeps growing while the replay runs. By minute 40 it is about 340 acres.", f1)], a="t=36", b="t=44", speed=3),
        ],
        [
            Shot("clip", "falsealarm", [Cap("The Suppressed tab holds alerts held back as likely prescribed burns, with the reason.", f2)], a="suppressed_tab", b="burn_log"),
            Shot("clip", "falsealarm", [Cap("Dispatch logs each permitted burn. Smoke near a logged burn stays quiet.", f2)], a="burn_log", b="burns_on_file+3.5"),
        ],
        [
            Shot("clip", "spread3d", [Cap("The 3D preview plays the next 60 minutes of spread across real terrain.", f3)], a="loaded", b="reset"),
            Shot("clip", "spread3d", [Cap("Override the wind with the sliders and the forecast redraws.", f3)], a="override", b="wind_set+3"),
            Shot("clip", "spread3d", [Cap("Drag to look around. It is an estimate, not an operational prediction.", f3)], a="orbit+-2", b="orbit+5", pos="right"),
        ],
        [
            Shot("clip", "board", [Cap("Neighbours post what they see: fire, smoke, hazard or a burn.", f4)], a="category", b="posted"),
            Shot("clip", "board", [Cap("Staff and neighbours confirm with one tap, or mark it a controlled burn.", f4)], a="scrolled", b="confirm+2.5"),
        ],
        [
            Shot("clip", "planner", [Cap("The planner shows which ground the likely fire starts cover.", f5)], a="start", b="plots20", pos="right"),
            Shot("clip", "planner", [Cap("Change the plot count: 10 plots is about $14,200 of hardware (our estimate).", f5)], a="plots20", b="scroll_results+3", pos="right"),
        ],
        [
            Shot("clip", "timeline", [Cap("Today: trucks on scene at minute 62, at about 830 acres.", f6)], a="today_lane", b="today_lane+6", zoom=(1.35, 1.35, 0.7, 0.1), pos="right"),
            Shot("clip", "timeline", [Cap("With Firewatch in this replay: on scene at minute 36, at about 270 acres.", f6)], a="firewatch_lane", b="worst_case+3", zoom=(1.35, 1.35, 0.7, 0.1), pos="right"),
        ],
        [
            Shot("phone", "phone", [Cap("The alert reaches the chief's phone, with a county map saved for no signal.", f7)], a=30.0, b=62.0, speed=1.6),
            Shot("still", "card:phone", [], hold=8),
        ],
    ]


if __name__ == "__main__":
    build(tour(), "Firewatch-Tour.mp4", "tour")
