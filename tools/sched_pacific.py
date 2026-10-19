"""Official cruise schedules for Alaska, the Pacific coast, Hawaii, Mexico, US East / Canada and Panama.

Parsers follow port_schedules.py: (html_or_text, today) -> [call(...)], plus a SOURCES list.
"""
import html as htmllib
import json
import re
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

import port_schedules as ps
from port_schedules import text, cells, iso, call, get, render, DELAY, WINDOW_AHEAD, MONTHS

DAYS = r"(?:Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday)"
MONTH_NAMES = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"


def get_bytes(url):
    req = urllib.request.Request(url, headers={"User-Agent": ps.UA, "Accept": "*/*"})
    with ps._opener.open(req, timeout=ps.TIMEOUT) as r:
        return r.read()


# ---------------------------------------------------------------- Cruise Line Agencies of Alaska

CLAA_PAGES = ["https://claalaska.com/?page_id=1551", "https://claalaska.com/?page_id=1250",
              "https://claalaska.com/?page_id=665"]


def claa_rows(h):
    """Grid rows -> lists of cell texts, from HTML <tr>/<td|th> or Markdown '| a | b |' lines."""
    if re.search(r"<t[dh]\b", h, re.I):
        return [[text(c) for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", r, re.S | re.I)]
                for r in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S | re.I)]
    return [[text(c) for c in ln.strip().strip("|").split("|")] for ln in h.splitlines() if ln.strip().startswith("|")]


def claa_parser(port, code):
    """claalaska.com 'Cruise Ship Calendar for 2027' PDFs, one per port: a month grid, 7 columns Sunday..Saturday.
    A day cell reads 'Monday, May 31 HNS CRYSTAL SERENITY 07:00 - 18:00 HNS LUMINARA 12:00 - 20:00'; on busy weeks
    the cell overflows into rows below holding only 'JNU RUBY PRINCESS 10:00 - 21:15' (same column = same day).
    Multi-day stays use consecutive cells: first day '08:00 -' (or '08:00 -08:00'), middle '- -' or no time,
    last '-17:00'. Input: the grid as HTML table rows (see claa_fetch) or Markdown table lines."""
    def parse(h, today):
        m = re.search(r"Calendar for (\d{4})", h)
        year = int(m[1]) if m else today.year
        entries, coldate = [], {}  # (day, ship, [times])
        for row in claa_rows(h):
            for k, cell in enumerate(row):
                dm = re.match(rf"\s*{DAYS},\s+({MONTH_NAMES})\s+(\d{{1,2}})\b(.*)", cell, re.S)
                if dm:
                    try:
                        coldate[k] = date(year, MONTHS[dm[1][:3].lower()], int(dm[2]))
                    except ValueError:
                        coldate.pop(k, None)
                    cell = dm[3]
                if k not in coldate:
                    continue
                for seg in re.split(rf"\b{code}\b", cell)[1:]:
                    raw = re.match(r"(.*?)(?=\s*-?\s*\d{1,2}:\d\d|\s+-|$)", seg.strip(), re.S)[1]
                    name = re.sub(r"\bOF THE SEA$", "OF THE SEAS", raw.strip(" -"))  # 'QUANTUM OF THE SEA'
                    if name:
                        tm = re.findall(r"\d{1,2}:\d\d", seg)
                        if len(tm) == 1 and re.match(r"\s*-\s*\d", seg.strip()[len(raw):]):  # '- 17:00': departure only
                            tm = ["", tm[0]]
                        entries.append((coldate[k], name, tm))
        by = {}
        for e in sorted(set((d, n, tuple(t)) for d, n, t in entries), key=lambda e: (e[1], e[0])):
            by.setdefault(e[1], []).append(e)
        out = []

        def is_open(tm):
            return len(tm) < 2 or len(set(tm)) < len(tm) and tm[0] != ""
        for name, evs in by.items():
            i = 0
            while i < len(evs):
                day, _, tm = evs[i]
                j = i
                if is_open(tm):  # the stay continues in the next days' cells
                    while j + 1 < len(evs) and evs[j + 1][0] - evs[j][0] == timedelta(days=1) and j - i < 6:
                        j += 1
                last_day, _, last_tm = evs[j]
                a = iso(day.year, day.month, day.day, tm[0]) if tm and tm[0] else None
                d = iso(last_day.year, last_day.month, last_day.day, last_tm[-1]) if last_tm else None
                if j == i and len(tm) == 1:
                    d = None  # a lone time is the arrival
                if a and d and d <= a:
                    d = None
                if not a and not d:  # no times at all: keep the day
                    a = iso(day.year, day.month, day.day)
                out.append(call(name, None, port, a, d))
                i = j + 1
        return out
    return parse


