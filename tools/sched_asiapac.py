"""Official cruise schedules for Australia, New Zealand, the South Pacific islands and Asia.

Parsers follow port_schedules.py: (html_or_text, today) -> [call(...)], plus a SOURCES list.
"""
import html as htmllib
import json
import re
import time
import urllib.parse
from datetime import date, datetime, timedelta

import port_schedules as ps
from port_schedules import text, cells, iso, call, get, render, DELAY, WINDOW_AHEAD, MONTHS


def _json(h):
    """JSON body of a response (also when a scraper wrapped it in <pre> or HTML-escaped it)."""
    h = htmllib.unescape(re.sub(r"<[^>]+>", "", h)) if h.lstrip()[:1] == "<" else h
    i = min([k for k in (h.find("{"), h.find("[")) if k >= 0], default=-1)
    j = max(h.rfind("}"), h.rfind("]"))
    return json.loads(h[i:j + 1]) if 0 <= i < j else None


def _later(a, d):
    """A departure time earlier than the arrival on the same date means it leaves after midnight."""
    if a and d and d < a and d[:10] == a[:10]:
        return (datetime.fromisoformat(d) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    return d


# ---------------------------------------------------------------- Australia

def parse_brisbane(h, today):
    """portbris.com.au: the schedule page's DataTable loads /documents/d/port-of-brisbane/shippingscheduledata,
    JSON {"data": [{"Name", "Arrival Date": "22/10/2026 12:00:00 AM" (or '13/04/29 ...'), "Arrival Time": "0630",
    "Departure Date", "Departure Time", "Agent", "Wharf", "Type Of Call"}]} - every season from 2021 on."""
    out = []

    def dt(day, hm):
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", day or "")
        t = re.match(r"(\d{1,2}):?(\d\d)$", (hm or "").strip())
        if not m:
            return None
        y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        return iso(y, m[2], m[1], f"{t[1]}:{t[2]}" if t else "00:00")
    for r in (_json(h) or {}).get("data", []):
        name = (r.get("Name") or "").strip()
        a, d = dt(r.get("Arrival Date"), r.get("Arrival Time")), dt(r.get("Departure Date"), r.get("Departure Time"))
        if name and (a or d) and not re.search(r"cancel", json.dumps(r), re.I):
            out.append(call(name, None, "bne", a, _later(a, d)))
    return out


def _dmy_words(s, hm=None):
    """'Sun 11 Oct 2026' / '11 October 2026' / 'Sat 29 Aug 26' (+ '08:00') -> ISO"""
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4}|\d\d)\b", s or "")
    if not m or m[2].lower() not in MONTHS:
        return None
    return iso(int(m[3]) + (2000 if len(m[3]) == 2 else 0), MONTHS[m[2].lower()], m[1], hm or "00:00")


VIC_REGIONAL = {"G": "Geelong", "P": "Portland", "PI": "Phillip Island"}


def parse_ports_victoria(h, today):
    """ports.vic.gov.au 'Cruise ship schedules 2026-27' (one page per season): two SharePoint tables,
    <div id="station-pier"> Ship | ETA date 'Sun 11 Oct 2026' | time | ETD date | time | Berth | Agent, and
    <div id="regional-ports"> with Location G/P/PI = Geelong, Portland, Phillip Island.
    Ship names carry '(T)'/'(pT)' turnaround marks."""
    out = []
    for sec, body in re.findall(r'<div id="(station-pier|regional-ports)"[^>]*>(.*?)</table>', h, re.S):
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.S):
            c = [text(x).replace("​", "").strip() for x in cells(row)]
            if len(c) < 6:
                continue
            name = re.sub(r"\s*\((p?T)\)\s*$", "", c[0], flags=re.I).strip()
            a, d = _dmy_words(c[1], c[2]), _dmy_words(c[3], c[4])
            if not name or not (a or d) or re.search(r"cancel", " ".join(c), re.I):
                continue
            if sec == "station-pier":
                out.append(call(name, None, "mel", a, _later(a, d)))
            else:
                port = VIC_REGIONAL.get(c[5].upper())
                if port:
                    out.append(call(name, None, None, a, _later(a, d), name=port))
    return out


