# Firewatch system flows

The README diagram stays the short version. This file is the long version: every flow across every branch, plus the community board. For the pitch, open [system-map.html](system-map.html) in a browser. It is the one-screen version, built with Archify from `system-map.architecture.json`.

Everything here follows the code, not the older docs. Where the two disagree, the list at the end says so.

**Status colors used below**

| Color | Meaning |
|---|---|
| Green | Live: runs on real data today |
| Blue | Simulated: built, but only run in replay or against fakes |
| Purple, dashed | Building: community board work under way |
| Gray, dashed | Planned: documented only |

## 1. The whole system

```mermaid
flowchart LR
  subgraph context ["Context: informs the person deciding"]
    FEEDS["14 free feeds on the map<br/>GOES, NGFS, HMS, NWS, WFIGS,<br/>METAR, SPC, RTMA-RU and more"]
    RISK["Dry air grid,<br/>lines under wind"]
  end

  subgraph detect ["Detect"]
    SAT["Satellite hotspot<br/>NASA FIRMS, polled every 60 s"]
    LF["Co-op line fault<br/>lockout on a fire-weather day"]
    TXT["Texted report<br/>FIRE or FIRE N 5"]
    SEN["Tower smoke sensor<br/>PM2.5 jump, not dust"]
    BOARD["Community board<br/>post, then I see it too"]
  end

  subgraph confirm ["Confirm"]
    ML["Satellite score<br/>XGBoost plus guardrails"]
    EV["One event per fire"]
    BURN{"Registered burn,<br/>not escaped?"}
    LVL{"How many independent<br/>sources?"}
    ASK["Ask the ring<br/>6 neighbors within 8 mi"]
  end

  subgraph respond ["Respond"]
    MON["Monitor<br/>texts nobody"]
    FYI["Investigate<br/>duty officer FYI"]
    ESC["Escalate<br/>duty officer: Reply PAGE"]
    PB["Forecast and playbook<br/>3 lowest-loss options"]
    LAD["No answer:<br/>chief at 3 min, dispatch at 9"]
    PAGE["PAGE<br/>dispatch and volunteers"]
    DW["Downwind ranchers:<br/>arrival estimate"]
    EQ["Water truck and disc:<br/>can you help?"]
    MA["Mutual aid draft<br/>chief replies SEND"]
    HU["Heads-up to<br/>neighboring stations"]
  end

  SAT --> ML --> EV
  LF --> EV
  TXT --> EV
  SEN --> EV
  BOARD --> EV
  EV --> BURN
  BURN -- "yes, mild day" --> MON
  BURN -- "yes, extreme day" --> FYI
  BURN -- no --> LVL
  LVL -- none --> MON
  LVL -- one --> FYI
  FYI --> ASK
  ASK -- "reply 1" --> EV
  LVL -- "two, strong satellite,<br/>or Red Flag line fault" --> ESC
  ESC -.-> LAD
  ESC --> PB
  FYI --> PB
  PB -.-> HU
  ESC -- "person replies PAGE" --> PAGE
  PAGE --> DW
  PAGE --> EQ
  PAGE -- "over 371 ac, or<br/>under 2 responding" --> MA
  FEEDS -.-> PB
  RISK -.-> PB

  classDef live fill:#123a2b,stroke:#3ddc97,color:#e6e8eb
  classDef sim fill:#10303f,stroke:#5cc8ff,color:#e6e8eb
  classDef building fill:#2a2146,stroke:#b18cff,color:#e6e8eb,stroke-dasharray:6 4
  class SAT,ML,EV,FEEDS,RISK live
  class LF,TXT,SEN,BURN,LVL,ASK,MON,FYI,ESC,PB,LAD,PAGE,DW,EQ,MA,HU sim
  class BOARD building
```

## 2. Confirm: how a level is decided

This is `decide_level` in `backend/app/confirm.py`. The order matters.

