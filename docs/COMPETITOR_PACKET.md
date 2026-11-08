---
title: Firewatch 2026 competitor packet (full transcription)
date: 2026-11-06
project: analyzer
tags: [hackathon, university, wildfire, firewatch, brief, competitor-packet]
type: project
status: active
---

# Firewatch 2026: competitor packet

Full transcription of the six-page printed packet handed out at check-in on Friday Nov 6, 2026.
Team: **Watch Dogs** (name tag: Shanuka Vithana). Background and our earlier research are in
[[wsu-innovation-works]].

> Quick reference
> - **The user:** the chief of Cottonwood Creek Fire District (fictional, south-central Kansas).
> - **The window:** 62 minutes from ignition (1:50) to first truck on scene (2:52); for 27 of them nobody knows there is a fire.
> - **The ask:** a *system*, not a sensor. Detect → Confirm → Respond, and how the pieces talk.
> - **Must answer:** rough cost, who would realistically pay, time to stand up, what it does when it fails, what we tested.
> - **Deadlines:** team name on Slack by **8:00 pm Fri** · review round **12:30 Sat** · slides (PowerPoint, in `#slides`) by **11:00 Sun** · pitches **11:30 Sun**.

---

## Page 1 / 6: Cover

**College of Innovation + Design, Wichita State University**, in collaboration with **Lockheed Martin Skunk Works**

Firewatch 2026 / Competitor packet · Innovation Works Challenge · Nov 6 to 8, 2026

# Firewatch.

**Help stop a small fire from becoming a disaster.**

| When | Where | Questions |
|---|---|---|
| Friday Nov 6, 5:00 pm through Sunday Nov 8, 3:00 pm | Woolsey Hall, Wichita State. Rooms on page 2 | Slack first. jared.goering@wichita.edu · 620-755-2823 |

**Contents**

| Page | Section | What's in it |
|---|---|---|
| 02 | The weekend | Schedule, rooms, doors, food |
| 03 | The brief | Why now, three barriers, the ask, ground rules |
| 04 | The scenario | Cottonwood Creek and the 62 minutes everyone designs against |
| 05 | How you are judged | Saturday review round, Sunday pitch round, what judges are looking for |
| 06 | Awards, comms, tonight | Six awards, the trip, Slack, what to do before 9:00 |

*Cover graphic: a topographic contour map with a red ignition point and a smoke plume, labelled
"1:52 pm · 15 acres · nobody within four miles".*

| Friday | Saturday | Sunday | Sunday 2:00 |
|---|---|---|---|
| Kickoff 5:30. Then work time until 9:00 | Review round 12:30. Eight finalists announced at 2:00 | Pitches 11:30. Slides due 11:00, in PowerPoint | X-59 talk, then awards. Open to the public. Bring people |

© 2026 WSU College of Innovation and Design · Wichita, Kansas

---

## Page 2 / 6: The weekend

*Building hours are the first and last lines of each day.*

# The weekend.

Three days in Woolsey Hall. Friday is about turning an idea into a plan, Saturday is the build and
the review round, Sunday is the pitch. Pizza Friday at 6:00 and snacks and food Sunday at 11:15;
otherwise food is on your own, with snacks and water out all weekend.

### Friday Nov 6 (WO 135)

| Time | What | Detail |
|---|---|---|
| 5:00 | Check-in, by team | Sit with your team. Solo signups are grouped at the table |
| 5:30 | Kickoff | The brief, the scenario, how the weekend works. Lucas and Brian from Lockheed Martin on Teams |
| 6:00 | Pizza | |
| 6:20 | Work time, until 9:00 | Mentors circulating |

### Saturday Nov 7 (WO 110A, 110B, 233, 234)

| Time | What | Detail |
|---|---|---|
| 9:00 | Doors open | Five-minute morning brief, then build |
| 12:30 | Review round, assigned slots | Ten minutes, two judges. Your room and time are posted on Slack |
| 2:00 | Eight finalists announced | Everyone gathers |
| 8:00 | Doors close | |

### Sunday Nov 8 (WO 110B and WO 135)