def get_ports_victoria(url):
    """The cruise-shipping page links one schedule page per season ('cruise-ship-schedules-2026-27'); fetch every
    season that has not ended yet."""
    seasons = sorted(set(re.findall(r"cruise-ship-schedules-(20\d\d)-(\d\d)\b", get(url))))
    yr = date.today().year
    pages = []
    for y1, y2 in seasons:
        if 2000 + int(y2) >= yr:
            time.sleep(DELAY)
            pages.append(get(f"https://ports.vic.gov.au/cruise-shipping/cruise-ship-schedules-{y1}-{y2}/"))
    return pages


def parse_fremantle(h, today):
    """Fremantle Ports VTMIS (Saab PortControl WebX public page, report 'Cruise Ships', rendered DOM):
    <tr id=.. role="row"> Arrival 'Fri 23 Oct 2026 06:30' | Departure | Ship | Agency | Operation | Berth | Visit no."""
    out = []
    for row in re.findall(r'<tr id="\d+"[^>]*role="row"[^>]*>(.*?)</tr>', h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 3:
            continue
        a = _dmy_words(c[0], (re.search(r"\d{1,2}:\d\d", c[0]) or [None])[0])
        d = _dmy_words(c[1], (re.search(r"\d{1,2}:\d\d", c[1]) or [None])[0])
        if c[2] and (a or d):
            out.append(call(c[2], None, "fre", a, d))
    return out


def get_fremantle(url):
    return [render(url, 'tr[role="row"][id]')]


# ---------------------------------------------------------------- New Zealand

def parse_auckland(h, today):
    """poal.co.nz cruise schedule (Drupal view table): Vessel | Wharf | Arrival <time datetime="2026-10-25T05:00:00+13:00">
    | Departs <time ..> | Previous port | Next port. Local times are taken from the datetime attribute."""
    out = []
    body = h[h.find("<tbody"):h.find("</tbody>")] if "<tbody" in h else ""
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.S):
        c = cells(row)
        if len(c) < 4:
            continue

        def dt(s):
            m = re.search(r'datetime="(\d{4})-(\d\d)-(\d\d)T(\d\d:\d\d)', s)
            return iso(m[1], m[2], m[3], m[4]) if m else None
        name, a, d = text(c[0]), dt(c[2]), dt(c[3])
        if name and (a or d):
            out.append(call(name, None, "akl", a, d))
    return out


# ---------------------------------------------------------------- Tasmania

TAS_PORTS = {"Hobart": "hba", "Burnie": "bwt", "Port Arthur": "pta"}
TASPORTS_JSON = ("https://www.tasports.com.au/actions/site-module/shipping/get-json-data"
                 "?type=External%20Schedule%20-%20Cruise%20Ships&filterPort=")


def parse_tasports(h, today):
    """TasPorts 'Cruise Ships' list (all Tasmanian ports): the JSON the shipping-schedule page loads,
    [{"PORT": "Hobart", "BERTH", "VESSEL", "VESSEL_TYPE", "AGENT", "ARRIVAL_DATE": "02/11/2026 07:00:00",
    "DEPARTURE_DATE", "PORT_FROM", "PORT_TO", ...}], or the same columns as the page's last HTML table
    (Port | Berth | Vessel | Agent | Arrival | Departure | From | To | Flag | LOA). Coles Bay etc. are kept by name."""
    rows = []
    if h.lstrip()[:1] == "[":
        rows = [(r.get("PORT"), r.get("VESSEL"), r.get("ARRIVAL_DATE"), r.get("DEPARTURE_DATE")) for r in _json(h) or []]
    else:
        i = h.rfind('<table class="table-sm')
        seg = h[i:h.find("</table>", i)] if i >= 0 else ""
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", seg, re.S):
            c = [text(x) for x in cells(row)]
            if len(c) >= 6:
                rows.append((c[0], c[2], c[4], c[5]))
    out = []

    def dt(s):
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}:\d\d)", (s or "").strip())
        return iso(m[3], m[2], m[1], m[4]) if m else None
    for port, name, a, d in rows:
        a, d = dt(a), dt(d)
        if not (name and port and (a or d)):
            continue
        p = TAS_PORTS.get(port.strip())
        out.append(call(name, None, p, a, d, name=None if p else port.strip()))
    return out


# ---------------------------------------------------------------- PDFs

def pdf_text(data):
    """PDF bytes -> `pdftotext -layout` text (see sched_pacific.pdf_text)."""
    import sched_pacific
    return sched_pacific.pdf_text(data)


