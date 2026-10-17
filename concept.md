# Cruise Port App: Concept and First Version

## Decision
**Build a cruise port guide, for crew first and passengers second.**

A general "things to do today where you are" app would compete head-on with Google Maps, TripAdvisor and Airbnb Experiences. A new app can't win that, and it gives you no edge. Cruise ports are a narrow, repeating set of places (a few hundred worldwide). Crew and passengers there share the same problems: limited time, a hard all-aboard deadline, and poor or costly internet. You know those problems from the inside, and you can reach the users directly through crew across the fleet. Being narrow is what lets this app win.

Crew come first because nothing serves them well, they come back to the same ports every few weeks (so they keep using the app and add tips), and you can get your first users without any marketing budget. Passengers come in version 2. They are the bigger market and the source of revenue.

## Working name
**Crew Ashore** (passenger edition later: **Ashore**)

## What it does
- **Port page:** one page per port, opened offline, with a map centred on the pier and pins for wifi, SIM cards, money exchange, pharmacy, laundry, food, sights, beach and shopping.
- **Time-boxed ideas:** "1 hour / 3 hours / full day" suggestions with walking or taxi times from the pier.
- **All-aboard timer:** enter your all-aboard time and it counts down, warning you based on how long the walk back takes from where you are.
- **Crew tips:** short notes like "cheapest SIM is at the kiosk left of the terminal" or "crew discount at X". Crew can upvote them.
- **Offline first:** each port downloads over ship wifi before arrival, then the app works with no signal ashore.

## Where the data comes from
- Maps and points of interest: **OpenStreetMap**, which is free and can be stored offline. Google Places doesn't allow long-term storage and charges per search, so it's a bad fit for offline use.
- Port details and crew tips: written by you and your colleagues first, then by users.
- Itineraries: public cruise schedules. Use only public information and nothing internal to Celebrity.

## First version (MVP)
1. Cover every port the whole Celebrity fleet visits (all ships, all current itineraries). Step one is to build that port list from Celebrity's public itineraries. Every port gets an auto-generated page, and the most-visited ports get hand-polished first.
2. Build it as an installable web app (PWA) that works offline. That means no app store review at first, and it shares a lot of the setup with LinguaPath.
3. Include the port page, the all-aboard timer and read-only tips. Tip submission comes through a simple form that you review.
4. Test it free with your department and crew friends, and watch which ports and pins people actually open.

## After that
- Open tip submission to crew, and add other ships and itineraries.
- Release a passenger edition in the app stores, with optional affiliate links for excursions (for example Viator or GetYourGuide) as the first revenue.
- Publish and promote it alongside LinguaPath. Crew-language phrases per port could link the two apps.

## Added features (requested 17 Oct)
- **Directions button:** every place (restaurant, activity, wifi spot) gets a "Directions" button. It opens Google Maps with walking directions from where you are to that place. This uses a plain Google Maps link, so it needs no API key and costs nothing.
- **Refresh button:** a refresh button on the home screen, with a hint next to it such as "Tap refresh to get today's updates" and "Last updated: today 08:12". Tapping it downloads the latest port data as a small file hosted for free (for example on GitHub Pages). No server runs all the time.
- **Open today:** each place stores its opening hours per weekday, so the app shows "Open today" or "Closed on Mondays" automatically, even offline. Refresh brings in any changes, such as new places, holiday closures or new crew tips.
- **Design:** a polished, travel-magazine look with large photos, clear cards and a calm ocean colour palette, given the same design care as LinguaPath.

## Check before building
- Celebrity / Royal Caribbean Group policy on employee side projects and social media.
- Don't use the company name or logo in the branding.

## Status
Parked until LinguaPath is finished.

## Scope decision (17 Oct)
The first release covers all ports on the Celebrity fleet's itineraries. Ports from other cruise lines come later.