| Time | What | Detail |
|---|---|---|
| 9:00 | Doors open | Work on the pitch |
| 11:00 | Slides due | PowerPoint, posted in Slack |
| 11:15 | Snacks and food | |
| 11:30 | Pitches | Eight finalists, ten minutes plus three of questions |
| 2:00 | Jeff's X-59 talk | Lockheed Martin. Open to the public |
| 2:30 | Awards | Done by 3:00 |

### Rooms and doors

| Tonight | Saturday | Sunday | Doors |
|---|---|---|---|
| **WO 135**: reserved until 9:00 | **WO 110A**: home base. Judging rooms posted Friday night | **WO 110B + 135**: pitches, the X-59 talk and awards | **9:00 to 8:00** Saturday. Sunday 9:00 to 3:00 |

*Floor plans:*

- **First floor.** WO 135 (Friday and Sunday). WO 110A and 110B are the two halves of the
  auditorium (110B marked "SUN · pitches", 110A marked "SAT · base").
- **Second floor.** WO 233 and 234, Saturday judging rooms, south wing.

**WiFi.** The WSU network, with your usual login.

**Saturday rooms.** Your review room and time slot are assigned Friday night, posted on Slack and
printed on the door of the home base room.

**Not advancing Saturday?** Come back Sunday at 2:00 for the X-59 talk and the awards. Both are
open to the public, so bring people.

**Leaving the building.** Saturday closes at 8:00. Sunday ends at 3:00. Take your things with you
each night.

---

## Page 3 / 6: The brief

*What this weekend asks of you.*

# Catch a grass fire in its first minutes.

Wildfires burned 5.1 million acres across the U.S. in 2025. Extreme fires are about 3% of fires and
do 80% of the damage, and most are still found by a 911 call. The Ranger Road fire this February
burned 15,000 acres in its first hour and 283,000 before it was out. The cheapest minutes are the
first ones, and nobody has solved the prairie.

| As a system | With what is actually out there | On a rural budget |
|---|---|---|
| Detect, confirm, respond, and how the pieces talk to each other. | One bar of cell in the breaks. No fiber anywhere. Volunteers at work. | A county mill levy, and whatever grant the chief wins this year. |

### 01 · Three barriers

| Barrier | |
|---|---|
| **Time** | Detection still depends on someone noticing. By the time a crew rolls, the window to stop a fire cheaply has closed. |
| **False alarms** | Dust, controlled burns and haze all look like smoke. A system that cries wolf gets switched off. |
| **Cost at rural scale** | Rural districts cover hundreds of square miles on volunteer budgets. Anything that needs a fiber line or a full-time operator will not get deployed. |

The scenario on the next page shows all three in one afternoon. Every team designs against it, so
nobody has to guess who the user is or what the fire looks like.

### 02 · The ask

**A system, not a sensor.** Cover the whole chain, and show how the pieces talk to each other.

| Detect → | Confirm → | Respond |
|---|---|---|
| Sensors, cameras, satellites, community reports, or something we have not thought of. | A drone or another low-cost way to verify a fire without sending a person. | Suppression, containment or alerting that slows the fire before the first engine arrives. |

Build it for the chief on the next page. Tell him roughly what it costs, who would realistically
pay, how long it takes to stand up, and what it does when it fails.

### 03 · Ground rules

1. **Civil and commercial use only.** No defense applications. This is a fire district's problem.
2. **Public data sources.** Weather, satellite, terrain, fire history: anything you use has to be
   something the district could get too.
3. **Power and connectivity in the field are part of the problem. Design for them.** One bar of cell
   and no fiber is the starting condition, not an inconvenience to assume away.
4. **You decide what you can demo in a weekend.** There is no minimum demo bar. Something built,
   simulated or tested beats a slide, every time.

---

## Page 4 / 6: The scenario

*One story every team designs against.*

# Cottonwood Creek Fire District.

This is who you are building for. Not an agency, not a utility. A chief. The district is
fictional, modeled on Clark, Comanche and Barber counties in south-central Kansas. The fire numbers
come from three real Kansas fires: Anderson Creek 2016, Starbuck 2017 and Ranger Road 2026.

| Number | What it is |
|---|---|
| **450** | square miles of grass, wheat and CRP |
| **18** | volunteers on the roster |
| **5** | who can leave work on a weekday afternoon |
| **2+1** | brush trucks and a tanker, all secondhand |
| **11** | miles of gravel to the far side of the district |
| **1** | bar of cell in the breaks, if that |
| **0** | fiber, anywhere |
| **911** | county dispatch pages by radio and app |