def get_pdf(url):
    import sched_pacific
    return [pdf_text(sched_pacific.get_bytes(url))]


def pdf_link_fetch(page, pattern, every=False):
    import sched_pacific
    return sched_pacific.pdf_link_fetch(page, pattern, every)


# Names some PDFs clip to the column width ('SEVEN SEAS NAVIC'); a clipped name is completed from this list.
LONG_SHIPS = ["Seven Seas Navigator", "Seven Seas Mariner", "Seven Seas Explorer", "Seven Seas Splendor",
              "Seven Seas Voyager", "Seven Seas Grandeur", "Seven Seas Prestige", "Carnival Luminosa",
              "Carnival Encounter", "Carnival Adventure", "Carnival Splendor", "Crystal Serenity", "Crystal Symphony",
              "Azamara Onward", "Azamara Pursuit", "Azamara Journey", "Azamara Quest", "Mitsui Ocean Fuji",
              "Le Jacques Cartier", "Emerald Princess", "Sapphire Princess", "Diamond Princess", "Majestic Princess",
              "Coral Princess", "Island Princess", "Crown Princess", "Grand Princess", "Royal Princess",
              "Queen Elizabeth", "Queen Victoria", "Quantum of the Seas", "Ovation of the Seas",
              "Anthem of the Seas", "Radiance of the Seas", "Brilliance of the Seas", "Serenade of the Seas",
              "Voyager of the Seas", "Celebrity Solstice", "Celebrity Edge", "Celebrity Eclipse", "Celebrity Millennium",
              "Norwegian Spirit", "Norwegian Jewel", "Norwegian Sun", "Seabourn Encore", "Seabourn Quest",
              "Seabourn Sojourn", "Silver Whisper", "Silver Shadow", "Coral Discoverer", "Coral Adventurer",
              "Coral Geographer", "Costa Deliziosa", "Costa Serena", "Pacific Explorer",
              "Pacific Encounter", "Pacific World", "Westerdam", "Zuiderdam", "Oosterdam", "Noordam", "Nieuw Amsterdam"]


def unclip(name):
    n = re.sub(r"[\s:;!]+$", "", name.strip())
    if len(n) >= 12 and not any(n.lower() == s.lower() for s in LONG_SHIPS):
        for cut in (0, 1, 2):  # the clipped last letter is often misread ('NAVIC', 'LUMINOI', 'MARII')
            stem = n[:len(n) - cut].lower()
            if stem.endswith(" "):
                continue
            hits = [s for s in LONG_SHIPS if s.lower().startswith(stem) and len(s) > len(n) - cut]
            if len(hits) == 1:
                return hits[0]
    return n


DAY3 = r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)"


def parse_portsnorth(h, today):
    """Ports North 'Cruise liner schedule' PDF (Cairns seaport, 2026..2030): rows
    No | Vessel | Day | Arr date '02 Jan 26' | time | Dep date | time | Agent | Port from | Port to | LOA | pax | crew.
    Works on `pdftotext -layout` text or a Markdown table ('|' separated). Clipped vessel names are completed."""
    out = []
    pat = re.compile(rf"^\s*\d+\s+(.+?)\W+{DAY3}\s+(\d\d) ([A-Za-z]{{3}}) (\d\d)\s+(\d\d:\d\d)\s+"
                     rf"(\d\d) ([A-Za-z]{{3}}) (\d\d)\s+(\d\d:\d\d)")
    for ln in h.splitlines():
        m = pat.match(ln.replace("|", " "))
        if not m or m[3].lower() not in MONTHS or m[7].lower() not in MONTHS:
            continue
        a = iso(2000 + int(m[4]), MONTHS[m[3].lower()], m[2], m[5])
        d = iso(2000 + int(m[8]), MONTHS[m[7].lower()], m[6], m[9])
        if a and d and d < a:  # typos such as departure '30 Oct' for a 31 Oct arrival
            d = _later(a, d[:11] + d[11:]) if d[:10] == a[:10] else None
        name = unclip(m[1])
        if name and (a or d):
            out.append(call(name, None, "cns", a, d))
    return out


PN_REGIONAL = {"COOKTOWN": None, "PORT DOUGLAS": "pds", "THURSDAY ISLAND": None, "YORKEYS KNOB": None}


