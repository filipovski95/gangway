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
LIMITS = {"food": 60, "sights": 40, "essentials": 30}
UA = "Gangway/0.1 (offline cruise port guide)"
# SHARD="i/n" splits the missing ports across n parallel jobs; each starts on a different mirror.
SHARD = tuple(map(int, os.environ["SHARD"].split("/"))) if os.environ.get("SHARD") else None


# Three small queries per port: busy Overpass servers accept short, light
# queries far more readily than one large one.
# Big-city ports have so many places that a normal query runs out of server memory:
# for them the search circles are smaller and the query may use more memory.
# (food and essentials scale, sights scale) of the search circles. Baltimore's terminal is in a port
# district, so food and essentials need a wider circle there while its sights stay tight.
DENSE = {"nyc": (0.5, 0.5), "mnl": (0.5, 0.5), "got": (0.5, 0.5), "bwi": (1.6, 0.5)}


def queries(lat, lon, dense=None):
    near, far = dense or (1, 1)
    a = lambda r: f"(around:{int(r * (far if r >= 7000 else near))},{lat},{lon})"
    head = "[out:json][timeout:90][maxsize:268435456];" if dense else "[out:json][timeout:90][maxsize:32000000];"
    return [
        head + f"""nwr{a(2000)}[amenity~"^(restaurant|cafe|fast_food|bar|pub|ice_cream)$"][name];out center tags 200;""",
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
        url = MIRRORS[(attempt + (SHARD[0] if SHARD else 0)) % len(MIRRORS)]
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.load(r)
            # A busy server can time out mid-query and still answer 200 with a partial result.
            if "remark" in data and ("error" in data["remark"] or "timed out" in data["remark"]):
                raise RuntimeError(data["remark"][:120])
            return data
        except Exception as e:  # busy servers and timeouts: rotate mirrors, back off
            last = e
            print(f"  {url.split('/')[2]}: {e}", flush=True)
            if os.environ.get("GITHUB_ACTIONS"):  # visible in the run's annotations
                print(f"::warning title=Overpass::{url.split('/')[2]}: {str(e)[:160]}", flush=True)
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
                     ("contact:website", "w"), ("phone", "ph"), ("contact:phone", "ph"),
                     ("wikipedia", "wp"), ("wikidata", "wd"), ("description:en", "ds"), ("description", "ds")):
        if t.get(src) and dst not in p:
            p[dst] = t[src][:300]
    street = " ".join(x for x in (t.get("addr:housenumber"), t.get("addr:street")) if x)
    if street:
        p["ad"] = street[:120]
    # Small yes/no facts shown as pills on the place card.
    facts = [code for code, ok in (
        ("out", t.get("outdoor_seating") == "yes"),
        ("veg", t.get("diet:vegetarian") in ("yes", "only") or t.get("diet:vegan") in ("yes", "only")),
        ("wc", t.get("wheelchair") == "yes"),
        ("take", t.get("takeaway") in ("yes", "only")),
        ("card", t.get("payment:credit_cards") == "yes" or t.get("payment:cards") == "yes"),
        ("ac", t.get("air_conditioning") == "yes"),
        ("free", t.get("fee") == "no"),
    ) if ok]
    if facts:
        p["f"] = facts
    if t.get("internet_access") in ("wlan", "yes"):
        p["wifi"] = 1
    return p


def keep_wiki(path, out):
    """Carry Wikipedia text, photos and added landmarks over from the previous file,
    so a refresh of the map data doesn't wipe what enrich.py added."""
    try:
        with open(path) as f:
            old = json.load(f)
    except (FileNotFoundError, ValueError):
        return
    if "wk" not in old:
        return
    wiki = {(p["n"], p["k"]): p for p in old["places"] if p.get("ds") or p.get("img")}
    for p in out["places"]:
        w = wiki.get((p["n"], p["k"]))
        if w:
            p.update({k: w[k] for k in ("ds", "img", "wpu") if k in w})
    names = {p["n"] for p in out["places"]}
    out["places"] += [p for p in old["places"] if p["k"] == "landmark" and p["n"] not in names]
    for k in ("about", "wk"):
        if k in old:
            out[k] = old[k]


def write_index(index):
    if SHARD:  # parallel jobs leave the shared index alone so their pushes never conflict
        return
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    path = os.path.join(OUT, "index.json")
    try:
        with open(path) as f:
            imgs = {p["id"]: p["img"] for p in json.load(f)["ports"] if p.get("img")}
    except (FileNotFoundError, ValueError, KeyError):
        imgs = {}
    for p in index:
        if p["id"] in imgs:
            p["img"] = imgs[p["id"]]
    # A port shows in the app only once its places are saved.
    index = [p for p in index if os.path.exists(os.path.join(OUT, "ports", p["id"] + ".json"))]
    with open(path, "w") as f:
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
    if SHARD:
        todo = todo[SHARD[0]::SHARD[1]]
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
            data = {"elements": [el for q in queries(lat, lon, DENSE.get(pid)) for el in fetch(q).get("elements", [])]}
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
        out = {**entry, "places": places}
        keep_wiki(path, out)
        with open(path, "w") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        print(f"  {len(places)} places", flush=True)
        done += 1
        if done % 10 == 0:
            write_index(index)
            save_progress(f"Port places: {done} more ports")
        time.sleep(2)
    return failed


if __name__ == "__main__":
    main()
