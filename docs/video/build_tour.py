"""Builds the tour cut (docs/video/firewatch-tour.mp4): the story's opening, then each feature of the site in use,
recorded by record_tour.mjs. Same machinery and style as build_video.py.

    (cd docs/video && npm install && node record_tour.mjs all) && python3 docs/video/build_tour.py
"""

from build_video import C, HERE, INTRO, SCENES as STORY, Shot, build

CONSOLE = ("CONSOLE", "statewide queue and map", C["sky"])
REPLAY = ("SATELLITE REPLAY", "real detections, real scorer", C["amber"])
DRAWER = ("ALERT", "one fire, every reason", C["sky"])
FORECAST = ("FIRE FORECAST", "2D map", C["amber"])
SPREAD = ("3D SPREAD", "terrain view", C["amber"])
BURNS = ("BURN LOG", "registered burns stay quiet", C["ok"])
LOWDATA = ("LOW DATA", "built for one bar of cell", C["sky"])
BOARD = ("COMMUNITY BOARD", "public page", C["sky"])
PLANNER = ("PLANNER", "any Kansas county", C["ok"])

TOUR: list[list[Shot]] = [
    STORY[0],
    [Shot("still", "slide:1", zoom=(1.0, 1.03, 0.5, 0.5), hold=4)],
    [Shot("still", "slide:2", zoom=(1.0, 1.03, 0.5, 0.45), hold=7.5)],
    [Shot("still", "slide:3", zoom=(1.0, 1.03, 0.5, 0.45), hold=8)],
    [
        Shot("clip", "tour-console@start", to="tabs", chip=CONSOLE, lines=[
            "Every satellite hotspot, power-line fault and neighbor report in Kansas, scored and ranked in one queue.",
        ]),
        Shot("clip", "tour-console@tabs", to="layers", speed=1.3, chip=CONSOLE, lines=[
            "Escalate holds what needs a decision. Suppressed keeps refinery flares and prescribed burns off the queue.",
        ]),
        Shot("clip", "tour-console@layers", to="end", speed=1.5, chip=CONSOLE, lines=[
            "Layers add the Flint Hills, lines under strong wind, a dry-air grid and live weather alerts.",
        ]),
    ],
    [Shot("clip", "tour-replay@running", to="end", speed=3.0, chip=REPLAY, lines=[
        "Satellite replay feeds a real run of Kansas detections through the scorer, pass by pass.",
        "Wildfires rise to the top. Known heat sources and prescribed burns drop to Suppressed.",
    ])],
    [
        Shot("clip", "tour-drawer@start", to="how", chip=DRAWER, lines=[
            "Open any alert for its score, the evidence behind it and the weather at the fire.",
        ]),
        Shot("clip", "tour-drawer@how", to="end", speed=2.0, chip=DRAWER, lines=[
            "Why this score, nearby assets, every satellite hit and a full log: what a duty officer needs to decide.",
        ]),
    ],
    [
        Shot("clip", "tour-scenario", a=0.6, b=7.8, minutes=True, chip=("DETECT", "1:50 PM · line lockout", C["amber"]), lines=[
            "Run scenario replays the packet's fire. The co-op's line locks out; Firewatch opens an event and asks the neighbors.",
        ]),
        Shot("clip", "tour-scenario", a=7.8, b=9.0, minutes=True, zoom=(1.6, 1.6, 0.85, 0.55), chip=("CONFIRM", "1:58 PM · a neighbor replies", C["sky"]), lines=[
            "Minute 8: a rancher replies 1, he sees smoke. Two independent signals, so it escalates.",
        ]),
        Shot("clip", "tour-scenario", a=9.0, b=14.5, minutes=True, chip=("RESPOND", "1:59 PM · the duty officer pages", C["ember"]), lines=[
            "Minute 9: the duty officer replies PAGE. The response panel shows each step taken and what's still waiting.",
        ]),
        Shot("clip", "tour-scenario", a=14.5, b=22, minutes=True, chip=("RESPOND", "every text logged", C["ember"]), lines=[
            "Every text in and out is on the event: the page, downwind warnings, volunteers answering.",
        ]),
        Shot("clip", "tour-scenario", a=22, b=62, minutes=True, zoom=(1.0, 1.6, 0.33, 0.12), lines=[
            "The strip compares the same fire today and with Firewatch: paged at minute 9, not 31.",
        ]),
    ],
    [
        Shot("clip", "tour-forecast@start", to="3d", speed=1.4, chip=FORECAST, lines=[
            "Drag the forecast to see where the fire is likely to be over the next hour, and the worst case.",
        ]),
        Shot("clip", "tour-forecast@3d", to="override", speed=1.3, chip=SPREAD, lines=[
            "The 3D view plays the forecast on real terrain, with the towns, lines and substations it could reach.",
        ]),
        Shot("clip", "tour-forecast@override", to="orbit", speed=1.5, chip=SPREAD, lines=[
            "Change the wind and the forecast runs again.",
        ]),
        Shot("clip", "tour-forecast@orbit", to="end", speed=1.5, chip=SPREAD, lines=[
            "Tilt and turn to see the ground crews will face.",
        ]),
    ],
    [Shot("still", "slide:5", zoom=(1.0, 1.03, 0.5, 0.4), hold=8)],
    [
        Shot("clip", "tour-burns@start", to="lowdata", speed=1.3, chip=BURNS, pos="left", lines=[
            "When a rancher calls in a controlled burn, it's logged, and that burn texts nobody unless it escapes.",
        ]),
        Shot("clip", "tour-burns@lowdata", to="end", speed=1.5, chip=LOWDATA, lines=[
            "Low data mode drops map pictures and slows updates when the connection is weak.",
        ]),
    ],
    [Shot("clip", "tour-board@start", to="end", speed=1.5, zoom=(1.3, 1.3, 0.5, 0.36), chip=BOARD, pos="left", lines=[
        "The public board: residents report fire or smoke from any phone, no app needed.",
    ])],
    [Shot("still", "phones", zoom=(1.0, 1.04, 0.62, 0.45), hold=7)],
    [
        Shot("clip", "tour-planner@start", to="plots", chip=PLANNER, pos="right", lines=[
            "The region planner places sensor plots where fires start and where wind carries their smoke. Each plot says why.",
        ]),
        Shot("clip", "tour-planner@plots", to="budget", chip=PLANNER, pos="right", lines=[
            "Ask for fewer plots and it re-plans, with coverage and cost.",
        ]),
        Shot("clip", "tour-planner@budget", to="county", speed=1.3, chip=PLANNER, pos="right", lines=[
            "Or start from a budget.",
        ]),
        Shot("clip", "tour-planner@county", to="scroll", speed=1.4, chip=PLANNER, pos="right", lines=[
            "Pick any Kansas county: terrain, ten years of fires and hourly winds are pulled in for it.",
        ]),
        Shot("clip", "tour-planner@scroll", to="end", speed=1.6, chip=PLANNER, pos="right", lines=[
            "Fire-weather climate, solar power in the worst week, relays, and a full bill of materials.",
        ]),
    ],
    STORY[8][:3] + [Shot("still", "slide:8", zoom=(1.0, 1.03, 0.5, 0.45), hold=6)],
    [Shot("still", "slide:10", zoom=(1.0, 1.03, 0.5, 0.45), hold=6)],
    [Shot("still", "slide:11", zoom=(1.0, 1.04, 0.5, 0.45), hold=6)],
]

if __name__ == "__main__":
    build(TOUR, HERE / "firewatch-tour.mp4", "tour")