def pdf_grid(data):
    """Calendar PDF -> HTML table rows of day cells, from word positions (poppler `pdftotext -bbox`). Each
    'Sunday,'..'Saturday,' word starts a cell: words go to the column whose day word is nearest to their left and
    the row whose day words are the last above them."""
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext not installed (apt-get install poppler-utils)")
    x = subprocess.run(["pdftotext", "-bbox", "-enc", "UTF-8", "-", "-"], input=data, capture_output=True,
                       check=True, timeout=120).stdout.decode("utf-8", "replace")
    out = []
    head = re.search(r"Calendar for \d{4}", text(x))
    out.append(f"<h1>{head[0] if head else ''}</h1>")
    for page in re.findall(r"<page\b.*?</page>", x, re.S):
        words = [(float(a), float(b), text(w)) for a, b, w in
                 re.findall(r'<word xMin="([\d.]+)" yMin="([\d.]+)"[^>]*>(.*?)</word>', page, re.S)]
        heads = [(wx, wy) for i, (wx, wy, w) in enumerate(words[:-2]) if re.fullmatch(rf"{DAYS},", w)
                 and re.fullmatch(MONTH_NAMES, words[i + 1][2]) and re.fullmatch(r"\d{1,2}", words[i + 2][2])]
        # (the footer '11:58 Friday, October 02, 2026' is not a day cell: its day number has a comma)
        if not heads:
            continue
        cols = sorted({round(wx) for wx, _ in heads})
        cols = [c for i, c in enumerate(cols) if not i or c - cols[i - 1] > 8]
        rows = sorted({round(wy) for _, wy in heads})
        rows = [r for i, r in enumerate(rows) if not i or r - rows[i - 1] > 4]
        grid = {}
        for wx, wy, w in sorted(words, key=lambda t: (t[1], t[0])):
            ci = max([i for i, c in enumerate(cols) if c <= wx + 3], default=None)
            ri = max([i for i, r in enumerate(rows) if r <= wy + 3], default=None)
            if ci is not None and ri is not None:
                grid.setdefault((ri, ci), []).append(w)
        for ri in range(len(rows)):
            out.append("<tr>" + "".join(f"<td>{' '.join(grid.get((ri, ci), []))}</td>" for ci in range(len(cols)))
                       + "</tr>")
    return "\n".join(out)


def claa_fetch(code, years=None):
    """Find this port's newest '<CODE>-<Name>-<year>.pdf' for this year and next on the CLAA schedule pages,
    download and extract its text."""
    def fetch(url):
        want = years or [date.today().year, date.today().year + 1]
        links = set()
        for i, page in enumerate(CLAA_PAGES):
            if i:
                time.sleep(DELAY)
            try:
                links.update(re.findall(r'href="(https?://claalaska\.com/wp-content/uploads/[^"]+\.pdf)"', get(page)))
            except Exception as e:
                print(f"     CLAA {page}: {type(e).__name__}: {str(e)[:100]}")
        out = []
        for y in want:
            pdfs = sorted(u for u in links if re.search(rf"/{code}-[^/]*-{y}\.pdf$", u, re.I))
            if pdfs:  # same file uploaded in several months: newest upload folder sorts last
                time.sleep(DELAY)
                out.append(pdf_grid(get_bytes(pdfs[-1])))
        if not out:
            raise ValueError(f"no {code} PDF linked on the CLAA schedule pages")
        return out
    return fetch


