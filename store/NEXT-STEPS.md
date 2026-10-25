# Gangway: steps to publish on Google Play

Everything for the store is in this folder: listing text (`listing-en.md`), icon (`play-icon-512.png`), banner (`feature-graphic-1024x500.png`) and 5 phone screenshots (`screenshots/`). The privacy policy is `PRIVACY.md` in the repo.

## Only you can do these

1. **Google Play developer account.** Use the one from Saylark, or create one at play.google.com/console ($25 once, with ID verification).
2. **Check your employer's rules** on crew side projects before publishing. The listing names no cruise line and says the app is not affiliated with one.
3. **Signing key.** Created (25 Oct): `gangway-upload-key.jks` plus `gangway-github-secrets.txt`, kept privately by you, never in the repo. Add its 4 secrets in GitHub (repo Settings > Secrets and variables > Actions): `GANGWAY_KEYSTORE_BASE64`, `GANGWAY_KEYSTORE_PASSWORD`, `GANGWAY_KEY_ALIAS`, `GANGWAY_KEY_PASSWORD`. They have their own names so Gangway and Saylark keep separate keys. Then run the "Build Gangway Android app" workflow; the signed `Gangway.aab` is attached to the "Gangway test build" release.
4. **Closed test first.** New personal Play accounts must run a closed test with at least 12 testers for 14 days before going public. Crew friends on the ship are perfect testers: they just need a Gmail address.

## In Play Console (about 30 minutes)

1. Create app: name "Gangway: Cruise Port Guide", free, category Travel & Local.
2. Store listing: paste the texts from `listing-en.md`, upload the icon, banner and screenshots.
3. App content: privacy policy URL (in `listing-en.md`), Data safety answers (no data collected), content rating questionnaire (everyone), no ads.
4. Testing > Closed testing: upload `Gangway.aab`, add the testers' emails, send them the opt-in link.
5. After 14 days: apply for production access, then promote the release.
