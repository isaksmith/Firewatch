# Put Firewatch on your iPhone (for Isak)

You need a Mac, an iPhone, a USB cable and about 45 minutes the first time. Most of that is waiting for Xcode.

1. **Install Xcode.** Open the App Store on the Mac, search for Xcode, tap Get. Open it once and accept the license.
2. **Sign in with your Apple ID.** In Xcode choose Xcode > Settings > Accounts, tap the plus, pick Apple ID, sign in. A free account works. A free account's app stops opening after 7 days; run step 6 again to renew it.
3. **Plug in the iPhone** with the cable. Tap Trust on the phone.
4. **Turn on Developer Mode** on the phone: Settings > Privacy & Security > Developer Mode > on. The phone restarts. Confirm when it asks.
5. **Get the app code ready.** In Terminal:
   ```
   cd mobile
   npm install
   ```
6. **Build and install.**
   ```
   npx expo run:ios --device
   ```
   Pick your iPhone from the list. When asked for a team, pick your own name (Personal Team). The first build takes 10 to 15 minutes.
   - If the phone says "Untrusted Developer" when the app opens: Settings > General > VPN & Device Management > your Apple ID > Trust.
7. **Tell the phone where the server is.** The phone cannot use "localhost"; that means the phone itself.
   1. On the laptop, find its Wi-Fi address: System Settings > Wi-Fi > Details, then look for "IP address" (it looks like 192.168.1.23). The laptop and the phone must be on the same Wi-Fi.
   2. Start the backend so other devices can reach it, with `--host 0.0.0.0` on the end of the start command (for example `.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8031`, run from the backend folder).
   3. On the phone open Firewatch > Settings > Server address and type `http://` then the address, a colon and the port, for example `http://192.168.1.23:8031`. Do this before you pick counties. The word "Saved" appears when it is kept.
8. **First launch.**
   1. Pick your state and county, then tap Download. Do this on Wi-Fi. The demo area (Cottonwood Creek) is already inside the app.
   2. Pick "Firefighter" or "Fire chief", then Done.
   3. Turn on your Meshtastic radio and hold it near the phone.
   4. Tap Settings > Radio: not connected > Connect. Tap Allow when the phone asks about Bluetooth.
   5. If the phone asks to pair, type the radio's PIN (the factory default is 123456).
   6. The Radio screen shows the radio's name and, if it is sending it, the battery.

Reports use channel 0. If your district channel is a different number, type it into "Radio channel number" on the Radio screen.

## Test it

Send this exact text on the district channel from the official Meshtastic app (any other radio or phone on the same channel):

```
FW1.cwc.ae.c.2g.vg.-139.2c7t.0.6.n.c0n
```

What you should see within a few seconds:
- Home shows a new row, "Fire, page the district", with a red bar.
- "Last update just now, by radio" under the title.
- Tap the row: a map, "Fire 11 mi NW of Station 1. Moving north. Miller house: as little as 39 min.", and a red Call dispatch button.
- Plain chat such as "fire looks bigger" does not make an alert. It shows under "Radio messages" on the Radio screen.

Older example (a possible fire, no direction): `FW1.cwc.ai.c.19.vg.-139.2c7f...5.5by`

Sending: with the radio connected, Home shows a red **Report smoke here** button. Tap it and allow location. It sends your position and then `FIRE <lat>,<lon>` on the channel. "Sent over radio" means the radio accepted it. It does not mean anyone received it.

The radio keeps delivering alerts while the screen is locked (Bluetooth background mode). Keep the app in the background, not force-closed.

## If something goes wrong
- "Radio needs the full Firewatch app": you opened it in Expo Go. Use `npx expo run:ios --device` instead.
- No radio found: check the radio is on, has Bluetooth turned on in its settings, and no other phone is connected to it. Meshtastic radios allow one Bluetooth connection at a time, so close the official app first.