# (port id, name, CLAA port code)
CLAA_PORTS = [
    ("jnu", "Juneau", "JNU"), ("ktn", "Ketchikan", "KTN"), ("sgy", "Skagway", "SKG"), ("sit", "Sitka", "SIT"),
    ("isp", "Icy Strait Point", "ISP"), ("swd", "Seward", "SEW"), ("whi", "Whittier", "WHT"), ("hns", "Haines", "HNS"),
    ("sea", "Seattle", "SEA"), ("yvr", "Vancouver", "VAN"),  # CLAA's SFO calendar lists only its own 3 ships
]




# ---------------------------------------------------------------- Los Angeles (Ports America)

def parse_portsamerica(h, today):
    """portsamerica.com World Cruise Center schedule (Next.js): the table shows one month, but the page embeds every
    call as JSON records {"Month","Date":"2027-01-02","Day","LineUrl":"<a ..>PRINCESS</a>","ShipUrl",
    "LOA","Berth","VesselCall":"Turn-Around","VesselName":"Discovery Princess"} (quotes may be backslash-escaped).
    Dates only, no times."""
    out = []
    h = h.replace('\\"', '"').replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&")
    for rec in re.findall(r'\{"Month":.*?"VesselName":"[^"]*"\}', h):
        f = dict(re.findall(r'"(\w+)":"((?:[^"\\]|\\.)*)"', rec))
        m = re.match(r"(\d{4})-(\d\d)-(\d\d)$", f.get("Date", ""))
        name = text(f.get("VesselName", ""))
        line = text(f.get("LineUrl", "")) or None
        if m and name and not re.search(r"port of los angeles", line or "", re.I):  # 'Hold date for POLA', navy
            out.append(call(name, line, "lax", iso(m[1], m[2], m[3]), None))
    return list({(c["raw"], c["a"]): c for c in out}.values())


# ---------------------------------------------------------------- PortCall (CruiseMaine, Hawaii DOT Harbors)

def portcall_parser(ports):
    """PortCall.com public cruise schedule JSON (/PortCallServer/portcall/app/home/cruise/<domain>?isThisYear=..),
    the data behind the 'Cruise schedule' tab of maine.portcall.com (CruiseMaine, linked from portlandmaine.gov) and
    hawaii.portcall.com (linked from Hawaii DOT Harbors): [{"PortName", "CruiseVisits": [{"VesselName",
    "Arrival": "2026-10-20T07:00:00-04:00", "Deparature" (sic), "ReservationStatus", ...}]}].
    ports: {PortName or its first word(s): port id}; local times are kept, the UTC offset dropped."""
    def parse(h, today):
        out = []
        m = re.search(r"\[.*\]", h, re.S)
        try:
            data = json.loads(htmllib.unescape(m[0])) if m else []
        except ValueError:
            return []
        for p in data:
            name = (p.get("PortName") or "").strip()  # 'Portland', 'Honolulu - Oahu'
            pid = next((v for k, v in ports.items() if name == k or name.startswith(k + " ")), None)
            if not pid:
                continue
            for v in p.get("CruiseVisits") or []:
                def t(s):
                    mt = re.match(r"(\d{4})-(\d\d)-(\d\d)T(\d\d:\d\d)", s or "")
                    return iso(mt[1], mt[2], mt[3], mt[4]) if mt else None
                a, d = t(v.get("Arrival")), t(v.get("Deparature") or v.get("Departure"))
                if a and d and d <= a:
                    d = None
                if v.get("ReservationStatus") == 2:  # 0 requested, 1 booked, 2 cancelled, 3 conflicted
                    continue
                if v.get("VesselName") and (a or d):
                    out.append(call(v["VesselName"], None, pid, a, d))
        return out
    return parse


def portcall_fetch(url):
    """This year's and next year's schedule (url ends with '?isThisYear=')."""
    pages = [get(url + "true")]
    time.sleep(DELAY)
    try:
        pages.append(get(url + "false"))
    except Exception as e:
        print(f"     PortCall next year: {type(e).__name__}: {str(e)[:100]}")
    return pages


