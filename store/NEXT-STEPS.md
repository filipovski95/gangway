# Next steps to publish Plume on Google Play

1. **Move Plume to its own repo.** Create an empty repo (e.g. `plume`) on github.com. Claude can move the `plume` branch there with its history.
2. **Google Play developer account.** One-time $25 at play.google.com/console. Use an organization account if you can (an LLC is recommended for health apps).
3. **Upload key.** Create an upload keystore (Claude can generate one), then add these repository secrets under Settings › Secrets and variables › Actions:
   `PLUME_KEYSTORE_BASE64`, `PLUME_KEYSTORE_PASSWORD`, `PLUME_KEY_ALIAS`, `PLUME_KEY_PASSWORD`.
   The workflow then signs `Plume.aab` automatically.
4. **Real Pro purchase.** Create a one-time in-app product (`plume_pro`, $4.99) in Play Console, then wire Google Play Billing into the "Unlock" button (in `app/index.html`, look for `TODO(Play Billing)`) and set `TEST_BUILD = false`.
5. **Store listing.** Text is in `listing-en.md`. Screenshots come from the "Plume test results" release. Feature graphic 1024×500 still to make.
6. **Health apps declaration + Data safety form.** Answer: data stays on device, nothing collected or shared. Privacy policy: link to `PRIVACY.md` on GitHub.
7. **Closed testing.** New personal accounts must run a closed test with 12 testers for 14 days before going to production.
