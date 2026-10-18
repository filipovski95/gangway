"""Which cruise ships are in port: read official port-authority cruise schedules and
merge them into data/ships.json (format: {"updated", "source", "ships": [{"name", "calls": [...]}]}).

Only official public schedules published by the port authority / harbour operator are used.
Each site has its own small parser; one failing site never breaks the others.

    python3 tools/port_schedules.py                 # fetch all sites, merge into data/ships.json
    python3 tools/port_schedules.py --test DIR      # run every parser on saved samples DIR/<key>*.html

Stdlib only (runs in GitHub Actions).
"""
import html as htmllib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "ships.json")
UA = "Gangway/0.2 (offline cruise port guide for crew; https://github.com/filipovski95/linguapath)"
TIMEOUT = 40
DELAY = 2.0
WINDOW_BACK, WINDOW_AHEAD = 1, 60

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}

# ---------------------------------------------------------------- ship names

# Lines whose ships are usually written without the brand ("Summit" -> "Celebrity Summit").
# (pattern matched against the line name given by the port, prefix to add)
LINE_PREFIX = [
    (r"celebrity", "Celebrity"),
    (r"oceania", "Oceania"),
    (r"holland america", "Holland America"),
    (r"cunard", "Cunard"),
    (r"ponant", "Ponant"),
    (r"windstar", "Windstar"),
    (r"virgin", "Virgin"),
]
# Ships known without a line from the page (Quebec, Bergen, Canaveral list ship only).
SHIP_PREFIX = {}
for _prefix, _ships in {
    "Celebrity": "Apex Ascent Beyond Constellation Eclipse Edge Equinox Flora Infinity Millennium Reflection "
                 "Silhouette Solstice Summit Xcel Xpedition Xploration",
    "Oceania": "Allura Insignia Marina Nautica Regatta Riviera Sirena Vista Sonata",
    "Holland America": "Eurodam Koningsdam Nieuw_Amsterdam Nieuw_Statendam Noordam Oosterdam Rotterdam "
                       "Volendam Westerdam Zaandam Zuiderdam",
    "Cunard": "Queen_Mary_2 Queen_Victoria Queen_Elizabeth Queen_Anne",
    "Virgin": "Scarlet_Lady Valiant_Lady Resilient_Lady Brilliant_Lady",
    "Ponant": "Le_Austral Le_Bellot Le_Boreal Le_Bougainville Le_Champlain Le_Commandant_Charcot "
              "Le_Dumont-d'Urville Le_Jacques_Cartier Le_Laperouse Le_Lyrial Le_Soleal",
}.items():
    for _s in _ships.split():
        SHIP_PREFIX[_s.replace("_", " ").lower()] = _prefix

KEEP_UPPER = {"MSC", "AIDA", "NG", "SH", "QM2", "TUI", "HX", "P&O", "USA", "NCL"}
ROMAN = re.compile(r"^(?=[IVX]+$)X{0,3}(IX|IV|V?I{0,3})$")
SMALL = {"of", "the", "de", "da", "la", "le", "del", "di"}


def smart_case(name):
    """'SEVEN SEAS SPLENDOR' -> 'Seven Seas Splendor', 'VICTORY II' -> 'Victory II', 'AIDADIVA' -> 'AIDAdiva'."""
    out = []
    for i, w in enumerate(name.split()):
        u = w.upper()
        if u in KEEP_UPPER or ROMAN.match(u):
            out.append(u)
        elif u.startswith("AIDA") and len(u) > 4:
            out.append("AIDA" + w[4:].lower())
        elif i > 0 and w.lower() in SMALL:
            out.append(w.lower())
        else:
            out.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
    return " ".join(out)