# ---------------------------------------------------------------- Boston (Massport)

def parse_massport(h, today):
    """massport.com Flynn Cruiseport schedule (Drupal view, ?page=0,1,2): rows
    <time datetime="2026-04-14T12:00:00Z">Tue 04/14/26</time> | itinerary | logo | 'Book on Norwegian' | vessel.
    Only sailings that start in Boston (homeport turnarounds), date only."""
    out = {}
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        m = re.search(r'<time datetime="(\d{4})-(\d\d)-(\d\d)', row)
        c = cells(row)
        if not m or len(c) < 5:
            continue
        name = text(c[4])
        line = re.sub(r"^Book on\s+", "", text(c[3])) or None
        if name:
            out[(name, m[0])] = call(name, line, "bos", iso(m[1], m[2], m[3]), None)
    return list(out.values())


def get_massport(url):
    pages = []
    for n in range(8):
        h = get(f"{url}?page={n}")
        if n and not parse_massport(h, date.today()):
            break
        pages.append(h)
        if f"page={n + 1}" not in h:
            break
        time.sleep(DELAY)
    return pages


# ---------------------------------------------------------------- PDF schedule lists (Saint John, Sydney NS)

def pdf_text(data):
    """PDF bytes -> text with the page layout kept (poppler `pdftotext -layout`): one table row per line,
    columns separated by runs of spaces."""
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext not installed (apt-get install poppler-utils)")
    return subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=data, capture_output=True,
                          check=True, timeout=120).stdout.decode("utf-8", "replace")


def table_rows(h):
    """Rows of cells from an HTML/Markdown table, or from `pdftotext -layout` text (cells = runs of 2+ spaces)."""
    rows = claa_rows(h)
    if rows:
        return rows
    return [[c.strip() for c in re.split(r"\s{2,}", ln.strip())] for ln in h.splitlines() if ln.strip()]


# Lines whose ships these PDFs list without the brand ('Breakaway' / Norwegian -> 'Norwegian Breakaway').
BRANDS = ["Norwegian", "Carnival", "Viking", "Crystal", "Azamara", "Seabourn", "Silversea", "Celebrity", "Oceania"]


def branded(name, line):
    for b in BRANDS:
        if line and line.lower().startswith(b.lower()) and not name.lower().startswith(b.lower()) \
                and not (b == "Viking" and name.lower().startswith("viking")):
            return f"{b} {name}"
    return name


def pdf_link_fetch(page, pattern):
    """Read the schedule page, follow the first PDF link whose URL or link text matches pattern, return its text."""
    def fetch(url):
        h = get(page)
        links = [urllib.parse.urljoin(page, htmllib.unescape(u))
                 for u, inner in re.findall(r'<a\b[^>]*href="([^"]+\.pdf[^"]*)"[^>]*>(.*?)</a>', h, re.I | re.S)
                 if re.search(pattern, u + " " + text(inner), re.I)]
        if not links:
            raise ValueError(f"no schedule PDF linked on {page}")
        time.sleep(DELAY)
        return [pdf_text(get_bytes(links[0]))]
    return fetch


def parse_saintjohn(h, today):
    """sjport.com PDF: # | DATE '08-Apr-26' | DAY | ARRIVAL '06:30' | DEPARTURE '04:00 (Departure on Apr 9th)' |
    SHIP 'Breakaway' | CRUISE LINE 'Norwegian' | BERTH | PAX."""
    out = []
    for c in table_rows(h):
        i = next((k for k, x in enumerate(c) if re.fullmatch(r"\d{1,2}-[A-Za-z]{3}-\d{2}", x)), None)
        if i is None or len(c) < i + 6:
            continue
        dd, mon, yy = c[i].split("-")
        if mon[:3].lower() not in MONTHS:
            continue
        y, mo = 2000 + int(yy), MONTHS[mon[:3].lower()]
        a = iso(y, mo, dd, c[i + 2])
        dday = date(y, mo, int(dd))
        m = re.search(r"Departure on ([A-Za-z]{3})\w* (\d{1,2})", c[i + 3])
        if m and m[1].lower() in MONTHS:
            dday = date(y + (MONTHS[m[1].lower()] < mo), MONTHS[m[1].lower()], int(m[2]))
        d = iso(dday.year, dday.month, dday.day, c[i + 3])
        if a and d and d <= a:
            d = None
        name, line = c[i + 4], c[i + 5] or None
        if name and (a or d):
            out.append(call(branded(name, line), line, "sjb", a, d))
    return out