**The district.** One station in a town of 900. Two brush trucks (one a converted military surplus
truck), one tanker, one structure engine. The county 911 center dispatches by radio pager and a
phone app. The budget is a county mill levy that covers fuel, insurance and repairs, plus whatever
grant the chief wins that year.

**The day.** A Tuesday in mid-March. Red flag warning since 6 a.m.: south wind 30 to 40 mph, gusts
past 55, humidity 11 percent, 78 degrees, no measurable rain in five weeks, dormant grass. Two
neighbors burned pasture over the weekend under county burn permits, so smoke on the horizon is
normal this month.

**Ignition, 1:50 p.m.** A gust snaps the cross-arm on a 40-year-old line serving an oil lease,
11 miles northwest of the station. The line drops into CRP grass beside a gravel road. Nobody is
within four miles.

**Detection.** 2:17: a propane delivery driver sees a smoke column from the highway and assumes a
pasture burn until he sees how fast it is moving. He has no signal for three miles. 2:21: he
reaches 911. 2:23: the dispatcher pages Cottonwood Creek. The fire is 33 minutes old.

**Response.** 2:34: Brush 1 leaves the station with two volunteers; the chief is at work 30 miles
away. 2:52: Brush 1 arrives after 11 miles of gravel into the wind. The head of the fire is two to
three miles downwind and the flanks are wider than two trucks can hold. Mutual aid is 30 to 40
minutes out, and one of the two nearest departments is already on a fire of its own, because it is
the same red flag day for everyone. The state can offer one air tanker; the Guard helicopters need
a declaration and a two-hour flight, and the wind driving the fire is the wind that keeps aircraft
on the ground.

### Timeline

| Time | What happens | Who knows |
|---|---|---|
| 1:50 | Line falls, grass ignites | Nobody |
| 2:17 | Driver sees smoke, no signal | Driver |
| 2:21 | 911 call | Dispatch |
| 2:23 | District paged | District |
| 2:34 | Brush 1 rolls, two volunteers | District |
| 2:52 | Brush 1 on scene, fire 2 to 3 miles long | District |
| 3:05 | Tanker and Brush 2 on scene | District |
| 3:10 | Mutual aid requested, nearest 30 to 40 min out | County |
| 3:20 | State requested; aircraft hours away and wind-limited | State |
| 4:00 | Fire across two county roads; rancher discing ahead of it | Everyone |

> **The weekend is about everything before 2:52.**
> Sixty-two minutes pass between the line falling and the first truck on scene. Twenty-seven of
> them, nobody knows there is a fire at all. Those are the minutes you are going after. Which ones,
> and how, is your call.

### The three jobs

| Detect it in minutes, not 27. | Confirm it is a wildfire, not Tuesday's pasture burn. | Slow it, or get the right people moving, before the first engine. |
|---|---|---|
| Two minutes in, this fire is a smoke column over about 15 acres with nobody within four miles. A monitored line would have reported the fault the moment it fell. | Without driving out to look. A system that pages the district for every permitted burn gets switched off by April. | Even a fast page puts Brush 1 on scene with the head a mile and a half out. Respond has to mean more than the station: the rancher downwind, the lease's water truck, a disc line. |

---

## Page 5 / 6: How you are judged

*Judges rank. No scores, no percentages, no rubric.*

# Two rounds. Six things judges look for.

Saturday's review round is ten minutes with two Lockheed Martin or WSU judges while you are
mid-build; it decides the eight finalists. Sunday's pitch round is ten minutes plus questions in
front of the full panel; it decides the awards. Pitch to people, not to a panel: ask questions,
push back, tell them what you tested.

### 12:30 Saturday: The review round

- **Your room and slot are assigned.** They are posted on Slack Friday night. Be outside the door
  five minutes early.
- **Ten minutes. Two judges.** Show them where you are. No slides needed; a sketch, a screen or a
  half-built thing all count.
- **Each room ranks what it sees.** Top two per room advance. Eight finalists, announced at 2:00.
- **Not advancing?** Come back Sunday at 2:00 for the X-59 talk and the awards.

