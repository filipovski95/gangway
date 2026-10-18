"""Which cruise ships are in port: read official port-authority cruise schedules and
merge them into data/ships.json (format: {"updated", "source", "ships": [{"name", "calls": [...]}]}).

Only public schedules published by the port authority, cruise-terminal operator, VTS or pilots are used
(no aggregators). Each site has its own small parser; one failing site never breaks the others.

    python3 tools/port_schedules.py                 # fetch all sites, merge into data/ships.json
    python3 tools/port_schedules.py --test DIR      # run every parser on saved samples DIR/<key>*.html

Stdlib only, except Port Everglades, which is rendered in headless Chrome (`pip install selenium`, imported
lazily: without it only that source fails).
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
    if n.isupper() or n.islower() or n[:1].islower() or re.search(r"\b[a-z]", n) or "Msc " in n \
            or re.search(r" (Of|The) ", n) or re.match(r"Aida[a-z]", n):  # 'Utopia Of The Seas', 'Aidablu'
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


def pair_moves(events, port, max_days=5):
    """Movement lists (pilots / vessel traffic) -> calls.
    events: (ship, line, 'A'|'D', iso). An arrival is paired with the same ship's next departure;
    a departure with no arrival in the list (ship already alongside) becomes a departure-only call."""
    by = {}
    for ev in sorted(events, key=lambda e: e[3]):
        by.setdefault(ev[0].upper(), []).append(ev)
    out = []
    for evs in by.values():
        arr = None
        for name, line, kind, t in evs:
            if kind == "A":
                if arr:
                    out.append(call(arr[0], arr[1], port, arr[3], None))
                arr = (name, line, kind, t)
            elif arr and datetime.fromisoformat(t) - datetime.fromisoformat(arr[3]) <= timedelta(days=max_days):
                out.append(call(name, line, port, arr[3], t))
                arr = None
            else:
                if arr:
                    out.append(call(arr[0], arr[1], port, arr[3], None))
                    arr = None
                out.append(call(name, line, port, None, t))
        if arr:
            out.append(call(arr[0], arr[1], port, arr[3], None))
    return out


def parse_everglades(h, today):
    """Port Everglades vessel traffic (pevvesseltraffic.broward.org, Broward County WebX public view, rendered DOM):
    <tr id=.. role="row"> Status | Start 'mm/dd/yyyy HH:MM' | ARR/DEP/SHFT | Vessel | From | To | Line | Agency |
    Stevedore | Last port | Next port | Cargo type 'CRUISE - MULTI-DAY' | Tug | Orientation.
    Only multi-day cruise ships (the daily Bimini ferry is skipped)."""
    ev = []
    for row in re.findall(r'<tr id="\d+"[^>]*role="row"[^>]*>(.*?)</tr>', h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 12 or "CRUISE" not in c[11].upper() or "DAILY" in c[11].upper():
            continue
        if re.search(r"cancel", c[0], re.I) or c[2] not in ("ARR", "DEP"):
            continue
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}:\d\d)", c[1])
        t = iso(m[3], m[1], m[2], m[4]) if m else None
        if c[3] and t:
            ev.append((c[3], c[6] or None, c[2][0], t))
    return pair_moves(ev, "fll")


def parse_bbpilots(h, today):
    """PortMiami via Biscayne Bay Pilots (bbpilots.com, server-rendered): day header
    <th class="day-title">Sun, Oct 18, 2026</th>, then service rows ARRIVAL/DEPARTURE | time | vessel + vessel-type.
    Times are pilot times (boarding at the sea buoy for arrivals, roughly the sailing time for departures)."""
    ev, day = [], None
    for m in re.finditer(r'<th class="day-title"[^>]*>(.*?)</th>|<tr class="service-row"[^>]*>(.*?)</tr>', h, re.S):
        if m[1]:
            d = re.search(r"([A-Za-z]{3})[a-z]* (\d{1,2}), (\d{4})", text(m[1]))
            day = (d[3], MONTHS.get(d[1].lower()), d[2]) if d else None
            continue
        r = m[2]
        kind = re.search(r'class="action-col">\s*<div[^>]*>\s*<div>\s*(\w+)', r)
        tm = re.search(r'class="service-time-col">\s*(\d{1,2}:\d\d)', r)
        v = re.search(r'font-weight-bold[^"]*">([^<]+)</div>\s*<div class="vessel-type">([^<]*)', r)
        if not (day and day[1] and kind and tm and v) or "CRUISE" not in v[2].upper():
            continue
        k = {"ARRIVAL": "A", "DEPARTURE": "D"}.get(kind[1].upper())
        t = iso(day[0], day[1], day[2], tm[1])
        if k and t:
            ev.append((text(v[1]), None, k, t))
    return pair_moves(ev, "mia")


def parse_southampton(h, today):
    """southamptonvts.co.uk (ABP Southampton VTS): Ship Name | Berth | Arrival '18-Oct-26 06:27' | Departure | Agent.
    Far-off calls show 'AM'/'PM'/'TBA' instead of a time; those halves are left empty."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 4:
            continue

        def dt(s):
            m = re.search(r"(\d{1,2})-([A-Za-z]{3})-(\d{2,4})\s+(\d{1,2}:\d\d)", s)
            if not m or m[2].lower() not in MONTHS:
                return None
            y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            return iso(y, MONTHS[m[2].lower()], m[1], m[4])
        a, d = dt(c[2]), dt(c[3])
        if c[0] and (a or d):
            out.append(call(c[0], None, "sou", a, d))
    return out