def parse_sydney_ns(h, today):
    """sydneyport.ca (Port of Sydney, Nova Scotia) PDF: Date 'April 9, 2026' | Cruise Ship ('*' = inaugural) |
    Times '0800-1330' | Cruise Line | Pax | Crew | Berth | Agent | Length."""
    out = []
    for c in table_rows(h):
        i = next((k for k, x in enumerate(c) if re.fullmatch(rf"{MONTH_NAMES} \d{{1,2}}, \d{{4}}", x)), None)
        if i is None or len(c) < i + 4:
            continue
        mo, dd, y = re.match(r"(\w+) (\d+), (\d{4})", c[i]).groups()
        m = re.fullmatch(r"(\d\d)(\d\d)\s*-\s*(\d\d)(\d\d)", c[i + 2])
        a = iso(y, MONTHS[mo[:3].lower()], dd, f"{m[1]}:{m[2]}" if m else None)
        d = iso(y, MONTHS[mo[:3].lower()], dd, f"{m[3]}:{m[4]}") if m else None
        if a and d and d <= a:
            d = None
        name, line = c[i + 1].strip(" *"), c[i + 3] or None
        name = re.sub(r"^Main Schiff", "Mein Schiff", name)
        if name and a:
            out.append(call(branded(name, line), line, "syd", a, d))
    return out


def parse_newport(h, today):
    """discovernewport.org PDF (credit: Office of the Newport Harbormaster), Perrotti Park tender landing: two
    columns of 'Sunday, October 4th' | 'Majestic Princess' pairs under month headings; dates only.
    (Cancelled calls are shown only by styling in the PDF, so they cannot be told apart.)"""
    m = re.search(r"(\d{4}) cruise ship schedule", h, re.I)
    year = int(m[1]) if m else today.year
    out = []
    for c in table_rows(h):
        for k in range(len(c) - 1):
            dm = re.fullmatch(rf"{DAYS},\s+({MONTH_NAMES})\s+(\d{{1,2}})(?:st|nd|rd|th)?", c[k])
            if dm and c[k + 1] and not re.match(DAYS, c[k + 1]):
                out.append(call(c[k + 1], None, "nwp", iso(year, MONTHS[dm[1][:3].lower()], dm[2]), None))
    return out


# ---------------------------------------------------------------- San Francisco, San Diego (PDF lists)

def parse_sanfrancisco(h, today):
    """sfport.com '2026 Cruise Terminal Schedule' PDF: No. | Vessel | ETA Day | ETA Date 'Jan-02-2026' |
    Arrival '7:00 AM' | Last Port | ETD Day | ETD Date | Departure | Next Port | Berth | Cruise Line | Agent.
    Terminal events ('Pier 27 Event', 'FLEETWEEK', ...) share the table and are skipped."""
    out = []
    for c in table_rows(h):
        idx = [k for k, x in enumerate(c) if re.fullmatch(r"[A-Za-z]{3}-\d{2}-\d{4}", x)]
        if not idx or idx[0] < 1 or re.search(r"event|fleet ?week|shore power|recommission", c[idx[0] - 2] if idx[0] >= 2 else c[0], re.I):
            continue
        name = c[idx[0] - 2] if idx[0] >= 2 else ""
        if re.search(r"event|fleet|power", name, re.I) or not name:
            continue

        def dt(k):
            mo, dd, y = c[k].split("-")
            return iso(y, MONTHS.get(mo[:3].lower(), 0), dd, c[k + 1]) if k + 1 < len(c) and mo[:3].lower() in MONTHS else None
        a = dt(idx[0])
        d = dt(idx[1]) if len(idx) > 1 else None
        if a and d and d <= a:
            d = None
        line = c[-2] if len(c) >= 13 else None
        if a:
            out.append(call(branded(name, line or ""), line, "sfo", a, d))
    return out