```mermaid
flowchart TD
  START["Event updated"] --> B{"Registered burn here today?"}
  B -- no --> RF
  B -- yes --> X{"Escape evidence, or a late notice?<br/>Fire over 1 km past the notice,<br/>any text report of fire,<br/>or a neighbor replying 1"}
  X -- yes --> RF
  X -- no --> D{"Red Flag day,<br/>or GFDI 25 or more?"}
  D -- no --> M1["Monitor<br/>texts nobody"]
  D -- yes --> I3["Investigate<br/>never asks for a page"]
  RF{"Line fault that counts,<br/>on a Red Flag day,<br/>inside the district?"} -- yes --> C3
  RF -- no --> S{"Strong satellite (score 70+),<br/>or two or more sources?"}
  S -- yes --> C3{"Late notice or a reply of 3,<br/>with no escape evidence?"}
  C3 -- no --> E["Escalate"]
  C3 -- yes --> I2["Investigate<br/>check before paging"]
  S -- no --> O{"One source,<br/>or any stranger's report?"}
  O -- yes --> I["Investigate"]
  O -- no --> M2["Monitor, or the<br/>satellite's own level"]
```

**What counts as one independent source**

| Input | Counts when | Note |
|---|---|---|
| Satellite | Score 40 or more | 70 or more is strong and escalates alone. Under 40 does not count. |
| Line fault | Lockout, over 1 km from a town, GFDI 12 or more | A momentary trip does not count. On a Red Flag day, inside the district, it escalates alone, unless a registered burn with no escape evidence covers it. |
| Registered contact's report | Always | One source per person. |
| Neighbor reply 1 | Always | One source per person. Reply 2 is logged and lowers nothing. |
| Smoke sensors | Rule passes | All sensors together are one source. |
| NOAA NGFS | Labeled wildland, seen in two scans, no registered burn covers it | Same source class as a satellite, never strong, so alone it reaches Investigate. |
| Stranger's report | Never a full source | Weak. Reaches Investigate, never Escalate. |

## 3. Respond: from the first text to mutual aid

```mermaid
sequenceDiagram
  participant FW as Firewatch
  participant DO as Duty officer
  participant CH as Chief
  participant DI as County dispatch
  participant NB as Neighbors
  participant VO as Volunteers
  participant DW as Downwind and helpers
  participant MA as Neighbor district

  Note over FW,DO: A Red Flag line fault skips to Escalate, with no ring ask
  FW->>DO: Investigate: FYI, Reply PAGE or NO
  FW->>NB: See smoke? Reply 1, 2 or 3
  NB-->>FW: 1 (second source)
  FW->>DO: Escalate: Reply PAGE or NO
  alt Duty officer is silent
    FW->>CH: 3 min later, same text
    FW->>DI: 9 min later, likely fire
  end
  DO-->>FW: PAGE
  FW->>DI: Tone out the district
  FW->>VO: FIRE, wind, location. Reply R
  FW->>DW: Arrival estimate, move stock
  FW->>DW: Can you bring your water truck or disc?
  VO-->>FW: R
  FW->>CH: Over 371 ac, or under 2 R in 5 min: Reply SEND
  CH-->>FW: SEND
  FW->>MA: Mutual aid request
```

The expected-loss playbook sits beside this on the dashboard (`andrew` branch). It ranks options for the person deciding. A person still chooses, and `PAGE` by text works with or without it.

## 4. Community board (building)

These rules come from the board plan. The bearing parser (`where.py`), the wider ring, posts, the keyword sorter, the confirm logic, the unconfirmed-post timer and the send limits exist on `michael-board`. The acknowledge hold is in. The board page and member approval do not exist yet.