def parse_portsnorth_regional(h, today):
    """Ports North regional ports PDF: one section per port ('COOKTOWN', 'PORT DOUGLAS', 'THURSDAY ISLAND',
    'YORKEYS KNOB') with rows Vessel | Day | Arr '25 Nov 26' | '7:00' | Dep date | time | Agent | LOA.
    pdftotext text or Markdown. A departure more than 5 days after arrival is a typo and is dropped."""
    out, port = [], None
    pat = re.compile(r"^\s*(.+?)\W+(?:Mon|Tue|Wed|Thu|Fri?|Sat|Sun)\s+(\d\d) ([A-Za-z]{3}) (\d\d)\s+(\d{1,2}:\d\d)\s+"
                     r"(\d\d) ([A-Za-z]{3}) (\d\d)\s+(\d{1,2}:\d\d)")
    for ln in h.splitlines():
        flat = re.sub(r"\s+", " ", ln.replace("|", " ")).strip()
        if flat.upper() in PN_REGIONAL:
            port = flat.upper()
            continue
        m = pat.match(flat)
        if not port or not m or m[3].lower() not in MONTHS or m[7].lower() not in MONTHS:
            continue
        a = iso(2000 + int(m[4]), MONTHS[m[3].lower()], m[2], m[5])
        d = iso(2000 + int(m[8]), MONTHS[m[7].lower()], m[6], m[9])
        if a and d and not (a <= d <= (datetime.fromisoformat(a) + timedelta(days=5)).isoformat()):
            d = None
        name = unclip(re.sub(r"^MS\s+", "", m[1]))
        pid = PN_REGIONAL[port]
        if name and a:
            out.append(call(name, None, pid, a, d, name=None if pid else port.title()))
    return out


# ---------------------------------------------------------------- Port Authority of NSW (Newcastle, Eden)

def pansw_parser(port):
    """portauthoritynsw.com.au cruise schedules use the same table as Sydney (port_schedules.parse_sydney_au):
    Vessel | Arrival 'Mon 9 Nov 2026 07:00' | Departure 'Mon 9 Nov 16:00' | Berth | Agent | Line."""
    def parse(h, today):
        return [dict(c, p=port) for c in ps.parse_sydney_au(h, today)]
    parse.__name__ = f"parse_pansw_{port}"
    return parse


def get_pansw(url):
    """The list is paged (Drupal pager '?block_config_key=..&page=1' .. last page); walk every page."""
    h = get(url)
    pages = [h]
    links = [htmllib.unescape(u) for u in re.findall(r'href="([^"]*[?&]page=\d+[^"]*)"', h)]
    if links:
        last = max(int(re.search(r"page=(\d+)", u)[1]) for u in links)
        for n in range(1, min(last, 20) + 1):
            time.sleep(DELAY)
            pages.append(get(urllib.parse.urljoin(url, re.sub(r"page=\d+", f"page={n}", links[0]))))
    return pages


