"""Firewatch short cut (out/Firewatch-Short.mp4): every feature in under 2 minutes, one short caption per shot.
Reuses the shot engine and recordings of build_video.py.   build/venv/bin/python build_short.py"""

from build_video import C, Cap, Shot, build

HOOK = ("THE DAY", "Tue Mar 17 · red flag warning", C["amber"])
F = lambda n, name, col: (f"{n} OF 7", name, col)


def short() -> list[list[Shot]]:
    live, f3d = "live", "spread3d"
    f1, f2, f3, f4, f5, f6, f7 = (F(1, "live alert and texts", C["ember"]), F(2, "false alarms", C["violet"]), F(3, "3D spread preview", C["sky"]),
                                  F(4, "community board", C["amber"]), F(5, "FireNode planner", C["ok"]), F(6, "phone app", C["sky"]), F(7, "results", C["ok"]))
    return [
        [
            Shot("still", "slide:sol-02", [Cap("1:50 pm, red flag day: a downed power line starts a grass fire. Trucks arrive 62 minutes later.", HOOK, C["amber"])],
                 zoom=(1.0, 1.0, 0.5, 0.45)),
            Shot("still", "slide:sol-03", [Cap("Cottonwood Creek: 450 square miles, 18 volunteers, one bar of signal.", ("PROBLEM", "the chief's district", C["ember"]))],
                 zoom=(1.0, 1.0, 0.5, 0.45)),
        ],
        [Shot("still", "card:steps", [], hold=8)],
        [
            Shot("clip", live, [Cap("The packet's day, replayed. 1:50 pm: the co-op's line locks out.", f1, C["ember"])],
                 a="run", b="alert_opened", fit=True),
            Shot("clip", live, [Cap("The duty officer is texted first. No reply in 3 minutes, so the chief is texted too.", f1, C["ember"])],
                 a="alert_opened", b="chief_page", fit=True),
            Shot("clip", live, [Cap("The chief texts PAGE. Volunteers text R. Replies are simulated here.", f1, C["ember"])],
                 a="chief_page", b="scroll_texts", speed=2.5),
            Shot("clip", live, [Cap("Every text is kept in the alert, in order.", f1, C["ember"])],
                 a="texts_visible+-2.5", b="texts_visible+3", fit=True, zoom=(1.35, 1.35, 0.85, 0.5)),
        ],
        [Shot("clip", "falsealarm", [Cap("Dispatch logs permitted burns, so smoke near them stays quiet.", f2, C["violet"])],
              a="suppressed_tab", b="burns_on_file+3", speed=2.5)],
        [Shot("clip", f3d, [Cap("The next 60 minutes of spread in 3D. Change the wind and it redraws. An estimate, and it says so.", f3, C["sky"])],
              a="speed4", b="wind_set+3", fit=True)],
        [Shot("clip", "board", [Cap("Neighbours post what they see. Others confirm with one tap.", f4, C["amber"])],
              a="typed", b="confirm+2.5", fit=True)],
        [Shot("clip", "planner", [Cap("Optional ground sensors: 10 plots, about $14,200 of hardware (our estimate).", f5, C["ok"])],
              a="map", b="plots10+2", fit=True, pos="right")],
        [
            Shot("phone", "phone", [Cap("The chief's phone: one alert, big buttons, a map saved for no signal.", f6, C["sky"])],
                 a=33.0, b=62.0, speed=2.5),
            Shot("still", "card:phone", [], hold=5),
        ],
        [
            Shot("clip", "timeline", [Cap("Today: trucks on scene at minute 62, at about 830 acres.", f7, C["ok"])],
                 a="today_lane", b="today_lane+6", fit=True, zoom=(1.35, 1.35, 0.7, 0.1), pos="right"),
            Shot("clip", "timeline", [Cap("With Firewatch in this replay: on scene at minute 36, at about 270 acres.", f7, C["ok"]),
                                      Cap("26 minutes sooner, a third of the size. A simulated replay, not a real fire.", f7, C["ok"])],
                 a="firewatch_lane", b="worst_case+3", fit=True, zoom=(1.35, 1.35, 0.7, 0.1), pos="right"),
        ],
        [
            Shot("still", "slide:sol-12", [Cap("If a feed fails, the screen says so. A person decides, and 911 stays the main path.", ("TRUST", "when it fails", C["violet"]), C["violet"])],
                 zoom=(1.0, 1.0, 0.5, 0.45)),
            Shot("still", "slide:sol-14", [Cap("The district pays $0 for the software: free public data, hosted once for the region.", ("COST", "who pays", C["ok"]), C["ok"])],
                 zoom=(1.0, 1.0, 0.5, 0.45)),
            Shot("still", "card:close", [], hold=5),
        ],
    ]


if __name__ == "__main__":
    build(short(), "Firewatch-Short.mp4", "short")
