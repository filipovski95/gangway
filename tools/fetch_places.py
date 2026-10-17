"""Fetch places around every port from OpenStreetMap (Overpass API) and write
compact JSON files the app downloads: data/index.json and data/ports/<id>.json."""
import json, math, os, subprocess, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from ports_src import PORTS

MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.osm.jp/api/interpreter",
]
OUT = os.path.join(os.path.dirname(__file__), "..", "data")
LIMITS = {"food": 40, "sights": 25, "essentials": 30}
UA = "Gangway/0.1 (offline cruise port guide)"


# Three small queries per port: busy Overpass servers accept short, light
# queries far more readily than one large one.
def queries(lat, lon):
    a = lambda r: f"(around:{r},{lat},{lon})"
    head = "[out:json][timeout:30][maxsize:16000000];"
    return [
        head + f"""nwr{a(2000)}[amenity~"^(restaurant|cafe|fast_food|bar|pub|ice_cream)$"][name];out center tags 150;""",
        head + f"""(nwr{a(7000)}[tourism~"^(attraction|museum|viewpoint|gallery|zoo|aquarium|theme_park)$"][name];
 nwr{a(7000)}[historic~"^(castle|fort|ruins|monument|archaeological_site)$"][name];
 nwr{a(9000)}[natural=beach][name];);out center tags 120;""",
        head + f"""(nwr{a(2500)}[amenity~"^(pharmacy|atm|bank|bureau_de_change|internet_cafe|post_office|hospital)$"];
 nwr{a(2500)}[shop~"^(mobile_phone|supermarket|laundry|dry_cleaning)$"];
 nwr{a(2500)}[internet_access~"^(wlan|yes)$"][name];);out center tags 120;""",
    ]


def fetch(q):
    body = urllib.parse.urlencode({"data": q}).encode()
    last = None
    for attempt in range(8):
        url = MIRRORS[attempt % len(MIRRORS)]
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception as e:  # busy servers and timeouts: rotate mirrors, back off
            last = e
            print(f"  {url.split('/')[2]}: {e}", flush=True)
            time.sleep(3 + 4 * attempt)
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


def write_index(index):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    with open(os.path.join(OUT, "index.json"), "w") as f:
        json.dump({"version": stamp, "ports": index}, f, ensure_ascii=False, separators=(",", ":"))


def save_progress(msg):
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    subprocess.run(["git", "add", "data"], check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode:
        subprocess.run(["git", "commit", "-qm", msg], check=True)
    # Other commits (app changes) may land on the branch while this runs.
    for _ in range(3):
        subprocess.run(["git", "pull", "-q", "--rebase"], check=False)
        if subprocess.run(["git", "push", "-q"]).returncode == 0:
            break
        time.sleep(5)


def main():
    only = set(sys.argv[1:])
    os.makedirs(os.path.join(OUT, "ports"), exist_ok=True)
    index = [dict(id=p[0], name=p[1], country=p[2], region=p[3], lat=p[4], lon=p[5], tender=p[6]) for p in PORTS]
    write_index(index)
    done = 0
    refresh_all = os.environ.get("REFRESH_ALL") == "1"  # weekly: refetch every port, keep old data on failure
    todo = [p for p in PORTS if (p[0] in only) or (not only and (refresh_all or not os.path.exists(os.path.join(OUT, "ports", f"{p[0]}.json"))))]
    for attempt in range(2):  # second pass retries ports the busy servers refused
        todo = fetch_ports(todo, index, done)
        if not todo:
            break
        print(f"Retrying {len(todo)} ports", flush=True)
        time.sleep(60)
    write_index(index)
    save_progress("Port places: final batch")


def fetch_ports(todo, index, done):
    failed = []
    for pid, name, country, region, lat, lon, tender in todo:
        entry = {"id": pid, "name": name, "country": country, "region": region,
                 "lat": lat, "lon": lon, "tender": tender}
        path = os.path.join(OUT, "ports", f"{pid}.json")
        print(f"{pid} {name}", flush=True)
        try:
            data = {"elements": [el for q in queries(lat, lon) for el in fetch(q).get("elements", [])]}
        except RuntimeError as e:
            print(f"  skipped: {e}", flush=True)
            failed.append((pid, name, country, region, lat, lon, tender))
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
        done += 1
        if done % 10 == 0:
            write_index(index)
            save_progress(f"Port places: {done} more ports")
        time.sleep(2)
    return failed


if __name__ == "__main__":
    main()