def parse_tauranga(h, today):
    """port-tauranga.co.nz cruise schedule (TablePress table): Vessel | Agent | LOA | Tonnage |
    Arrival date 'Tue 13 October 2026' | ETA '05:07' | ETD '17:11' | Max pax. ETD before ETA = next day."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 7:
            continue
        a = _dmy_words(c[4], c[5]) if re.match(r"\d{1,2}:\d\d$", c[5]) else None
        d = _dmy_words(c[4], c[6]) if re.match(r"\d{1,2}:\d\d$", c[6]) else None
        if a and d and d < a:
            d = (datetime.fromisoformat(d) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        if c[0] and (a or d):
            out.append(call(c[0], None, "tau", a, d))
    return out


def table_parser(port, cols, fmt="dmy"):
    """Generic one-table schedule: cols = (vessel, arrival date, arrival time, departure date, departure time)
    column indexes (a time index may be None when the date cell holds the time). fmt 'dmy' = '25/10/2026'."""
    v, ad, at, dd, dt_ = cols

    def dt(day, hm):
        m = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})(?:\s+(\d{1,2}[:.]\d\d))?", day or "")
        if not m:
            return _dmy_words(day, (re.search(r"\d{1,2}:\d\d", hm or day or "") or [None])[0])
        y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        t = re.search(r"\d{1,2}[:.]\d\d", hm or "") or (m[4] and [m[4]])
        return iso(y, m[2], m[1], t[0].replace(".", ":") if t else "00:00")

    def parse(h, today):
        out = []
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
            c = [text(x) for x in cells(row)]
            if len(c) <= max(i for i in cols if i is not None) or re.search(r"cancel", " ".join(c), re.I):
                continue
            a = dt(c[ad], c[at] if at is not None else None)
            d = dt(c[dd], c[dt_] if dt_ is not None else None)
            name = re.sub(r"\s*\*+$", "", c[v]).strip()
            if name and (a or d) and not re.match(r"vessel|ship", name, re.I):
                out.append(call(name, None, port, a, _later(a, d)))
        return out
    parse.__name__ = f"parse_table_{port}"
    return parse


# centreport.co.nz 'Cruise schedule' page: Vessel | PAX | Arrival '25/10/2026' | time | Dept. date | time
parse_wellington = table_parser("wlg", (0, 2, 3, 4, 5))


# New Zealand Cruise Association (the industry's official cruise association): its /schedules/ page loads one
# published Google Sheet per season (yearUrls in an inline base64 script). Rows: Ship | Port | Arrival
# 'Sat 29 Aug 26' | time | Departure | time | Guests | Crew. Auckland, Tauranga and Wellington come from their
# own port companies above, so they are left out here.
NZCA_PORTS = {"Napier": "npe", "Picton": "pic", "Lyttelton": "lyt", "Christchurch": "lyt", "Akaroa": "akr",
              "Port Chalmers": "dud", "Dunedin": "dud", "Bay of Islands": "boi"}
NZCA_OWN = {"auckland", "tauranga", "wellington"}
NZCA_SCENIC = re.compile(r"fiordland|subantarctic|white island|marlborough", re.I)   # scenic cruising, no call
NZCA_PAGE = "https://www.newzealandcruiseassociation.com/schedules/"


def parse_nzca(h, today):
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 6 or re.search(r"cancel", c[1], re.I) or not re.search(r"\d", c[2]):
            continue
        port = c[1].strip()
        if port.lower() in NZCA_OWN or NZCA_SCENIC.search(port):
            continue
        a = _dmy_words(c[2], c[3] if re.match(r"\d{1,2}:\d\d$", c[3]) else None)
        d = _dmy_words(c[4], c[5] if re.match(r"\d{1,2}:\d\d$", c[5]) else None)
        if c[0] and (a or d):
            pid = NZCA_PORTS.get(port)
            out.append(call(c[0], None, pid, a, _later(a, d), name=None if pid else port))
    return out


def get_nzca(url):
    """Read the season -> sheet map from the schedules page and fetch every season that has not ended."""
    import base64
    page = get(url)
    js = " ".join(base64.b64decode(b).decode("utf-8", "replace")
                  for b in re.findall(r"data:text/javascript;base64,([A-Za-z0-9+/=]+)", page)) + page
    yr, pages = date.today().year, []
    for y1, y2, u in re.findall(r"'(20\d\d)-(\d\d)'\s*:\s*'(https://docs\.google\.com/spreadsheets/[^']+)'", js):
        if 2000 + int(y2) >= yr:
            time.sleep(DELAY)
            pages.append(get(htmllib.unescape(u)))
    return pages


# Southern Ports (WA) season PDF: 'Port of Albany' / 'Port of Esperance' sections, a year line ('2026'), then
# rows 'Crown Princess  Fri 16 Oct  3,582  5.30am-4pm' or 'Coral Geographer  Wed 28 to Thur 29 Oct  120  10am-6pm'.
SOUTHERN_PORTS = {"Albany": "alh"}
SP_ROW = re.compile(r"^(?P<ship>[A-Za-z][\w .'-]*?)\s+[A-Z][a-z]{2,4}\s+(?P<d1>\d{1,2})(?:\s+(?P<m1>[A-Z][a-z]{2}))?"
                    r"(?:\s+to\s+[A-Z][a-z]{2,4}\s+(?P<d2>\d{1,2}))?\s+(?P<mon>[A-Z][a-z]{2})\s+[\d,]+\s+"
                    r"(?P<t1>\d{1,2}(?:[.:]\d\d)?\s*[ap]m)\s*[-\u2013\u2014]\s*(?P<t2>\d{1,2}(?:[.:]\d\d)?\s*[ap]m)")


def _ampm(s):
    m = re.match(r"(\d{1,2})(?:[.:](\d\d))?\s*([ap])m", s)
    h = int(m[1]) % 12 + (12 if m[3] == "p" else 0)
    return f"{h:02d}:{m[2] or '00'}"


def parse_southern_ports(h, today):
    out, port, year = [], None, None
    for line in re.sub(r"<[^>]+>", "\n", h).splitlines():
        line = re.sub(r"\s+", " ", line.replace("|", " ")).strip()
        if m := re.match(r"Port of ([A-Z][a-z]+)", line):
            port, year = m[1], None
        elif re.fullmatch(r"20\d\d", line):
            year = int(line)
        elif port and year and (m := SP_ROW.match(line)) and m["mon"].lower() in MONTHS:
            mon = MONTHS[m["mon"].lower()]
            a = iso(year, MONTHS.get((m["m1"] or "").lower(), mon), m["d1"], _ampm(m["t1"]))
            d = iso(year, mon, m["d2"] or m["d1"], _ampm(m["t2"]))
            pid = SOUTHERN_PORTS.get(port)
            out.append(call(m["ship"].strip(), None, pid, a, _later(a, d), name=None if pid else port))
    return out


PORTSNORTH = "https://www.portsnorth.com.au/marine-tourism/cruise-ship-schedules/"
SOURCES = [
    {"key": "bne", "name": "Brisbane (Port of Brisbane)",
     "url": "https://www.portbris.com.au/documents/d/port-of-brisbane/shippingscheduledata", "parse": parse_brisbane},
    {"key": "mel", "name": "Melbourne & Victorian regional ports (Ports Victoria)",
     "url": "https://ports.vic.gov.au/cruise-shipping/", "parse": parse_ports_victoria, "fetch": get_ports_victoria},
    {"key": "fre", "name": "Fremantle (Fremantle Ports)",
     "url": "https://www3.fremantleports.com.au/VTMIS/dashb.ashx?db=fmp.public&btn=CruiseShips",
     "parse": parse_fremantle, "fetch": get_fremantle},
    {"key": "akl", "name": "Auckland (Ports of Auckland)", "url": "https://www.poal.co.nz/operations/schedules/cruise",
     "parse": parse_auckland},
    {"key": "hba", "name": "Hobart, Burnie & Port Arthur (TasPorts)", "url": TASPORTS_JSON, "parse": parse_tasports},
    {"key": "cns", "name": "Cairns (Ports North)", "url": PORTSNORTH, "parse": parse_portsnorth,
     "fetch": pdf_link_fetch(PORTSNORTH, r"CruiseSchedule\.pdf")},
    {"key": "pds", "name": "Port Douglas & FNQ regional (Ports North)", "url": PORTSNORTH,
     "parse": parse_portsnorth_regional, "fetch": pdf_link_fetch(PORTSNORTH, r"regional")},
    {"key": "ntl", "name": "Newcastle (Port Authority of NSW)",
     "url": "https://www.portauthoritynsw.com.au/newcastle-harbour-cruise-schedule", "parse": pansw_parser("ntl"),
     "fetch": get_pansw},
    {"key": "edn", "name": "Eden (Port Authority of NSW)",
     "url": "https://www.portauthoritynsw.com.au/cruise/port-eden/eden-cruise-schedule", "parse": pansw_parser("edn"),
     "fetch": get_pansw},
    {"key": "tau", "name": "Tauranga (Port of Tauranga)",
     "url": "https://www.port-tauranga.co.nz/operations/cruise-ship-schedules/", "parse": parse_tauranga},
    {"key": "wlg", "name": "Wellington (CentrePort)",
     "url": "https://www.centreport.co.nz/what-we-do/cruise-ships/cruise-schedule", "parse": parse_wellington},
    {"key": "lyt", "name": "NZ regional ports (New Zealand Cruise Association)", "url": NZCA_PAGE,
     "parse": parse_nzca, "fetch": get_nzca},
    {"key": "alh", "name": "Albany & Esperance (Southern Ports)",
     "url": "https://www.southernports.com.au/in-port/shipping-schedule/cruise/albany-cruise-arrivals",
     "parse": parse_southern_ports,
     "fetch": pdf_link_fetch("https://www.southernports.com.au/in-port/shipping-schedule/cruise/albany-cruise-arrivals",
                             r"cruise-schedule")},
]