def parse_cmp(h, today):
    """Copenhagen Malmö Port 'ships in port' (cmport.com): one <div class="singleCall"> per call with
    'columnTitle : ' / 'columnValue' pairs (Vessel name, Vessel type, Terminal, Purpose, ETD '19 Oct - 26 at 1700')
    and the ETA in the header. Copenhagen and Visby quays are kept (Malmö has no port page in the app)."""
    out = []

    def dt(s):
        m = re.search(r"(\d{1,2}) ([A-Za-z]{3})[a-z]* - (\d{2}) at (\d\d)(\d\d)", s or "")
        if not m or m[2].lower() not in MONTHS:
            return None
        return iso(2000 + int(m[3]), MONTHS[m[2].lower()], m[1], f"{m[4]}:{m[5]}")
    for b in h.split('<div class="singleCall')[1:]:
        f = {text(k).rstrip(" :"): text(v) for k, v in re.findall(
            r'<span class="columnTitle">(.*?)</span>\s*<span class="columnValue">(.*?)</span>', b, re.S)}
        if "cruise" not in (f.get("Vessel type", "") + f.get("Purpose", "")).lower():
            continue
        q = re.search(r'To quay <span class="greenColored">\s*([^<]*?)\s*<', b)
        quay, term = (q[1] if q else "").upper(), f.get("Terminal", "").lower()
        port = "vby" if "visby" in term or quay.startswith("V") else "cph" if quay.startswith("C") else None
        head = re.search(r"\d{1,2} [A-Za-z]{3}[a-z]* - \d{2} at \d{4}", text(b[:3000]))
        a, d = dt(head[0] if head else None), dt(f.get("ETD"))
        name = f.get("Vessel name")
        if port and name and (a or d) and not re.search(r"cancel", f.get("Status", ""), re.I):
            out.append(call(name, None, port, a, d))
    return out


def parse_stmaarten(h, today):
    """Port St. Maarten (gls.portstmaarten.sx, ASP.NET grid myControl_grdCargoShipSchedules, one month per page):
    Date 'dd-mm' | Day | Time '07:00 - 17:00' | Homeport | CRN | Vessel | Remarks | Pier; year = selected ddlYear."""
    m = re.search(r'name="myControl\$ddlYear".*?<option[^>]*selected[^>]*value="(\d{4})"', h, re.S) or \
        re.search(r'name="myControl\$ddlYear".*?<option[^>]*value="(\d{4})"[^>]*selected', h, re.S)
    year = int(m[1]) if m else today.year
    i = h.find("myControl_grdCargoShipSchedules")
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h[i:h.find("</table>", i)] if i >= 0 else "", re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 6 or not re.match(r"\d\d-\d\d$", c[0]) or re.search(r"cancel", c[6] if len(c) > 6 else "", re.I):
            continue
        dy, mo = c[0].split("-")
        t = re.match(r"(\d{1,2}:\d\d)\s*-\s*(\d{1,2}:\d\d)", c[2])
        a = iso(year, mo, dy, t[1]) if t else None
        d = iso(year, mo, dy, t[2]) if t else None
        if a and d and d < a:  # leaves after midnight
            d = (datetime.fromisoformat(d) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        if c[5] and (a or d):
            out.append(call(c[5], None, "sxm", a, d))
    return out


def gph_parser(port):
    """Global Ports Holding cruise-port sites (WordPress theme 'mbcglobalports'): includes/api/schedule-pdf.php
    returns a JSON list {Cruiseline, Ship Name, Arrival Date, ETA, Departure Date, ETD, Berth, Status, ...}.
    Placeholder rows (ETA == ETD) and ferries are skipped."""
    def parse(h, today):
        i, j = h.find("["), h.rfind("]")
        rows = json.loads(htmllib.unescape(h[i:j + 1])) if 0 <= i < j else []
        out = []
        for r in rows:
            if not isinstance(r, dict) or re.search(r"cancel", str(r.get("Status", "")), re.I):
                continue
            line = (r.get("Cruiseline") or "").strip() or None
            if line and re.search(r"ferr", line, re.I):
                continue

            def dt(day, hm):
                m = re.match(r"(\d{4})-(\d\d)-(\d\d)", day or "")
                return iso(m[1], m[2], m[3], hm) if m and hm else None
            a, d = dt(r.get("Arrival Date"), r.get("ETA")), dt(r.get("Departure Date"), r.get("ETD"))
            if a and a == d:
                continue
            name = re.sub(r"\s*\(\d{4}\)$", "", (r.get("Ship Name") or "").strip())  # 'Rotterdam (2020)'
            if name and (a or d):
                out.append(call(name, line, port, a, d))
        return out
    parse.__name__ = f"parse_gph_{port}"
    return parse


# ---------------------------------------------------------------- fetching

_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())