def ship_name(raw, line=None):
    n = re.sub(r"\s+", " ", htmllib.unescape(raw or "")).strip(" *.")
    n = re.sub(r"^(m/?s|m/?v|ms\.)\s+", "", n, flags=re.I)
    if not n or re.match(r"(refer\b|tba\b|tbc\b|tbn\b|unknown|vessel\b|n/?a$)", n, re.I):
        return ""
    if n.isupper() or n.islower() or n[:1].islower() or re.search(r"\b[a-z]", n) or "Msc " in n:
        n = smart_case(n)
    prefix = None
    if line:
        for pat, pre in LINE_PREFIX:
            if re.search(pat, line, re.I):
                prefix = pre
                break
    prefix = prefix or SHIP_PREFIX.get(n.lower())
    if prefix and not n.lower().startswith(prefix.lower()):
        n = f"{prefix} {n}"
    return n


# ---------------------------------------------------------------- helpers

def text(s):
    s = re.sub(r"<br\s*/?>", " ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", htmllib.unescape(s)).strip()


def cells(row):
    return re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S | re.I)


def iso(y, m, d, hm=None):
    try:
        dt = datetime(int(y), int(m), int(d))
    except ValueError:
        return None
    if hm:
        mt = re.search(r"(\d{1,2})[:h.](\d{2})\s*([ap]\.?m\.?)?", hm, re.I)
        if mt:
            hh, mm = int(mt[1]), int(mt[2])
            if mt[3]:
                hh = hh % 12 + (12 if mt[3][0].lower() == "p" else 0)
            if hh == 24:
                hh, mm = 23, 59
            if hh < 24 and mm < 60:
                return dt.replace(hour=hh, minute=mm).strftime("%Y-%m-%dT%H:%M")
    return dt.strftime("%Y-%m-%dT00:00") if hm is None else None


def call(raw, line, port, a, d):
    return {"raw": raw, "line": line, "p": port, "a": a, "d": d}


# ---------------------------------------------------------------- parsers
# Each parser: (html, today: date) -> list of call() dicts.

def parse_quebec(h, today):
    """portquebec.ca: <td data-date="2026-10-18 05:30:00"> columns: ship, arrival, departure, type..."""
    out = []
    body = h[h.find("<tbody"):] if "<tbody" in h else h
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.S):
        c = re.findall(r"<td\b([^>]*)>(.*?)</td>", row, re.S)
        if len(c) < 3:
            continue
        name = text(c[0][1])
        dates = []
        for attrs, inner in c[1:3]:
            m = re.search(r'data-date="(\d{4})-(\d\d)-(\d\d) (\d\d:\d\d)', attrs)
            dates.append(iso(m[1], m[2], m[3], m[4]) if m else None)
        if name and (dates[0] or dates[1]):
            out.append(call(name, None, "yqb", dates[0], dates[1]))
    return out


