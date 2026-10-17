"""Fetch places around every port from OpenStreetMap (Overpass API) and write
compact JSON files the app downloads: data/index.json and data/ports/<id>.json."""
import json, math, os, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from ports_src import PORTS

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
OUT = os.path.join(os.path.dirname(__file__), "..", "data")
LIMITS = {"food": 40, "sights": 25, "essentials": 30}
UA = "Gangway/0.1 (offline cruise port guide)"


def query(lat, lon):
    a = lambda r: f"(around:{r},{lat},{lon})"
    return f"""[out:json][timeout:120];
(nwr{a(2500)}[amenity~"^(restaurant|cafe|fast_food|bar|pub|ice_cream)$"][name];);out center tags 300;
(nwr{a(8000)}[tourism~"^(attraction|museum|viewpoint|gallery|zoo|aquarium|theme_park)$"][name];
 nwr{a(8000)}[historic~"^(castle|fort|ruins|monument|archaeological_site)$"][name];
 nwr{a(10000)}[natural=beach][name];);out center tags 250;
(nwr{a(3000)}[amenity~"^(pharmacy|atm|bank|bureau_de_change|internet_cafe|post_office|hospital)$"];
 nwr{a(3000)}[shop~"^(mobile_phone|supermarket|laundry|dry_cleaning)$"];
 nwr{a(3000)}[internet_access~"^(wlan|yes)$"][name];);out center tags 250;"""


def fetch(q):
    body = urllib.parse.urlencode({"data": q}).encode()
    last = None
    for attempt in range(6):
        url = MIRRORS[attempt % len(MIRRORS)]
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except Exception as e:  # rate limits and timeouts: back off and rotate
            last = e
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Overpass failed: {last}")


def dist_m(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return int(12742000 * math.asin(math.sqrt(a)))


def kind(t):
    am, sh, tou, hi = t.get("amenity"), t.get("shop"), t.get("tourism"), t.get("historic")
    if am in ("restaurant", "cafe", "fast_food", "bar", "pub", "ice_cream"):
        return "food", am
    if tou or hi or t.get("natural") == "beach":
        return "sights", "beach" if t.get("natural") == "beach" else (tou or hi)
    if t.get("internet_access") in ("wlan", "yes") and not am and not sh:
        return "essentials", "wifi"
    return "essentials", am or sh or "wifi"


def place(el, plat, plon):
    t = el.get("tags", {})
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lon = el.get("lon") or el.get("center", {}).get("lon")
    if lat is None:
        return None
    group, sub = kind(t)
    name = t.get("name:en") or t.get("name") or {
        "atm": "ATM", "pharmacy": "Pharmacy", "bank": "Bank",
        "bureau_de_change": "Currency exchange", "post_office": "Post office",
        "hospital": "Hospital", "supermarket": "Supermarket",
        "mobile_phone": "Phone & SIM shop", "laundry": "Laundry"}.get(sub, sub.replace("_", " ").title())
    p = {"n": name, "g": group, "k": sub, "la": round(lat, 6), "lo": round(lon, 6),
         "d": dist_m(plat, plon, lat, lon)}
    for src, dst in (("opening_hours", "h"), ("cuisine", "cu"), ("website", "w"),
                     ("contact:website", "w"), ("phone", "ph"), ("wikipedia", "wp")):
        if t.get(src) and dst not in p:
            p[dst] = t[src][:200]
    if t.get("internet_access") in ("wlan", "yes"):
        p["wifi"] = 1
    return p


def main():
    only = set(sys.argv[1:])
    os.makedirs(os.path.join(OUT, "ports"), exist_ok=True)
    index = []
    for pid, name, country, region, lat, lon, tender in PORTS:
        entry = {"id": pid, "name": name, "country": country, "region": region,
                 "lat": lat, "lon": lon, "tender": tender}
        index.append(entry)
        path = os.path.join(OUT, "ports", f"{pid}.json")
        if (only and pid not in only) or (not only and os.path.exists(path)):
            continue
        print(f"{pid} {name}", flush=True)
        try:
            data = fetch(query(lat, lon))
        except RuntimeError as e:
            print(f"  skipped: {e}", flush=True)
            continue
        seen, groups = set(), {g: [] for g in LIMITS}
        for el in data.get("elements", []):
            p = place(el, lat, lon)
            if not p:
                continue
            key = (p["n"].lower(), p["k"], round(p["la"], 3), round(p["lo"], 3))
            if key in seen:
                continue
            seen.add(key)
            groups[p["g"]].append(p)
        places = []
        for g, lim in LIMITS.items():
            places += sorted(groups[g], key=lambda x: x["d"])[:lim]
        with open(path, "w") as f:
            json.dump({**entry, "places": places}, f, ensure_ascii=False, separators=(",", ":"))
        print(f"  {len(places)} places", flush=True)
        time.sleep(4)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    with open(os.path.join(OUT, "index.json"), "w") as f:
        json.dump({"version": stamp, "ports": index}, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