def get(url, data=None):
    """GET (or form POST when data is a dict). HTTP errors propagate as 'HTTPError: HTTP Error 403: ...'."""
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8",
                                                          "Accept-Language": "en"})
    with _opener.open(req, timeout=TIMEOUT) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")


def get_paged_montreal(url):
    """Joomla list, 20 rows per page via ?start=20, 40, ... The season's upcoming calls are on the LAST pages, so
    walk the offsets directly (not only 'next' links) until a page has no new rows (max 10 pages)."""
    pages, prev = [], None
    for n in range(10):
        u = url if n == 0 else f"{url}{'&' if '?' in url else '?'}start={20 * n}"
        h = get(u)
        rows = [(c["raw"], c["a"], c["d"]) for c in parse_montreal(h, date.today())]
        if n and (not rows or rows == prev):
            break
        pages.append(h)
        prev = rows
        time.sleep(DELAY)
    return pages


CANAVERAL_SUITELET = ("https://3867087.extforms.netsuite.com/app/site/hosting/scriptlet.nl?script=1183&deploy=1"
                      "&compid=3867087&ns-at=AAEJ7tMQo3zDG9o8drR5sYhZx-SzIrCmA26Jo-BI8lM707JC8Hc")


def get_canaveral(url):
    """The ship-schedule page fills its table with JavaScript from a public NetSuite form whose URL is printed in the
    page (<p id="suitelet-url">). Read that URL (fallback: the one seen in Oct 2026) and fetch the cruise table."""
    su = CANAVERAL_SUITELET
    try:
        m = re.search(r'id="suitelet-url"[^>]*>\s*([^<\s]+)', get(url))
        if m:
            su = htmllib.unescape(m[1])
    except Exception as e:
        print(f"     Canaveral page: {type(e).__name__}: {str(e)[:100]} - using stored form URL")
    if "type=" not in su:
        su += "&type=Cruise"
    return [get(su)]


def render(url, wait_css, timeout=90):
    """Headless Chrome for pages that load their data with JavaScript (needs `pip install selenium` and Chrome;
    both are on GitHub's ubuntu runners - Selenium Manager finds the driver)."""
    from selenium import webdriver  # lazy: only this source needs it
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    o = webdriver.ChromeOptions()
    for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--window-size=1600,1200"):
        o.add_argument(arg)
    drv = webdriver.Chrome(options=o)
    try:
        drv.set_page_load_timeout(timeout)
        drv.get(url)
        try:
            WebDriverWait(drv, timeout).until(lambda d: d.find_elements(By.CSS_SELECTOR, wait_css))
        except Exception:
            src = drv.page_source
            raise RuntimeError(f"no rows after {timeout}s; title={drv.title!r} rows={src.count('<tr')} "
                               f"start={re.sub(r'\s+', ' ', src[:300])!r}")
        time.sleep(3)  # let the grid finish filling
        return drv.page_source
    finally:
        drv.quit()


def get_everglades(url):
    return [render(url, 'tr[role="row"][id]')]


