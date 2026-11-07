# Design direction for the Firewatch concept screens and deck

**Purpose:** show judges (Lockheed Martin Skunk Works and WSU) what Firewatch looks like in the hands of the people who use it, on the Cottonwood Creek afternoon in [SCENARIO.md](SCENARIO.md).

**People:**
- **Chief:** a volunteer, at work 30 miles away, phone in a truck in March sun, one bar of signal.
- **County dispatcher:** indoors, big screen, also taking 911 calls.
- **Rancher:** gets only a text message; has no app.

## Principles
1. **Daylight for phones, dark for dispatch.** Phone screens are light, very high contrast and readable in direct sun. The dispatch console keeps the existing app's dark look (`--c-*` tokens). Deck and system views are daylight.
2. **One obvious action per screen.** Big targets (phone buttons at least 56 px tall, full width). Plain words a stressed volunteer understands in five seconds. Undo, never "Are you sure?".
3. **Maps are the Kansas section grid.** Draw maps as inline SVG: tan grass fill (`--grass`), gravel roads as grey lines every mile labelled in Overpass ("CR 12", "Rd K"), the fire in `--fire`, the 60-minute forecast as a soft `--fire-soft` teardrop pointing north, houses as small squares with family names, and burns-on-file as `--ok` outlined circles. No map tiles, no external images. This also shows that the map works offline.
4. **Colour has one meaning each.** `--fire` means the fire or "page now". `--redflag` means fire weather only. `--watch` means possible / waiting. `--ok` means acknowledged or "matches a burn on file". `--gap` means missing or late data. No decorative gradients and no drop-shadow card kits.
5. **Type:**
   - Overpass 800/600 for headlines and road names.
   - IBM Plex Sans for everything else.
   - IBM Plex Mono (`.t` class) **only for clock times** like 2:05 pm.
   - No all-caps labels, no tracked-out eyebrows, no "A · B · C" meta strings, no "→" on buttons.
6. **Honesty:** every screen has a small footer: "Concept screen. Sample data from the Cottonwood Creek scenario."

## Files
- Link `../shared/fonts.css` then `../shared/tokens.css` from `design/screens/*.html`. No CDNs, no JS frameworks; vanilla HTML/CSS (a little inline JS only if needed). Each file renders correctly as a static screenshot.
- Set an explicit `background` on `html` and `body`, and do not use `prefers-color-scheme`. Headless Chrome may run in dark mode.

## Screenshot command
```
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --hide-scrollbars --force-device-scale-factor=2 --window-size=W,H --screenshot=/ABS/design/screens/png/NAME.png file:///ABS/design/screens/NAME.html
```

Sizes:
- phone: 390×844
- console: 1440×900
- system view: 1600×900

Always use absolute paths. Look at every PNG (Read tool) and fix what looks wrong before reporting.
