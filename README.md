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

## Port days shared by crew

Ports that don't publish schedules leave gaps in each ship's itinerary. Crew fill them: a day one crew member adds (or today's port they pick) is shared with everyone on the same ship, labelled "added by crew" with how many phones reported it. Official port schedules always win on the same day.

One-time setup (free Supabase project):

1. Create a project at supabase.com.
2. SQL Editor → New query → paste `supabase/crew_days.sql` → Run.
3. Project Settings → API: copy the project URL and the `anon` public key into `CREW_DB` near the top of the script in `app/index.html`.

With `CREW_DB` empty the app works as before and keeps added days on the phone only. `tools/crew_test.js` tests the feature against a fake database.

## Publishing
See `store/NEXT-STEPS.md`. The signed release bundle (`Gangway.aab`) is built by the "Build Gangway Android app" workflow once the four `GANGWAY_*` secrets are added under Settings > Secrets and variables > Actions.