def get_stmaarten(url):
    """Current month as served, plus next month via the page's own month selector (ASP.NET postback)."""
    h = get(url)
    pages = [h]
    try:
        today = date.today()
        nxt = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        form = dict(re.findall(r'<input[^>]*type="hidden"[^>]*name="([^"]+)"[^>]*value="([^"]*)"', h))
        form = {k: htmllib.unescape(v) for k, v in form.items()}
        form.update({"myControl$ddlYear": str(nxt.year), "myControl$ddlMonth": str(nxt.month),
                     "myControl$btnSearch": "Search", "__EVENTTARGET": "", "__EVENTARGUMENT": ""})
        time.sleep(DELAY)
        pages.append(get(url, form))
    except Exception as e:
        print(f"     St. Maarten next month: {type(e).__name__}: {str(e)[:100]}")
    return pages


def get_gph(url):
    """url has {lo}/{hi} placeholders for the date range (yesterday .. +WINDOW_AHEAD days)."""
    today = date.today()
    return [get(url.format(lo=(today - timedelta(days=WINDOW_BACK)).isoformat(),
                           hi=(today + timedelta(days=WINDOW_AHEAD)).isoformat()))]


GPH_API = "/wp-content/themes/mbcglobalports/includes/api/schedule-pdf.php?lang=en&param2={lo}&param4={hi}"
# (port id, name, site) - Global Ports Holding cruise ports that publish the schedule JSON
GPH_SITES = [
    ("nas", "Nassau", "https://nassaucruiseport.com"),
    ("sju", "San Juan", "https://www.sanjuancruiseport.com"),
    ("anu", "Antigua", "https://antiguacruiseport.com"),
    ("slu", "St. Lucia", "https://saintluciacruiseport.com"),
    ("bcn", "Barcelona", "https://bcncruiseport.com"),
    ("mlt", "Valletta", "https://www.vallettacruiseport.com"),
    ("agp", "Malaga", "https://malagacruiseport.com"),
    ("alc", "Alicante", "https://alicantecruiseport.es"),
    ("cag", "Cagliari", "https://cagliaricruiseport.com"),
    ("ace", "Lanzarote", "https://lanzarotecruiseport.com"),
    ("bjv", "Bodrum", "https://bodrumcruiseport.com"),
    ("zad", "Zadar", "https://zadarcruiseport.com"),
    ("bar", "Bar", "https://barcruiseport.com"),
]


# key: sample-file prefix for --test
SOURCES = [
    {"key": "yqb", "name": "Quebec City", "url": "https://www.portquebec.ca/en/cruises/cruise-schedule/", "parse": parse_quebec},
    {"key": "ymq", "name": "Montreal", "url": "https://www.port-montreal.com/en/cruises/arrivals-and-departures",
     "parse": parse_montreal, "fetch": get_paged_montreal},
    {"key": "pcv", "name": "Port Canaveral (Orlando)", "url": "https://www.portcanaveral.com/port-operations/ship-schedule",
     "parse": parse_canaveral, "fetch": get_canaveral},
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
    {"key": "fll", "name": "Fort Lauderdale (Port Everglades)", "url": "https://pevvesseltraffic.broward.org/",
     "parse": parse_everglades, "fetch": get_everglades},
    {"key": "mia", "name": "Miami", "url": "https://bbpilots.com/", "parse": parse_bbpilots},
    {"key": "sou", "name": "Southampton",
     "url": "https://www.southamptonvts.co.uk/Live_Information/Shipping_Movements_and_Cruise_Ship_Schedule/Cruise_Ship_Schedule/",
     "parse": parse_southampton},
    {"key": "cph", "name": "Copenhagen + Visby", "url": "https://www.cmport.com/terminals/ships-in-port/", "parse": parse_cmp},
    {"key": "sxm", "name": "St. Maarten", "url": "https://gls.portstmaarten.sx/sxm/MainMenu.aspx?ShipScheduleType=2",
     "parse": parse_stmaarten, "fetch": get_stmaarten},
] + [{"key": _id, "name": _name, "url": _site + GPH_API, "parse": gph_parser(_id), "fetch": get_gph}
     for _id, _name, _site in GPH_SITES]


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
                _covered.update(c["p"] for c in got)
            lo, hi = (today - timedelta(days=WINDOW_BACK)).isoformat(), (today + timedelta(days=WINDOW_AHEAD)).isoformat()
            inwin = sum(1 for c in got if (c["d"] or c["a"]) >= lo and (c["a"] or c["d"])[:10] <= hi)
            print(f"ok   {s['name']}: {len(got)} calls, {inwin} in window" + ("  <- nothing current!" if not inwin else ""))
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
                            ("AIDADIVA", None, "AIDAdiva"), ("Msc Preziosa", None, "MSC Preziosa"), ("Aidablu", None, "AIDAblu"),
                            ("Utopia Of The Seas", None, "Utopia of the Seas"), ("Le Boreal", "Ponant", "Ponant Le Boreal"),
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
