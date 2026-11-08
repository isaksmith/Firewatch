# Firewatch product video: story beats

No narration. One idea per caption, plain words, at most about 20 words. Every number comes from
`backend/data/scenarios/cottonwood-creek-packet.json`, `GET /api/scenario/cottonwood-creek-packet`,
`docs/RESEARCH.md`, `docs/COMPETITOR_PACKET.md`, the deck, or the planner screen (labelled "our estimate").
Judges rank: whole chain > field reality > built for a real district > honest numbers > evidence > next step.

| Beat | Picture | Captions |
|---|---|---|
| a. Hook | Deck: the 62-minute timeline | "1:50 pm. A power line falls into dry grass on a red flag day." / "Nobody knows for 27 minutes. The first truck arrives at 2:52, 62 minutes later." |
| b. Problem | Deck: three barriers | "Cottonwood Creek: 450 square miles, 18 volunteers, and only 5 can leave work on a weekday." / "One bar of cell signal. No fiber. Two permitted burns the same day make smoke look normal." |
| c. How it works | Card: detect, confirm, respond; deck: one bar of signal | (card text) / "Built for one bar of signal: short texts get through, and the county radio pager needs no cell." |
| d. Product in use | Live dashboard replay, 3D forecast, phone, community board | "The packet's day, replayed in the dashboard. 1:50 pm: the co-op's line locks out." / "The duty officer gets a text first. No reply in 3 minutes, so the chief gets one, with a link." / "The chief texts PAGE. Volunteers text R for responding. We simulate those replies here." / "Every text is kept in the alert, in order, so nothing is lost on a busy afternoon." / "The 3D forecast shows the next 60 minutes. Change the wind and it redraws." / "It is an estimate, not a prediction crews should bet on. The app says so on screen." / "The chief's phone: one alert, big buttons, a map saved for no signal." / "Neighbours can post what they see. Others confirm with one tap: I see it too." |
| e. Results | Scenario strip, Today lane versus Firewatch lane | "Today: seen at minute 27, 911 at 31, trucks on scene at 62, at about 830 acres." / "With Firewatch in this replay: paged at minute 7, on scene at 36, at about 270 acres." / "That is 26 minutes sooner and about a third of the size. A simulated replay, not a real fire." |
| f. Trust and false alarms | Burn log, Suppressed tab, deck: when a feed fails | "Smoke is normal in March. Logged burns keep smoke near them quiet." / "When a feed fails, the screen says so. A gap is never shown as no fire." / "A person decides, every override is logged, and 911 stays the main path." |
| g. Cost | Deck: who pays; FireNode planner | "The district pays $0 for the software: free public data, hosted once for the region." / "Camera detection runs about $50,000 per station per year. Co-ops pay for line sensors." / "Optional ground sensors: 10 plots, 90 nodes, about $14,200 of hardware (our estimate)." |
| h. Close | Deck: evidence and next steps; closing card | "The weather service reports 83 percent of satellite alerts beat the 911 call." / "Next: pilot with an electric co-op, and measure how fast satellites see small fires." |

The tour cut (`build_tour.py`) walks the same footage feature by feature with a caption per step.
