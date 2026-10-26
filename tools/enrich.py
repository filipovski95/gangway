"""Add Wikipedia descriptions and photos to each port and its sights, and add
well-known landmarks near the pier that OpenStreetMap's tags missed.

Runs after fetch_places.py. Ports already enriched are skipped unless
ENRICH_ALL=1, so a refetched port (which loses these fields) is picked up again.
Text and photos come from English Wikipedia (CC BY-SA); the app links each one back.
"""
import gzip, json, math, os, re, sys, time, urllib.parse, urllib.request
from datetime import date

OUT = os.path.join(os.path.dirname(__file__), "..", "data")
API = "https://en.wikipedia.org/w/api.php"
UA = "Gangway/0.2 (offline cruise port guide; https://github.com/filipovski95/gangway)"
MAX_SIGHTS = 50

LANDMARK = re.compile(r"\b(church|cathedral|basilica|chapel|mosque|temple|shrine|synagogue|monastery|abbey|convent|museum|gallery|"
                      r"park|garden|fort|fortress|fortification|castle|palace|square|plaza|market|monument|memorial|statue|"
                      r"lighthouse|beach|bridge|tower|landmark|ruins|archaeolog|theatre|theater|opera|aquarium|zoo|"
                      r"waterfall|citadel|cemetery|library|city hall|town hall|old town|historic site|heritage site|"
                      r"walls|gate|fountain|viewpoint|promenade|pier|harbour|harbor|island|bay|cave|volcano|reef|lagoon)\b", re.I)
SKIP = re.compile(r"\b(school|university|college|station|airport|company|corporation|neighbou?rhood|district|borough|"
                  r"street|road|avenue|highway|electoral|constituency|ward|parish|municipality|census|"
                  r"railway|bus|ferry route|ship|shipwreck|hospital|stadium|arena|radio|television|newspaper|"
                  r"football|club|band|album|film|person|politician|footballer|businessman|eruption|battle|siege|earthquake|massacre|tunnel|channel|strait)\b", re.I)


def api(**params):
    params.update(action="query", format="json", formatversion=2)
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(5):
        body = b""
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", "Api-User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                data = json.loads(body)
                api.ok = True
                return data
        except Exception as e:
            t = re.search(rb"<title>(.*?)</title>", body or b"")
            print(f"  wikipedia: {e} {getattr(e, 'code', '')} {t[1][:160] if t else body[:160]!r} {url[:200]}", flush=True)
            time.sleep(3 + 5 * attempt)
    return {}


def pages(**params):
    """Run a generator query and follow continuation; returns page dicts."""
    out, cont = {}, {}
    for _ in range(10):
        data = api(**params, **cont)
        for p in data.get("query", {}).get("pages", []):
            q = out.setdefault(p["pageid"], {})
            for k, v in p.items():
                if v not in (None, "", []) and k not in q:
                    q[k] = v
        if "continue" not in data:
            break
        cont = data["continue"]
        time.sleep(0.3)
    return list(out.values())


DETAIL = dict(prop="coordinates|pageimages|extracts|description", exintro=1, explaintext=1,
              exsentences=3, exlimit="max", piprop="thumbnail", pithumbsize=640, colimit="max")