def parse_montreal(h, today):
    """port-montreal.com: Origin | Arrival 'April 24, 2026<br>08:00' | Destination | Departure | Vessel | Line | ..."""
    out = []
    for row in re.findall(r'<tr class="row\d[^"]*"[^>]*>(.*?)</tr>', h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 6:
            continue

        def dt(s):
            m = re.search(r"([A-Za-z]+)\.? (\d{1,2}), (\d{4}) (\d{1,2}:\d\d)", s)
            if not m or m[1][:3].lower() not in MONTHS:
                return None
            return iso(m[3], MONTHS[m[1][:3].lower()], m[2], m[4])
        if re.search(r"cancel|annul", row, re.I) and "cancellable-text" not in row:
            continue
        a, d = dt(c[1]), dt(c[3])
        if c[4] and (a or d):
            out.append(call(c[4], c[5] or None, "ymq", a, d))
    return out


def parse_canaveral(h, today):
    """portcanaveral.com: <tr data-eta=..> Status | Vessel | Berth | Arr date m/d/yyyy | ETA | draft | Dep date | ETD | draft | Cargo type"""
    out = []
    for row in re.findall(r"<tr\b[^>]*data-eta[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 10 or c[9].lower() != "passenger":
            continue

        def dt(day, hm):
            m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", day)
            return iso(m[3], m[1], m[2], hm or "00:00") if m else None
        a, d = dt(c[3], c[4]), dt(c[6], c[7])
        if c[1] and (a or d):
            out.append(call(c[1], None, "pcv", a, d))
    return out


def parse_halifax(h, today):
    """porthalifax.ca: monthly tables Date 'MM-DD' | Vessel | Line | Pax | Arrival | Departure | Pier.
    Overnight calls are split: arrival-only row then departure-only row (next day)."""
    m = re.search(r"(\d{4}) Cruise Schedule", h)
    year = int(m[1]) if m else today.year
    rows = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 6 or not re.match(r"\d\d-\d\d$", c[0]):
            continue
        mo, dy = c[0].split("-")
        a = iso(year, mo, dy, c[4]) if c[4] else None
        d = iso(year, mo, dy, c[5]) if c[5] else None
        rows.append([c[1], c[2], a, d, c[0]])
    out, used = [], set()
    for i, (name, line, a, d, md) in enumerate(rows):
        if i in used:
            continue
        if a and not d:  # look for its departure-only row within 3 days
            for j in range(i + 1, min(i + 40, len(rows))):
                n2, _, a2, d2, _ = rows[j]
                if j not in used and n2 == name and d2 and not a2 and d2 > a and d2[:10] <= (
                        datetime.fromisoformat(a) + timedelta(days=3)).strftime("%Y-%m-%d"):
                    d = d2
                    used.add(j)
                    break
        if a or d:
            out.append(call(name, line, "hfx", a, d))
    return out


def parse_charlottetown(h, today):
    """portcharlottetown.com: Arrival 'Oct 17, 2026<br>6:30 am' | Departure | Ship | Line | Pax | Crew | Status"""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 7 or re.search(r"cancel", c[6], re.I):
            continue

        def dt(s):
            m = re.search(r"([A-Za-z]{3})[a-z]*\.? (\d{1,2}), (\d{4})\s*(\d{1,2}:\d\d\s*[ap]\.?m\.?)?", s, re.I)
            if not m or m[1].lower() not in MONTHS:
                return None
            return iso(m[3], MONTHS[m[1].lower()], m[2], m[4]) if m[4] else None
        a, d = dt(c[0]), dt(c[1])
        if c[2] and (a or d):
            out.append(call(c[2], c[3] or None, "yyg", a, d))
    return out


def parse_sydney_au(h, today):
    """portauthoritynsw.com.au: Vessel | Arrival 'Mon 19 Oct 2026<br>06:30' | Departure 'Mon 19 Oct<br>15:30' | Berth | Agent | Line"""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 6:
            continue
        ma = re.search(r"(\d{1,2}) ([A-Za-z]{3}) (\d{4})\s+(\d{1,2}:\d\d)", c[1])
        md = re.search(r"(\d{1,2}) ([A-Za-z]{3})(?: (\d{4}))?\s+(\d{1,2}:\d\d)", c[2])
        a = d = None
        if ma and ma[2].lower() in MONTHS:
            a = iso(ma[3], MONTHS[ma[2].lower()], ma[1], ma[4])
        if md and md[2].lower() in MONTHS:
            mon = MONTHS[md[2].lower()]
            yr = int(md[3]) if md[3] else (int(ma[3]) if ma else today.year)
            if not md[3] and ma and mon < MONTHS.get(ma[2].lower(), mon):
                yr += 1  # departs in January after a December arrival
            d = iso(yr, mon, md[1], md[4])
        if c[0] and (a or d):
            out.append(call(c[0], c[5] or None, "sya", a, d))
    return out


def parse_bergen(h, today):
    """bergenhavn.no arrivals list (server-rendered Nuxt): sr-only labels ARRIVAL/SHIP/SHIP TYPE/.../DEPARTURE 'dd.mm.yy - HH:MM'"""
    out = []
    for block in re.findall(r"<button[^>]*>(.*?)</button>", h, re.S):
        f = dict((k.strip().rstrip(":").upper(), text(v)) for k, v in re.findall(
            r'<span class="sr-only">([^<]+)</span>(.*?)</span>', block, re.S))
        if "cruise" not in f.get("SHIP TYPE", "").lower():
            continue

        def dt(s):
            m = re.search(r"(\d\d)\.(\d\d)\.(\d\d)\s*-\s*(\d\d:\d\d)", s or "")
            return iso(2000 + int(m[3]), m[2], m[1], m[4]) if m else None
        a, d = dt(f.get("ARRIVAL")), dt(f.get("DEPARTURE"))
        if f.get("SHIP") and (a or d):
            out.append(call(f["SHIP"], None, "bgo", a, d))
    return out


def parse_victoria(h, today):
    """gvha.ca (Ogden Point): div rows: Date(data-raw=ISO) | Vessel | ETA | Status | Revised | ETD | #Pass | Berth,
    followed by a details div 'Line | To: .. | From: ..'."""
    out = []
    for item, details in re.findall(
            r'<div class="c-cruise-table-sailing-item">(.*?)<div class="u-detail-trigger">.*?'
            r'<div class="c-cruise-table-sailing-details">(.*?)</div>', h, re.S):
        m = re.search(r'data-raw="(\d{4})-(\d\d)-(\d\d)', item)
        c = [text(x) for x in re.findall(r"<div\b[^>]*>(.*?)</div>", item, re.S)]
        if not m or len(c) < 6 or re.search(r"cancel", c[3], re.I):
            continue
        a = iso(m[1], m[2], m[3], c[2]) if c[2] else None
        d = iso(m[1], m[2], m[3], c[5]) if c[5] else None
        if a and d and d < a:  # departs after midnight
            d = (datetime.fromisoformat(d) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        line = text(details).split("|")[0].strip() or None
        if c[1] and (a or d):
            out.append(call(c[1], line, "yyj", a, d))
    return out


def parse_helsinki(h, today):
    """portofhelsinki.fi: Arrival 'dd.mm.yyyy HH:MM' | Ship | Line | From | Harbour | Berth | Departure | To"""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 7:
            continue

        def dt(s):
            m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\s+(\d{1,2}:\d\d)", s)
            return iso(m[3], m[2], m[1], m[4]) if m else None
        a, d = dt(c[0]), dt(c[6])
        if c[1] and (a or d):
            out.append(call(c[1], c[2] or None, "hel", a, d))
    return out


def _dmy(s):
    """'16/10/2026 14:00' or '16.10.2026 14:00' -> ISO"""
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})\s+(\d{1,2}:\d\d)", s or "")
    return iso(m[3], m[2], m[1], m[4]) if m else None


def parse_cork(h, today):
    """portofcork.ie print schedule: Arrival date | Vessel | Berth | Arrival | Departure | Line | Pax | Agent | IMO
    (Cobh Cruise Terminal, Cork City and Ringaskiddy berths are all 'Cork (Cobh)')."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 6:
            continue
        a, d = _dmy(c[3]) or _dmy(c[0]), _dmy(c[4])
        if c[1] and (a or d):
            out.append(call(c[1], c[5] or None, "cob", a, d))
    return out


def parse_tallinn(h, today):
    """ts.ee: <tr class="tr-parent"> Arrival 'dd.mm.yyyy HH:MM' | Departure | Port of arrival | Ship | Agent | Quay
    (Saaremaa calls are skipped - not Tallinn)."""
    out = []
    for row in re.findall(r'<tr class="tr-parent"[^>]*>(.*?)</tr>', h, re.S):
        c = [text(re.sub(r'<span class="table__mobile-title">.*?</span>', "", x, flags=re.S)) for x in cells(row)]
        if len(c) < 4 or "saaremaa" in c[2].lower():
            continue
        a, d = _dmy(c[0]), _dmy(c[1])
        if c[3] and (a or d):
            out.append(call(c[3], None, "tll", a, d))
    return out


# ---------------------------------------------------------------- fetching

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8",
                                               "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")


def get_paged_montreal(url):
    """Joomla list with ?start=20, 40, ... pagination; follow 'next page' links (max 10 pages)."""
    pages, seen = [], set()
    while url and url not in seen and len(pages) < 10:
        seen.add(url)
        h = get(url)
        pages.append(h)
        m = re.search(r'href="([^"]+)"[^>]*>\s*<span class="icon-angle-right"', h) or \
            re.search(r'aria-label="Go to next page" href="([^"]+)"', h)
        url = urllib.parse.urljoin(url, htmllib.unescape(m[1])) if m else None
        if url:
            time.sleep(DELAY)
    return pages


# key: sample-file prefix for --test
SOURCES = [
    {"key": "yqb", "name": "Quebec City", "url": "https://www.portquebec.ca/en/cruises/cruise-schedule/", "parse": parse_quebec},
    {"key": "ymq", "name": "Montreal", "url": "https://www.port-montreal.com/en/cruises/arrivals-and-departures",
     "parse": parse_montreal, "fetch": get_paged_montreal},
    {"key": "pcv", "name": "Port Canaveral (Orlando)", "url": "https://www.portcanaveral.com/port-operations/ship-schedule", "parse": parse_canaveral},
    {"key": "hfx", "name": "Halifax", "url": "https://www.porthalifax.ca/cruise/cruise-schedule/", "parse": parse_halifax},
    {"key": "yyg", "name": "Charlottetown", "url": "https://portcharlottetown.com/cruise-schedule/", "parse": parse_charlottetown},
    {"key": "sya", "name": "Sydney", "url": "https://www.portauthoritynsw.com.au/cruise/sydney-harbour/sydney-harbour-full-cruise-schedule",
     "parse": parse_sydney_au},
    {"key": "bgo", "name": "Bergen", "url": "https://www.bergenhavn.no/en/arrivals", "parse": parse_bergen},
    {"key": "yyj", "name": "Victoria", "url": "https://gvha.ca/cruise-landing-page/cruise-schedule/current-season/",
     "parse": parse_victoria},
    {"key": "hel", "name": "Helsinki",
     "url": "https://www.portofhelsinki.fi/en/passengers/information-for-passengers/international-cruise-ships/",
     "parse": parse_helsinki},
    {"key": "tll", "name": "Tallinn", "url": "https://www.ts.ee/en/cruise-schedules/", "parse": parse_tallinn},
    {"key": "cob", "name": "Cork (Cobh)", "url": "https://www.portofcork.ie/print-cruise-schedule.php", "parse": parse_cork},
]


def finish(raw_calls, port_names, today, window=True):
    """raw calls -> [{"name", "calls": [{"n","p","a","d"}]}], normalised, windowed, merged, de-duplicated."""
    lo = (today - timedelta(days=WINDOW_BACK)).isoformat()
    hi = (today + timedelta(days=WINDOW_AHEAD)).isoformat() + "T23:59"
    # A ship listed with its line at one port gets the same prefix at ports that list only the ship.
    learned = {}
    for c in raw_calls:
        if c["line"]:
            full = ship_name(c["raw"], c["line"])
            learned.setdefault(ship_name(c["raw"]).lower(), full)
    ships = {}
    for c in raw_calls:
        name = ship_name(c["raw"], c["line"])
        if not c["line"]:
            name = learned.get(name.lower(), name)
        if not name:
            continue
        a, d = c["a"], c["d"]
        if window and ((d or a) < lo or (a or d) > hi):
            continue
        ships.setdefault(name, set()).add((c["p"], a, d))
    out = []
    for name in sorted(ships):
        calls = sorted(ships[name], key=lambda t: (t[1] or t[2], t[0]))
        out.append({"name": name, "calls": [{"n": port_names.get(p, p), "p": p, "a": a, "d": d} for p, a, d in calls]})
    return out


def port_names():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from ports_src import PORTS
        return {p[0]: p[1] for p in PORTS}
    except Exception:
        return {s["key"]: s["name"] for s in SOURCES}


def fetch_all(sources=None, today=None, _covered=None):
    """Fetch every official schedule; returns [{"name": ..., "calls": [...]}] (see module docstring)."""
    today = today or datetime.now(timezone.utc).date()
    raw = []
    for i, s in enumerate(sources or SOURCES):
        if i:
            time.sleep(DELAY)
        try:
            pages = s["fetch"](s["url"]) if "fetch" in s else [get(s["url"])]
            got = [c for h in pages for c in s["parse"](h, today)]
            if not got:
                raise ValueError("no calls parsed (layout changed?)")
            raw += got
            if _covered is not None:
                _covered.add(got[0]["p"])
            print(f"ok   {s['name']}: {len(got)} calls")
        except Exception as e:  # one site must never break the others
            print(f"WARN {s['name']}: {type(e).__name__}: {str(e)[:160]}")
    return finish(raw, port_names(), today)


def merge(path, ships, covered, today):
    try:
        with open(path, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = {}
    lo = (today - timedelta(days=WINDOW_BACK)).isoformat()
    by = {}
    for s in old.get("ships", []):
        keep = [c for c in s.get("calls", []) if c.get("p") not in covered and (c.get("d") or c.get("a") or "") >= lo]
        by[s["name"]] = {(c.get("p"), c.get("a"), c.get("d")): c for c in keep}
    for s in ships:
        d = by.setdefault(s["name"], {})
        for c in s["calls"]:
            d[(c["p"], c["a"], c["d"])] = c
    out = {
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "source": "official port schedules",
        "ships": [{"name": n, "calls": sorted(cs.values(), key=lambda c: (c["a"] or c["d"] or "", c["p"]))}
                  for n, cs in by.items()],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    return out


def run_tests(folder):
    names, ok = port_names(), True
    for s in SOURCES:
        files = sorted(f for f in os.listdir(folder) if re.match(rf"{s['key']}(_p\d+)?\.html$", f))
        if not files:
            print(f"SKIP {s['name']}: no sample {s['key']}.html")
            continue
        raw = []
        for f in files:
            with open(os.path.join(folder, f), encoding="utf-8") as fh:
                raw += s["parse"](fh.read(), date.today())
        ships = finish(raw, names, date.today(), window=False)
        rows = [(sh["name"], c) for sh in ships for c in sh["calls"]]
        rows.sort(key=lambda r: r[1]["a"] or r[1]["d"])
        bad = [r for r in rows if not (r[1]["a"] or r[1]["d"]) or (r[1]["a"] and r[1]["d"] and r[1]["d"] < r[1]["a"])]
        status = "PASS" if rows and not bad else "FAIL"
        ok &= status == "PASS"
        print(f"{status} {s['name']} ({', '.join(files)}): {len(rows)} calls, {len(ships)} ships"
              + (f", {len(bad)} bad rows e.g. {bad[0]}" if bad else ""))
        for name, c in rows[:1] + rows[len(rows) // 2:len(rows) // 2 + 1]:
            print(f"     {name:28} {json.dumps(c, ensure_ascii=False)}")
    # name normalisation checks
    for raw, line, want in [("SUMMIT", None, "Celebrity Summit"), ("VISTA", "Oceania Cruises", "Oceania Vista"),
                            ("VICTORY II", None, "Victory II"), ("Silver shadow", None, "Silver Shadow"),
                            ("ZUIDERDAM", "HOLLAND AMERICA LINE INC.", "Holland America Zuiderdam"),
                            ("AIDADIVA", None, "AIDAdiva"), ("Msc Preziosa", None, "MSC Preziosa"),
                            ("JEWEL OF THE SEAS", None, "Jewel of the Seas"), ("CELEBRITY EDGE", None, "Celebrity Edge")]:
        got = ship_name(raw, line)
        if got != want:
            ok = False
            print(f"FAIL name {raw!r}/{line!r} -> {got!r}, want {want!r}")
    print("ALL PASS" if ok else "SOME FAILED")
    return ok


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--test":
        sys.exit(0 if run_tests(sys.argv[2]) else 1)
    today = datetime.now(timezone.utc).date()
    covered = set()
    ships = fetch_all(today=today, _covered=covered)
    res = merge(OUT, ships, covered, today)
    print(f"wrote {OUT}: {sum(len(s['calls']) for s in res['ships'])} calls, {len(res['ships'])} ships, ports {sorted(covered)}")