def parse_sandiego(h, today):
    """portofsandiego.org 2026-27 cruise schedule PDF: DATE '10/18/26' | SHIP | LINE | ITINERARY.
    Departures from San Diego only (homeport sailings), dates only."""
    out = {}
    for c in table_rows(h):
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2})", c[0]) if c else None
        if m and len(c) >= 3 and c[1]:
            out[(c[1], m[0])] = call(c[1], c[2] or None, "san", iso(2000 + int(m[3]), m[1], m[2]), None)
    return list(out.values())


# ---------------------------------------------------------------- sources

PORTCALL_MAINE = "https://maine.portcall.com/PortCallServer/portcall/app/home/cruise/2?isThisYear="
PORTCALL_HAWAII = "https://hawaii.portcall.com/PortCallServer/portcall/app/home/cruise/1?isThisYear="

# key: sample-file prefix for --test (multi-port sources use their main port)
SOURCES = [{"key": _id, "name": f"{_name} (CLAA)", "url": "https://claalaska.com/?page_id=1250",
            "parse": claa_parser(_id, _code), "fetch": claa_fetch(_code)} for _id, _name, _code in CLAA_PORTS] + [
    {"key": "pwm", "name": "Portland & Bar Harbor (CruiseMaine)", "url": PORTCALL_MAINE,
     "parse": portcall_parser({"Portland": "pwm", "Bar Harbor": "bhb"}), "fetch": portcall_fetch},
    {"key": "hnl", "name": "Hawaii (DOT Harbors PortCall)", "url": PORTCALL_HAWAII,
     "parse": portcall_parser({"Honolulu": "hnl", "Hilo": "ito", "Kailua-Kona": "koa", "Kahului": "ogg",
                               "Nawiliwili": "lih"}), "fetch": portcall_fetch},
    {"key": "bos", "name": "Boston (Massport)", "url": "https://www.massport.com/flynn-cruiseport/cruise-directory/cruise-schedule",
     "parse": parse_massport, "fetch": get_massport},
    {"key": "sjb", "name": "Saint John", "url": "https://www.sjport.com/cruise-schedule", "parse": parse_saintjohn,
     "fetch": pdf_link_fetch("https://www.sjport.com/cruise-schedule", r"cruise.?schedule")},
    {"key": "syd", "name": "Sydney NS", "url": "https://www.sydneyport.ca/cruiseschedule", "parse": parse_sydney_ns,
     "fetch": pdf_link_fetch("https://www.sydneyport.ca/cruiseschedule", r"_files/ugd/.*DOWNLOAD")},  # not 'LOUISBOURG CRUISE SCHEDULE'
    {"key": "nwp", "name": "Newport RI", "url": "https://www.discovernewport.org/industry/cruise-ship-schedule/",
     "parse": parse_newport,
     "fetch": pdf_link_fetch("https://www.discovernewport.org/industry/cruise-ship-schedule/", r"cruise_ship_schedule.*perrotti")},
    {"key": "lax", "name": "Los Angeles (Ports America)",
     "url": "https://www.portsamerica.com/our-services/cruise-los-angeles-terminal-schedule", "parse": parse_portsamerica},
    {"key": "sfo", "name": "San Francisco", "url": "https://www.sfport.com/maritime/cruise", "parse": parse_sanfrancisco,
     "fetch": pdf_link_fetch("https://www.sfport.com/maritime/cruise", r"cruise_schedule")},
    {"key": "san", "name": "San Diego", "url": "https://www.portofsandiego.org/maritime/cruise-operations",
     "parse": parse_sandiego,
     "fetch": pdf_link_fetch("https://www.portofsandiego.org/maritime/cruise-operations", r"Cruise-Schedule")},
]