### 11:30 Sunday: The pitch round

- **Slides due at 11:00.** Built in PowerPoint, posted in the Slack slides channel with your team
  name on the file. One machine runs every pitch, so no other format.
- **Ten minutes, three of questions.** Hard cutoff. A timekeeper gives a one-minute warning.
- **Live demo?** Bring your own device and tell us on Slack by 11:00. A video in the deck is the
  safe option.
- **Judges deliberate during Jeff's talk.** They rank the top three and vote the three sub-awards.
  Awards at 2:30.

### 01 · What the judges will ask you Saturday

1. **Problem.** Do you understand the fire you are trying to catch: the 62 minutes, the three
   barriers? Which minutes are you going after?
2. **Concept.** Is a system taking shape? Does it face power, connectivity, false alarms and the
   district's budget, or assume them away?
3. **Evidence.** What have you built, simulated or tested since last night, and what did it show?
   Half-built is expected.
4. **Next step.** What are you doing between 2:00 today and 11:00 tomorrow, and is that path
   credible for your team in that time?

### 02 · Put in your pitch

The six things on this page, in whatever order tells your story. The judges will ask about anything
you skip, so the questions worth preparing for are: who would realistically pay for this, what does
it do when it fails, and what did you test this weekend and what did it show.

**Submitted an RFP?** The judges know, and it helps in a close call.

### 03 · What judges are looking for, in order of importance

1. **The whole chain.** Detect, confirm, respond, and how the pieces talk to each other. A system,
   not a sensor.
2. **Field reality.** Power, connectivity, false alarms and rural budgets handled in the design, not
   assumed away.
3. **Built for a real district.** Does it work on a rural department's budget, crew and
   connectivity, in the minutes the scenario allows?
4. **Honest numbers.** Rough cost, who would realistically pay for it, time to stand up, what it
   does when it fails.
5. **Evidence.** A demo of what you built, simulated or tested this weekend, and what it showed.
6. **A next step.** What you would build next, and why.

---

## Page 6 / 6: Awards, comms, tonight

*Six awards. One trip. Four things before 9:00.*

# Six awards, one trip.

**The top three teams go to Lockheed Martin.** First, second and third get the trip and a trophy
each. The three sub-awards get a trophy each, presented Sunday at 2:30. A team can win a sub-award
and not place.

### 01 · Three places

| 1st | 2nd | 3rd |
|---|---|---|
| Ranked by the judges after the Sunday pitches. First place has a name, and you hear it then. | The trip, and a trophy. | The trip, and a trophy. |

### 02 · Three more, any team can take

| Best Influencer | Most Fire Idea | Most Practical |
|---|---|---|
| The most social content over the weekend. Tag the account and it counts. | The boldest, most original concept in the room. | The system a rural district could buy, stand up and run. |

### 03 · Slack

**Slack: everything, all weekend.** Questions, changes, where to be, your team name, your Saturday
room and slot, Sunday demo plans. Join tonight. Scan to join · `innovationworks26.slack.com`

**Sunday slides go in Slack too.** Upload your PowerPoint to the slides channel by 11:00 Sunday,
named after your team. Live demo? Say so in the same channel by 11:00. `#slides` · by 11:00 Sunday

### 04 · Tonight, before 9:00

1. **Turn your idea into a Saturday plan.** Who builds what, what you can test by 12:30, what you
   show the judges.
2. **Name your team and post it on Slack by 8:00 pm.** Unnamed teams show up by contact name on the
   grid, the name tags and the Sunday order.
3. **Check your judging slot and room on Slack before you leave.** Posted Friday night once check-in
   is final.
4. **Flag down a mentor.** Maggie and the MID mentors are circulating all evening and all day
   Saturday.

**Social.** Tag **@wsu_innovationdesign** on Instagram, or **College of Innovation & Design at
Wichita State University** on LinkedIn, in anything you post. It feeds Best Influencer.

**Photos and video.** By taking part you agree that Wichita State may use photos and video from the
weekend. Tell the check-in table if you would rather not be photographed.

**Questions.** Slack first. Then Jared Goering, jared.goering@wichita.edu or 620-755-2823.

---

## Related

[[wsu-innovation-works]]