```mermaid
flowchart TD
  IN1["SMS or MMS"] --> POSTS
  IN2["Mesh text"] --> POSTS
  IN3["Web page: photo, GPS,<br/>offline queue"] --> POSTS
  POSTS["Posts: every input, raw"] --> SORT["Sort: category button,<br/>or keywords for texts"]
  SORT --> BOARD["The board<br/>firefighters watch it"]
  BOARD --> SEE{"Second person:<br/>I see it too, or reply 1,<br/>within 15 miles"}
  SEE -- "fire or smoke" --> SIG["Report signal"]
  SEE -- hazard --> HZ["Duty officer text,<br/>map pin"]
  SIG --> LVL["Same two-source rule"]
  LVL --> MAP["Map, forecast, texts"]
  BOARD -.-> FF["Firefighter buttons:<br/>Acknowledge, Page, Dismiss, Resolve"]
  FF -.-> ACK["Acknowledge stops repeats,<br/>never new information,<br/>and lapses at 30 min"]
```

Two members reach Escalate. Two strangers stay at Investigate, so a person looks before anything pages. The crowd can raise an item, and only the station can lower it.

## 5. No cell bar: the mesh path

```mermaid
flowchart LR
  VR["Volunteer radio<br/>T1000-E"] -- "LoRa, no cell" --> GW["Station radio<br/>USB to the server"]
  TN["Solar tower node<br/>PM2.5, temp, humidity"] -- "LoRa, no cell" --> GW
  GW --> PARSE["Same text parser<br/>FIRE, BURN, PAGE, R"]
  PARSE --> CHAIN["Same confirm chain"]
  CHAIN -- "alerts with delivery receipts" --> GW
  GW --> VR
  CHAIN -- "SMS, needs internet" --> PHONES["Phones"]
```

The field side needs no cell bar. The station side still needs its server, its radio, and internet for SMS and satellite data. A radio with no roster contact counts as a stranger, so it reaches Investigate at most. Mesh and sensors have only run against simulated radios and packets.

## Which branch holds what

No single branch runs the whole chain yet. Merging `michael` and `michael-board` today conflicts in seven files, including `confirm.py` and `scenario.py`.

| Piece | `main` | `andrew` | `michael` | `michael-board` |
|---|---|---|---|---|
| Core chain, ML score, replay | Yes | Yes | Yes | Yes |
| Mesh bridge, tower sensors | Yes | No | No | Yes |
| Free data feeds | No | Yes, older copy | Yes | Yes |
| NGFS feed, packet scenarios, alert load | No | No | Yes | Yes |
| Bearing parser, wider ring, ring scenarios | No | No | No | Yes |
| Playbook, forecast v2, fire-day model | No | Yes | No | No |
| Red Flag rule, evidence-only burn escape, NGFS signal | No | No | Yes | No |
| Community board posts and page | No | No | No | No, in build |

`isak`, `preston` and `shane` have nothing beyond `main`.

## Where the code differs from older docs

| Doc says | Code does |
|---|---|
| README Detect box lists GOES | FIRMS is the only satellite feed the model scores. GOES is context on the map, and NGFS can count as the satellite source. |
| `DESIGN.md`: voice call to dispatch at 6 min | Text to dispatch at 9 min |
| `DESIGN.md`: reply 3 registers a burn | Reply 3 drops Escalate to Investigate |
| `DESIGN.md`: helpers reply 1 | Helpers reply R |
| `DESIGN.md`: downwind includes anyone within 2 miles | Downwind means contacts the fire reaches within the forecast window |
| README and `main`: ask 3 neighbors within 3 miles | 6 neighbors within 8 miles on `michael-board`, because the packet says nobody is within 4 miles |
| README: first truck T+40, 220 vs 520 acres | Forecast v2 on `andrew`: first truck T+38, 329 vs 954 acres (spread model estimate) |
| README: registered burns are suppressed | True on a mild day. On a Red Flag day or at GFDI 25 or more, a burn with no escape evidence goes to Investigate, and never Escalate. |
| README: escalation needs two independent signals | A line fault on a Red Flag day, inside the district, escalates on one source |