def dist_m(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return int(12742000 * math.asin(math.sqrt(a)))


def norm(s):
    s = re.sub(r"\(.*?\)", "", s.lower())
    return re.sub(r"[^a-z0-9]+", " ", s.replace("’", "'")).strip()


def clean(text, limit=420):
    text = re.sub(r"\s+", " ", re.sub(r"\(\s*[^()]*?(listen|pronounced|IPA)[^()]*\)", "", text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(". ", 1)[0]
    return cut + "." if len(cut) > 80 else text[:limit].rsplit(" ", 1)[0] + "…"


def coords(p):
    c = (p.get("coordinates") or [{}])[0]
    return c.get("lat"), c.get("lon")


def wiki_fields(pg):
    f = {"ds": clean(pg.get("extract")), "wpu": pg["title"]}
    if pg.get("thumbnail", {}).get("source"):
        f["img"] = pg["thumbnail"]["source"]
    return {k: v for k, v in f.items() if v}


def port_article(port):
    name = re.sub(r"\s*\(.*?\)", "", port["name"])
    for q in (f"{name} {port['country']}", name):
        found = pages(generator="search", gsrsearch=q, gsrlimit=6, **DETAIL)
        found.sort(key=lambda p: p.get("index", 99))
        for pg in found:
            la, lo = coords(pg)
            if la is None or "disambiguation" in (pg.get("description") or "").lower():
                continue
            if dist_m(port["lat"], port["lon"], la, lo) < 60000 and pg.get("extract"):
                return pg
        time.sleep(0.3)
    return None


def enrich(port):
    lat, lon = port["lat"], port["lon"]
    art = port_article(port)
    if art:
        about = wiki_fields(art)
        about["ds"] = clean(art.get("extract"), 700)
        port["about"] = about
    near = pages(generator="geosearch", ggscoord=f"{lat}|{lon}", ggsradius=10000, ggslimit=80, **DETAIL)
    by_title = {norm(p["title"]): p for p in near}
    used = set()
    sights = [p for p in port["places"] if p["g"] == "sights"]
    for pl in port["places"]:
        pg = None
        if pl.get("wp", "").startswith("en:"):
            pg = by_title.get(norm(pl["wp"][3:]))
            if pg is None:  # tagged article outside the 10 km search: fetch it by title
                got = pages(titles=pl["wp"][3:], redirects=1, **DETAIL)
                pg = got[0] if got and "missing" not in got[0] else None
        if pg is None and pl["g"] == "sights":
            pg = by_title.get(norm(pl["n"]))
        if pg and pg.get("extract"):
            pl.update(wiki_fields(pg))
            used.add(pg["pageid"])
    # Landmarks with a Wikipedia article that OpenStreetMap didn't tag as a sight.
    taken = {norm(p["n"]) for p in sights}
    added = []
    for pg in sorted(near, key=lambda p: p.get("index", 99)):
        if pg["pageid"] in used or norm(pg["title"]) in taken or not pg.get("extract"):
            continue
        desc = (pg.get("description") or "") + " " + pg["title"]
        la, lo = coords(pg)
        if la is None or SKIP.search(desc) or not LANDMARK.search(desc + " " + pg["extract"][:160]):
            continue
        if not pg.get("thumbnail"):
            continue  # an article without a photo is usually a minor entry
        if norm(pg["title"]) == norm(port["name"]):
            continue
        words = set(norm(pg["title"]).split()) - {"the", "of", "de", "la", "le", "st", "saint", "and"}
        if any(dist_m(s["la"], s["lo"], la, lo) < 80 or
               (dist_m(s["la"], s["lo"], la, lo) < 400 and words & set(norm(s["n"]).split()))
               for s in sights + added):
            continue  # the same place under another name
        added.append({"n": pg["title"], "g": "sights", "k": "landmark", "la": round(la, 6), "lo": round(lo, 6),
                      "d": dist_m(lat, lon, la, lo), **wiki_fields(pg)})
    room = max(0, MAX_SIGHTS - len(sights))
    added = sorted(added, key=lambda p: p["d"])[:room]
    port["places"] += added
    port["wk"] = date.today().isoformat()
    print(f"  about: {'yes' if art else 'no'}, sights with text: {sum(1 for p in port['places'] if p['g']=='sights' and p.get('ds'))}, added {len(added)}", flush=True)


def update_index():
    """Copy each port's photo into index.json so the port list can show it."""
    path = os.path.join(OUT, "index.json")
    with open(path) as f:
        index = json.load(f)
    for entry in index["ports"]:
        try:
            with open(os.path.join(OUT, "ports", f"{entry['id']}.json")) as f:
                about = json.load(f).get("about", {})
        except FileNotFoundError:
            continue
        if about.get("img"):
            entry["img"] = re.sub(r"/\d+px-", "/240px-", about["img"])
    with open(path, "w") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))


def main():
    only = set(sys.argv[1:])
    every = os.environ.get("ENRICH_ALL") == "1"
    files = sorted(os.listdir(os.path.join(OUT, "ports")))
    for i, fn in enumerate(files):
        path = os.path.join(OUT, "ports", fn)
        with open(path) as f:
            port = json.load(f)
        if (only and port["id"] not in only) or (not only and not every and port.get("wk")):
            continue
        print(f"{port['id']} {port['name']}", flush=True)
        api.ok = False
        try:
            enrich(port)
        except Exception as e:
            print(f"  skipped: {e}", flush=True)
            continue
        if not api.ok:  # Wikipedia never answered: leave the port to be tried next run
            print("  no answer from Wikipedia", flush=True)
            continue
        with open(path, "w") as f:
            json.dump(port, f, ensure_ascii=False, separators=(",", ":"))
        time.sleep(0.5)
    update_index()


if __name__ == "__main__":
    main()
