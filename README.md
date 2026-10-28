# Plume: GLP-1 Tracker

A calm, private tracker for people on GLP-1 medications (Zepbound, Mounjaro, Wegovy, Ozempic and compounded versions). Android first, built with Capacitor so the same app can ship on iPhone later.

**Pay once, yours forever.** Free to download, with a one-time Pro unlock. No subscription, no account, no ads. Everything stays on the phone.

## Features
**Free**
- Countdown to your next shot, with an overdue warning
- Injection site rotation on a body map, with the next site suggested
- Protein ring and water cups with one-tap logging and quick food picks
- Weigh-ins with progress toward a goal
- "How are you feeling?" symptom log with severity
- Dose journey (every dose change, automatically)
- Shot-day reminder and an optional evening check-in notification
- Full history you can edit or delete
- Light and dark mode

**Pro (one-time, $4.99 planned)**
- Full weight history (3 months / all time)
- "Pattern after your shot": which day after the shot symptoms usually hit
- Doctor-ready summary to share by email or text

## Project layout
```
app/        the app (index.html + fonts)
brand/      app icon, Android launcher icons and splash screens
store/      Google Play listing text
tools/      app_test.js, the automatic phone-screen test
.github/    workflow: test the app, then build the Android APK + AAB
PRIVACY.md  privacy policy (needed for the Play Store listing)
```

## Getting the app on your phone
Every push runs the **Plume app** workflow on GitHub:
1. **Test**: opens the app on a Pixel-sized screen, taps through every flow, and uploads screenshots + `report.txt` to the **Plume test results** release.
2. **Build**: makes `Plume.apk` (install on your phone) and `Plume.aab` (upload to Google Play), published to the **Plume test build** release.

On your Android phone, open the **Plume test build** release, download `Plume.apk`, open it and allow installing from this source.

## Before publishing on Google Play
See `store/NEXT-STEPS.md`.
