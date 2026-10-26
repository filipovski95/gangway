# Gangway

An offline cruise port guide for crew and passengers, built as an Android (and iOS) app with Capacitor. It covers 319 cruise ports. Download once, tap **Refresh** on ship wifi, then use it all day ashore with no signal.

## What's in each port
- **Eat & drink:** restaurants, cafés and bars near the pier, with walking times.
- **See & do:** museums, viewpoints, beaches, forts and attractions, plus shore excursion ideas.
- **Essentials:** free wifi, SIM shops, ATMs, banks, currency exchange, pharmacies, supermarkets and laundry.
- **Port basics:** currency, whether US dollars are accepted, language, emergency numbers and plug types.
- **Open today:** opening hours per weekday, so the app knows what's open even offline.
- **Directions:** every place opens Google Maps walking directions.
- **All-aboard timer** and **Find the port I'm in**.

Private by design: no account, no ads, no tracking. Place data © OpenStreetMap contributors. Gangway is an independent app and is not affiliated with any cruise line.

## Project layout
```
app/        the app itself (index.html, fonts)
data/       port guides the app ships with and downloads on Refresh
brand/      app icon and splash screens
store/      Google Play listing text, icon, feature graphic, screenshots, NEXT-STEPS.md
tools/      scripts that fetch places, schedules and ship info
.github/    workflows: build Android, build iOS, fetch port places (weekly + daily)
PRIVACY.md  privacy policy (linked from the Play Store listing)
```

## Publishing
See `store/NEXT-STEPS.md`. The signed release bundle (`Gangway.aab`) is built by the "Build Gangway Android app" workflow once the four `GANGWAY_*` secrets are added under Settings > Secrets and variables > Actions.
