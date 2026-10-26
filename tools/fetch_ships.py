"""Fetch each Celebrity ship's upcoming itinerary and write data/ships.json,
so the app can tell crew which port their ship is in today and who else is in port.

Source: crew-center.com ship itinerary pages (port, arrival, departure, local times).
"""
import html, http.cookiejar, json, os, re, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
from ports_src import PORTS

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "ships.json")
UA = "Gangway/0.2 (offline cruise port guide for crew; https://github.com/filipovski95/gangway)"
SHIPS = ["Silhouette", "Xcel", "Ascent", "Beyond", "Apex", "Edge", "Reflection", "Eclipse", "Equinox",
         "Solstice", "Constellation", "Infinity", "Summit", "Millennium"]
# Itinerary names that don't contain our port's name.
ALIASES = {
    "prince edward island": "Charlottetown", "sydney ns": "Sydney (Nova Scotia)", "nova scotia": None,
    "new south wales": "Sydney", "cococay": "Perfect Day at CocoCay", "port everglades": "Fort Lauderdale",
    "cape liberty": "Cape Liberty (New York)", "bayonne": "Cape Liberty (New York)",
    "civitavecchia": "Rome (Civitavecchia)", "piraeus": "Athens (Piraeus)",
}


def norm(s):
    s = html.unescape(s).lower().replace("'", "").replace("’", "").replace("st.", "st ").replace("saint ", "st ")
    s = re.sub(r"\(([^)]*)\)", r" \1 ", s)
    return " " + re.sub(r"[^a-z0-9]+", " ", s).strip() + " "


# Our port names as word sequences, longest first so "Sydney (Nova Scotia)" wins over "Sydney".
NAMES = sorted(((norm(re.sub(r"\s*\(.*?\)", "", p[1])), p[0]) for p in PORTS), key=lambda x: -len(x[0]))
BY_NAME = {p[1]: p[0] for p in PORTS}


def port_id(raw):
    n = norm(raw)
    for alias, name in ALIASES.items():
        if f" {alias} " in n and name in BY_NAME:
            return BY_NAME[name]
        if f" {alias} " in n and name is None:
            break
    first = norm(raw.split(",")[0])
    for name, pid in NAMES:
        if name in first:
            return pid
    for name, pid in NAMES:
        if len(name) > 6 and name in n:
            return pid
    return None


def when(cell):
    m = re.search(r"(\d{1,2} \w{3} \d{4})\s*-\s*(\d{1,2}:\d{2})", cell)
    if not m:
        return None
    return datetime.strptime(f"{m[1]} {m[2]}", "%d %b %Y %H:%M").strftime("%Y-%m-%dT%H:%M")


def text(cell):
    return html.unescape(re.sub(r"<[^>]+>", " ", cell)).strip()


# The site sets a cookie and redirects to the same page, so keep cookies between requests.
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def get(url):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html", "Accept-Language": "en"})
            with OPENER.open(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            print(f"  {e} -> {e.headers.get('Location')} {e.read()[:200]!r}", flush=True)
        except Exception as e:
            print(f"  {e}", flush=True)
        time.sleep(5 + 10 * attempt)
    return None


def calls(page):
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(cells) < 3:
            continue
        name, a, d = cells[0], when(cells[1]), when(cells[2])
        if not (a or d) or re.search(r"\b(at sea|cruising|scenic)\b", name, re.I):
            continue
        # A turnaround day is listed as two rows (arrive, then depart); join them.
        if rows and rows[-1]["n"] == name and rows[-1]["d"] is None and a is None:
            rows[-1]["d"] = d
            continue
        rows.append({"n": name, "p": port_id(name), "a": a, "d": d})
    return rows


def main():
    try:
        with open(OUT) as f:
            old = {s["name"]: s for s in json.load(f)["ships"]}
    except (FileNotFoundError, KeyError, ValueError):
        old = {}
    ships = []
    for short in SHIPS:
        name = f"Celebrity {short}"
        print(name, flush=True)
        page = get(f"https://crew-center.com/celebrity-{short.lower()}-itinerary")
        rows = calls(page) if page else []
        if not rows and name in old:  # keep last week's schedule when a page fails
            ships.append(old[name])
            print("  kept previous schedule", flush=True)
            continue
        unknown = sorted({r["n"] for r in rows if not r["p"]})
        print(f"  {len(rows)} calls; not in guide: {unknown}", flush=True)
        ships.append({"name": name, "calls": rows})
        time.sleep(2)
    with open(OUT, "w") as f:
        json.dump({"updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
                   "source": "crew-center.com", "ships": ships}, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
