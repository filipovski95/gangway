"""Official cruise schedules for US home ports (Gulf, East Coast) and more Caribbean ports of call
(see port_schedules.py for conventions).

Parsers follow port_schedules.py: (html_or_text, today) -> [call(...)], plus a SOURCES list.
"""
import html as htmllib
import re
from urllib.parse import urljoin
import time
from datetime import date, datetime, timedelta

import port_schedules as ps
from port_schedules import text, cells, iso, call, get, render, DELAY, WINDOW_AHEAD, MONTHS


def _fix_overnight(a, d):
    """Same-day times where departure < arrival mean the ship leaves after midnight."""
    if a and d and d < a:
        d = (datetime.fromisoformat(d) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    return a, d


# ---------------------------------------------------------------- Galveston

GLS_LINES = {"carnival": "Carnival", "msc": "MSC", "norwegian": "Norwegian", "disney": "Disney",
             "princess": "", "royal caribbean": "", "seven seas": "", "mas": ""}


def parse_galveston(h, today):
    """portofgalveston.com cruise calendar feed (WordPress admin-ajax.php?action=meeting_calender&start=&end=, the
    JSON array the page's FullCalendar loads; about 14 months ahead): [{"id", "title": "<span style=..>Breeze</span>",
    "start": "2026-10-19T00:00:00", "content": "<h2>Cruise Schedule</h2>...<h3>Carnival</h3><h3>Terminal 25</h3>
    <h3>Monday, Oct 19 to Saturday Oct 24, 2026</h3>..."}]. One event per embarkation day, no times (dated 00:00).
    Titles drop the brand ('Breeze' = Carnival Breeze): the first <h3> is the line. Parsed with regexes so it also
    reads a browser-serialised copy of the feed."""
    out = []
    for e in re.split(r'"id":\s*\d+', h)[1:]:
        t = re.search(r'"title":\s*"(.*?)",\s*"start":\s*"(\d{4})-(\d\d)-(\d\d)', e, re.S)
        if not t:
            continue
        n = re.search(r'>([^<>]+?)(?:<|&lt;)\\?/span', t[1])
        name = htmllib.unescape(n[1] if n else text(t[1])).strip()
        name = re.sub(r"\s+(?:[A-Z]{2})$", "", name)  # 'Mariner of the Seas LC'
        name = re.sub(r"^7 Seas\b", "Seven Seas", name)
        ln = re.search(r'<h3>([^<&]+?)(?:<|&lt;)\\?/h3', e)
        line = ln[1].strip() if ln else None
        pre = GLS_LINES.get((line or "").lower(), "")
        if pre and not name.lower().startswith(pre.lower()):
            name = f"{pre} {name}"
        if name and not re.search(r"cancel", name, re.I) and name.lower() != "margaritaville":  # 2 MAS ships
            out.append(call(name, line, "gls", iso(t[2], t[3], t[4]), None))
    return out


def get_galveston(url):
    """The calendar page loads its events from admin-ajax.php (allowed in the site's robots.txt)."""
    today = date.today()
    u = (url.split("/cruise-parking")[0] + "/wp-admin/admin-ajax.php?action=meeting_calender"
         f"&start={today - timedelta(days=1)}&end={today + timedelta(days=WINDOW_AHEAD)}")
    return [get(u)]


# ---------------------------------------------------------------- New York (Manhattan + Brooklyn)

def parse_nyc_fc(h, today):
    """cruise.nyc 'Berthing Calendar' (NYCEDC, a public Power BI report with a FullCalendar month/multi-month visual,
    rendered by JavaScript): day cells <td role="gridcell" data-date="2026-09-01"> holding
    <div class="fc-event-title fc-sticky aVikingspcharMars aManhattanspcharspcharMCTspchar">Viking Mars</div>.
    The second class names the terminal (Manhattan MCT / Brooklyn BCT). Names only, no times: dated 00:00."""
    out, seen = [], set()
    for m in re.finditer(r'<td\b[^>]*data-date="(\d{4})-(\d\d)-(\d\d)"[^>]*>(.*?)(?=<td\b|</tr>)', h, re.S):
        for cls, name in re.findall(r'class="fc-event-title\b([^"]*)"[^>]*>([^<]+)<', m[4]):
            name = text(name)
            key = (m[1], m[2], m[3], name, cls)
            if not name or key in seen:
                continue
            seen.add(key)
            a = iso(m[1], m[2], m[3])
            if "Brooklyn" in cls or "BCT" in cls:
                out.append(call(name, None, None, a, None, name="Brooklyn"))
            else:
                out.append(call(name, None, "nyc", a, None))
    return out


def get_nyc(url, months=15):
    """Headless Chrome: open the Power BI report page, find the (nested, sandboxed) frame holding the calendar,
    switch it to the year view when offered, else step month by month with its 'next' button; then the same on the
    next report page (Brooklyn)."""
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    o = webdriver.ChromeOptions()
    for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--window-size=1800,1400"):
        o.add_argument(arg)
    drv = webdriver.Chrome(options=o)
    pages = []

    def find_cal(depth=0):
        if drv.find_elements(By.CSS_SELECTOR, ".fc"):
            return True
        if depth > 3:
            return False
        for i in range(len(drv.find_elements(By.TAG_NAME, "iframe"))):
            try:
                drv.switch_to.frame(drv.find_elements(By.TAG_NAME, "iframe")[i])
            except Exception:
                continue
            if find_cal(depth + 1):
                return True
            drv.switch_to.parent_frame()
        return False

    def grab():
        drv.switch_to.default_content()
        if not find_cal():
            return
        today_btn = drv.find_elements(By.CSS_SELECTOR, ".fc-today-button")
        if today_btn and today_btn[0].is_enabled():
            today_btn[0].click()
            time.sleep(2)
        pages.append(drv.page_source)
        for _ in range(months):
            nxt = drv.find_elements(By.CSS_SELECTOR, ".fc-next-button")
            if not nxt:
                break
            nxt[0].click()
            time.sleep(2)
            pages.append(drv.page_source)
    try:
        drv.set_page_load_timeout(90)
        drv.get(url)
        time.sleep(20)
        grab()
        drv.switch_to.default_content()
        nxt_page = drv.find_elements(By.CSS_SELECTOR, "button[aria-label='Next Page'], .navigation-wrapper button.pbi-glyph-chevronrightmedium")
        if nxt_page:
            nxt_page[-1].click()
            time.sleep(15)
            grab()
    finally:
        drv.quit()
    return pages


NYC_PBI = ("https://app.powerbi.com/view?r=eyJrIjoiZDY5NzQ0NjUtNDU1OS00OTJkLTk2NjYtZWJiYWNjN2JhYjEwIiwidCI6ImYxZDQx"
           "OThjLTk1ZTAtNDBmZS1iZjRhLTNmYWEyYmVhNGRiZCIsImMiOjN9&pageName=4042a34207c37055827e")


# ---------------------------------------------------------------- Baltimore (Maryland Port Administration)

def parse_cruise_maryland(h, today):
    """cruise.maryland.gov 'Cruise Maryland Schedule <year>' PDF (text, in reading order): a ship header in capitals
    ending in the year ('CARNIVAL PRIDE 2026', 'VISION OF THE SEAS 2026'), itinerary headers '7-Day Bahamas' /
    '12-Night Southern Caribbean' / '... (One Way)', then 'Dates: Feb. 22, May 10 & 24, Sept. 27, Oct. 11 & 18'
    (may wrap) up to 'Ports of Call: ...'. Each date is an embarkation day in Baltimore (no times: 00:00); the ship
    is back in Baltimore N days later unless the itinerary is one way."""
    out = []
    ship = year = nights = None
    one_way = False
    lines = [re.sub(r"^#+\s*", "", ln).strip() for ln in re.sub(r"<[^>]+>", "\n", h).splitlines()]
    buf = None
    for ln in lines + ["Ports of Call"]:
        sm = re.match(r"(?:Carnival\s+)?([A-Z][A-Z .'&-]{3,}?)\s+(20\d\d)$", ln)
        if sm and not re.match(r"CRUISE SCHEDULE", sm[1]):
            ship, year = smart(sm[1]), int(sm[2])
            continue
        im = re.match(r"(\d{1,2})\s*-\s*(Day|Night)\b", ln, re.I)
        if im:
            nights, one_way = int(im[1]), bool(re.search(r"one way", ln, re.I))
            continue
        dm = re.match(r"Dates?:\s*(.*)", ln)
        if dm:
            buf = dm[1]
            continue
        if buf is not None and not ln.startswith("Ports of Call"):
            buf += " " + ln
            continue
        if buf is not None and ship and year:
            mo = None
            for tok in re.findall(r"[A-Za-z]{3,}|\d{1,2}", buf):
                if tok[:3].lower() in MONTHS:
                    mo = MONTHS[tok[:3].lower()]
                elif tok.isdigit() and mo:
                    a = iso(year, mo, tok)
                    if not a:
                        continue
                    out.append(call(ship, None, "bwi", a, None))
                    if nights and not one_way:
                        back = (datetime.fromisoformat(a) + timedelta(days=nights)).strftime("%Y-%m-%dT00:00")
                        out.append(call(ship, None, "bwi", back, None))
        buf = None
    return out


def smart(s):
    return ps.smart_case(re.sub(r"\s+", " ", s).strip())


def pdf_text(data):
    """PDF bytes -> plain text in reading order (poppler pdftotext, installed on GitHub's runners)."""
    import shutil
    import subprocess
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext not installed (apt-get install poppler-utils)")
    return subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=data, capture_output=True,
                          check=True, timeout=120).stdout.decode("utf-8", "replace")


def get_bytes(url):
    import urllib.request
    import urllib.error
    req = urllib.request.Request(url, headers={"User-Agent": ps.UA, "Accept": "*/*"})
    for wait in (30, 90, None):  # 'Too Many Requests': wait as the site asks (or a while) and try again
        try:
            with ps._opener.open(req, timeout=ps.TIMEOUT) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 429 or wait is None:
                raise
            ra = e.headers.get("Retry-After", "")
            time.sleep(min(int(ra), 180) if ra.isdigit() else wait)


def get_cruise_maryland(url):
    """url has {year}: this year's PDF and next year's when it is published."""
    pages = []
    for y in (date.today().year, date.today().year + 1):
        try:
            pages.append(pdf_text(get_bytes(url.format(year=y))))
        except Exception as e:
            print(f"     Cruise Maryland {y}: {type(e).__name__}: {str(e)[:100]}")
        time.sleep(DELAY)
    return pages


# ---------------------------------------------------------------- Jacksonville (JAXPORT vessel schedule)

def parse_jaxport(h, today):
    """vesselschedule.jaxport.com/webx (JAXPORT public vessel schedule, about two weeks ahead; DataTables grid built
    by the page's script): Terminal | Berth | Ocean Carrier | Vessel | Voyage | Agent | Stevedore | Vessel Type |
    ETA 'mm/dd/yyyy HHMM'. Cruise ships are 'Passenger Liner'; arrival only. Jacksonville is not in the guide."""
    out, seen = [], set()
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 9 or not re.match(r"passenger", c[7], re.I):
            continue
        m = re.match(r"(\d\d)/(\d\d)/(\d{4})\s+(\d\d)(\d\d)", c[8])
        a = iso(m[3], m[1], m[2], f"{m[4]}:{m[5]}") if m else None
        if c[3] and a and (c[3], a) not in seen:
            seen.add((c[3], a))
            out.append(call(c[3], c[2] or None, None, a, None, name="Jacksonville"))
    return out


def get_jaxport(url):
    return [render(url, 'tr[role="row"] td')]


# ---------------------------------------------------------------- Bermuda (Department of Marine and Ports)

MONTH_UP = r"(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+(20\d\d)"
BDA_ROW = re.compile(r"(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day\W+(\d\d)/(\d\d)\W+(\d{4})\W+(\d{4})\W+"
                     r"([A-Z][A-Z0-9 .'&-]*[A-Z0-9])\W+\d{1,3}\W+(.*)")


def parse_bermuda(h, today):
    """marineandports.bm '<year> Cruise Ship Schedule' PDF (whole year; text as table rows, HTML or pdftotext
    -layout): a 'MARCH 2027' heading per month, then rows Weekday | 'arr/dep day' 24/26 | Arrive 0800 | Depart 1600 |
    VESSEL | Visit # | Berth | Line code | From/To | Agent. Heritage/King's Wharf = Royal Naval Dockyard; Hamilton
    and Penno's Wharf (St. George's) are kept under their own names."""
    out = []
    flat = re.sub(r"\s+", " ", h) if re.search(r"<tr\b", h, re.I) else h
    flat = re.sub(r"</t[dh]>", " | ", flat, flags=re.I)
    flat = re.sub(r"</tr>|<br\s*/?>|</p>", "\n", flat, flags=re.I)
    flat = htmllib.unescape(re.sub(r"<[^>]+>", " ", flat))
    year = mon = None
    for ln in flat.splitlines():
        mh = re.search(MONTH_UP, ln)
        if mh:
            mon, year = MONTHS[mh[1][:3].lower()], int(mh[2])
        m = BDA_ROW.search(ln)
        if not m or not mon:
            continue
        d1, d2 = int(m[1]), int(m[2])
        a = iso(year, mon, d1, f"{m[3][:2]}:{m[3][2:]}")
        dm, dy = (mon, year) if d2 >= d1 else ((mon % 12) + 1, year + (mon == 12))
        d = iso(dy, dm, d2, f"{m[4][:2]}:{m[4][2:]}")
        if not a:
            continue
        berth = m[6].lower()
        if "hamilton" in berth or "ham " in berth:
            out.append(call(m[5], None, None, a, d, name="Hamilton (Bermuda)"))
        elif "penno" in berth:
            out.append(call(m[5], None, None, a, d, name="St. George's (Bermuda)"))
        else:
            out.append(call(m[5], None, "bda", a, d))
    return out


def get_bermuda(url):
    """url has {year}: this year's schedule and next year's (published about a year ahead), via pdftotext -layout."""
    import shutil
    import subprocess
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext not installed (apt-get install poppler-utils)")
    pages = []
    for y in (date.today().year, date.today().year + 1):
        try:
            data = get_bytes(url.format(year=y))
            pages.append(subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=data,
                                        capture_output=True, check=True, timeout=120).stdout.decode("utf-8", "replace"))
        except Exception as e:
            print(f"     Bermuda {y}: {type(e).__name__}: {str(e)[:100]}")
        time.sleep(DELAY)
    return pages


# ---------------------------------------------------------------- St. Thomas & St. John (West Indian Company)

WICO_BERTHS = {"WICO", "AMSS", "AMNS", "AMHP", "STJ", "INANCH", "IANCH", "OANCH"}


def parse_wico(h, today):
    """wico-ltd.com 'St. Thomas & St. John Scheduled Cruise Ship Arrivals' PDF (fiscal year Oct-Sep, all berths:
    WICO Havensight dock, Crown Bay AMSS/AMNS/AMHP, anchorages, STJ = St. John), text rows from pdftotext -layout or
    a Markdown table: '04-Oct-26 | Sun | AMSS | Rhapsody of the Seas | San Juan, PR | St. Croix, USVI | 08 00 - 17 00'.
    A row continued after a page break has no date: it keeps the previous row's date."""
    out, day = [], None
    for ln in htmllib.unescape(h).splitlines():
        f = [x for x in re.split(r"\s*\|\s*|\s{2,}", ln.strip(" |\t")) if x]
        bi = next((i for i, x in enumerate(f) if x in WICO_BERTHS), None)
        if bi is None or bi + 1 >= len(f):
            continue
        dm = next((re.match(r"(\d\d)-([A-Z][a-z]{2})-(\d\d)$", x) for x in f[:bi] if re.match(r"\d\d-[A-Z][a-z]{2}-\d\d$", x)), None)
        if dm and dm[2].lower() in MONTHS:
            day = (2000 + int(dm[3]), MONTHS[dm[2].lower()], int(dm[1]))
        tm = re.search(r"(\d\d)\s?(\d\d)\s*-\s*(\d\d)\s?(\d\d)", f[-1])
        if not day or not tm:
            continue
        a = iso(*day, f"{tm[1]}:{tm[2]}")
        d = iso(*day, f"{tm[3]}:{tm[4]}")
        a, d = _fix_overnight(a, d)
        ship = f[bi + 1]
        if f[bi] == "STJ":
            out.append(call(ship, None, None, a, d, name="St. John (USVI)"))
        else:
            out.append(call(ship, None, "stt", a, d))
    return out


def get_wico(url):
    """The home page links the fiscal-year schedule PDFs ('FY-2027-SHIP-SCHEDULE-REV-4.pdf'): read the newest two
    (current and next fiscal year, when published) with pdftotext -layout."""
    import shutil
    import subprocess
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext not installed (apt-get install poppler-utils)")
    links = re.findall(r'href="(https?://[^"]+/FY-?(\d{4})[^"]*SCHEDULE[^"]*\.pdf)"', get(url), re.I)
    best = {}
    for u, fy in links:
        if int(fy) >= date.today().year:
            best[fy] = max(best.get(fy, ""), u)  # newest upload folder / revision sorts last
    pages = []
    for fy in sorted(best)[:2]:
        time.sleep(DELAY)
        data = get_bytes(best[fy])
        pages.append(subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=data,
                                    capture_output=True, check=True, timeout=120).stdout.decode("utf-8", "replace"))
    if not pages:
        raise ValueError("no FY schedule PDF linked on the WICO home page")
    return pages


# ---------------------------------------------------------------- Jamaica (Port Authority of Jamaica)

PAJ_PORTS = {"FALMOUTH": "fal", "OCHO RIOS": "ocj", "MONTEGO BAY": "mbj"}


def parse_portjam(h, today):
    """app.portjam.com/webcalv2 'Vessel Booking Calendar' (Port Authority of Jamaica; FullCalendar feed
    lib/fullcalendar/get-events.php?l=&start=&end=, about 14 months ahead): [{"prt_val": "7", "port": "FALMOUTH",
    "berth": "SOUTH PIER", "ship": "Norwegian Aqua", "start": "2027-09-29T07:00:00+00:00", "end": ...}]. Times are
    local despite the +00:00. Port Antonio / Kingston calls are kept under their own names."""
    import json
    i = h.find("[")
    try:
        evs = json.loads(htmllib.unescape(h[i:h.rfind("]") + 1])) if i >= 0 else []
    except ValueError:
        return []
    out = []
    for e in evs:
        ship, port = (e.get("ship") or "").strip(), (e.get("port") or "").strip().upper()
        s, en = (e.get("start") or "")[:16], (e.get("end") or "")[:16]
        if not ship or not re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d", s):
            continue
        d = en if re.match(r"\d{4}-\d\d-\d\dT\d\d:\d\d", en) and en > s else None
        pid = PAJ_PORTS.get(port)
        out.append(call(ship, None, pid, s, d, name=None if pid else port.title()))
    return out


def get_portjam(url):
    today = date.today()
    return [get(f"{url}lib/fullcalendar/get-events.php?l=&start={today - timedelta(days=1)}"
                f"&end={today + timedelta(days=WINDOW_AHEAD)}")]


# ---------------------------------------------------------------- St. Croix (Virgin Islands Port Authority)

def parse_vipa_stx(h, today):
    """viport.com 'Ann E. Abramson Marine Facility at Frederiksted Pier Cruise Ship Schedule' PDF (fiscal year
    Oct-Sep), rows from pdftotext -layout or a Markdown table: '10/19/2026 | Monday | FSTED SB | 8:00 | 18:00 |
    ADVENTURE/SEAS | FL | STT | 5238'. 'X/SEAS' = 'X of the Seas'. A date whose year is off (typo '1/7/2025' among
    January 2027) takes the previous row's year."""
    out, prev = [], None
    for ln in htmllib.unescape(h).splitlines():
        if "FSTED" not in ln:
            continue
        f = [x for x in re.split(r"\s*\|\s*|\s{2,}", ln.strip(" |\t")) if x]
        dm = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})$", f[0]) if f else None
        times = re.findall(r"\b(\d{1,2}:\d\d)\b", ln)
        ship = next((re.sub(r"\s*\d{1,2}:\d\d\s*", " ", x).strip() for x in f[3:]
                     if re.search(r"[A-Z]{3}", re.sub(r"\d{1,2}:\d\d", "", x)) and "FSTED" not in x), "")
        if not dm or len(times) < 2 or not ship:
            continue
        y, mo, dy = int(dm[3]), int(dm[1]), int(dm[2])
        if prev and y != prev[0] and not (y == prev[0] + 1 and mo < prev[1]):
            y = prev[0] + (mo < prev[1])
        prev = (y, mo)
        ship = re.sub(r"\s*/\s*SEAS(\s+\S{2,3})?$", " OF THE SEAS", ship.upper()).replace("GRANDEAUR", "GRANDEUR")
        a, d = _fix_overnight(iso(y, mo, dy, times[0]), iso(y, mo, dy, times[1]))
        if a:
            out.append(call(ship, None, "stx", a, d))
    return out


def get_vipa_stx(url):
    """The schedules page links several PDFs under opaque Wix file names (St. Thomas Crown Bay, St. Croix, this and
    next fiscal year): read each and keep those for the Frederiksted pier (Abramson)."""
    import shutil
    import subprocess
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext not installed (apt-get install poppler-utils)")
    links = sorted(set(re.findall(r'https://www\.viport\.com/_files/ugd/[0-9a-f_]+\.pdf', get(url))))
    pages = []
    for u in links[:8]:
        time.sleep(DELAY)
        try:
            t = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", "-", "-"], input=get_bytes(u),
                               capture_output=True, check=True, timeout=120).stdout.decode("utf-8", "replace")
        except Exception as e:
            print(f"     VIPA {u[-12:]}: {type(e).__name__}: {str(e)[:100]}")
            continue
        if re.search(r"ABRAMSON|FREDERIKSTED|FREDRIKSTED", t, re.I):
            pages.append(t)
    return pages


# ---------------------------------------------------------------- Barbados (Barbados Port Inc.)

BGI_DATE = re.compile(r"\b(\d{1,2})-([A-Z][a-z]{2})-(\d{2})\b")
BGI_TIME = re.compile(r"(?<![\d-])(\d{3,4})(?:\s*-\s*(\d{3,4}))?(?![\d-])")


def _hm(t):
    t = t.zfill(4)
    return f"{t[:2]}:{t[2:]}"


def parse_barbados(html, today):
    """Barbados Port Inc. season PDF (Bridgetown, plus Speightstown tender calls), as Markdown table rows from a
    renderer or pdftotext -layout lines: DAY | MONTH | d-Mon-yy | VESSEL | OPERATOR | 0700-2300 | Transit.
    Columns sometimes merge (date+vessel, time+call). A single time on two consecutive rows of the same ship is
    an overnight: arrival on the first, departure on the second; an unpaired single time is the arrival."""
    rows = []
    for ln in htmllib.unescape(html).splitlines():
        dm = BGI_DATE.search(ln)
        mon = MONTHS.get(dm[2].lower()) if dm else None
        if not mon:
            continue
        f = [x for x in re.split(r"\s*\|\s*|\s{2,}", ln.strip(" |\t")) if x]
        i = next(k for k, x in enumerate(f) if BGI_DATE.search(x))
        rest = BGI_DATE.sub("", f[i]).strip()
        ship = rest or (f[i + 1] if i + 1 < len(f) else "")
        tail = " ".join(f[i + (1 if rest else 2):])
        tm = BGI_TIME.search(tail)
        ship = ship.replace('"', "").replace("”", "").strip()
        if not tm or not re.search(r"[A-Za-z]{2}", ship):
            continue
        y = 2000 + int(dm[3])
        name = "Speightstown" if re.search(r"Speightstown", tail, re.I) else None
        rows.append([smart(ship) if ship.isupper() else re.sub(r"\s+", " ", ship), date(y, mon, int(dm[1])), tm[1], tm[2], name])
    out, used = [], set()
    for k, (ship, dt, t1, t2, name) in enumerate(rows):
        if k in used:
            continue
        a = iso(dt.year, dt.month, dt.day, _hm(t1))
        d = iso(dt.year, dt.month, dt.day, _hm(t2)) if t2 else None
        if not t2:
            nxt = next((j for j in range(k + 1, min(k + 8, len(rows))) if j not in used and rows[j][0] == ship
                        and not rows[j][3] and rows[j][4] == name and 0 < (rows[j][1] - dt).days <= 2), None)
            if nxt is not None:
                used.add(nxt)
                o = rows[nxt][1]
                d = iso(o.year, o.month, o.day, _hm(rows[nxt][2]))
        a, d = _fix_overnight(a, d)
        if a:
            out.append(call(ship, None, None if name else "bgi", a, d, name=name))
    return out


def get_barbados(url):
    """The flipbook page names the current season PDF in its viewer options ("source":"https:\\/\\/...pdf")."""
    m = re.search(r'"source"\s*:\s*"(https:[^"]+?\.pdf)"', get(url))
    if not m:
        raise RuntimeError("no PDF link on Barbados Port schedule page")
    time.sleep(DELAY)
    return [pdf_text(get_bytes(m[1].replace("\\/", "/")))]


# ---------------------------------------------------------------- Aruba (Aruba Ports Authority)

AUA_HEAD = re.compile(r"SCHEDULE\s+CRUISE\s*SHIP\s+([A-Z]+)\s+(\d{4})", re.I)
AUA_ROW = re.compile(r"^(?:(?:MON|TUE|WED|THU|FRI|SAT|SUN)\s+(\d{1,2})\s+)?([A-Z][A-Z0-9 .'&-]*?[A-Z0-9.])\s+"
                     r"(\d{1,2}\.\d\d|\*{2,})\s+(\d{1,2}\.\d\d|\*{2,})(?:\s+[A-Z]\b)?", re.I)


def parse_aruba(html, today):
    """Monthly 'SCHEDULE CRUISESHIP <MONTH> <YEAR>' PDFs: DAY DD SHIP ARR DEP BERTH, the day omitted for a second
    ship on the same date; '****' is an open time. '<SHIP>-Dept.' is the departure of a ship that arrived on an
    earlier row with '****' as departure (overnight / multi-day stay)."""
    out, open_, ym, day = [], {}, None, None
    for ln in htmllib.unescape(html).splitlines():
        h = AUA_HEAD.search(ln)
        if h and MONTHS.get(h[1][:3].lower()):
            ym, day = (int(h[2]), MONTHS[h[1][:3].lower()]), None
            continue
        f = [x for x in re.split(r"\s*\|\s*", ln.strip(" |\t")) if x and not set(x) <= set("-")]
        s = " ".join(f) if "|" in ln else re.sub(r"\s{2,}", " ", ln.strip())
        if "|" in ln and any(re.fullmatch(r"(\d{1,2}\.\d\d|\*+) (\d{1,2}\.\d\d|\*+)", x) for x in f):
            if len(f) > 1 and f[1].isdigit():
                day = int(f[1])
            continue        # two ships merged in one cell by the renderer; pdftotext gives them separate lines
        m = AUA_ROW.match(s)
        if not m or not ym:
            continue
        if m[1]:
            day = int(m[1])
        if day is None:
            continue
        ship = m[2].strip()
        t1, t2 = (None if "*" in t else t.replace(".", ":") for t in (m[3], m[4]))
        dept = re.search(r"\s*-\s*DEPT\.?$", ship, re.I)
        ship = smart(re.sub(r"\s*-\s*DEPT\.?$", "", ship, flags=re.I))
        if dept:
            if ship in open_ and t2:
                c = open_.pop(ship)
                c["d"] = iso(ym[0], ym[1], day, t2)
            continue
        c = call(ship, None, "aua", iso(ym[0], ym[1], day, t1), iso(ym[0], ym[1], day, t2) if t2 else None)
        if c["a"]:
            c["a"], c["d"] = _fix_overnight(c["a"], c["d"])
            out.append(c)
            if not t2:
                open_[ship] = c
    return out


def get_aruba(url):
    """The schedules page lists one PDF per month (current and coming months): fetch each one from this month on."""
    page = get(url)
    links = [(urljoin(url, u.replace("&#038;", "&")), mon, yr) for u, mon, yr in
             re.findall(r'href=["\']([^"\']*Cruise-Ship-Schedule-([A-Za-z]+)-(\d{4})[^"\']*\.pdf)["\']', page, re.I)]
    if not links:
        raise ValueError(f"no monthly PDF links on the page ({len(page)} chars)")
    today = date.today()
    want = {}
    for u, mon, yr in links:
        mo = MONTHS.get(mon[:3].lower())
        if mo and (int(yr), mo) >= (today.year, today.month):
            want.setdefault((int(yr), mo), u)
    texts = []
    for k in sorted(want)[:13]:
        time.sleep(DELAY)
        texts.append(pdf_text(get_bytes(want[k])))
    return texts


# ---------------------------------------------------------------- Fort Lauderdale (Port Everglades)

FLL_ONEWAY = re.compile(r"Panama Canal|Transatlantic|Passage|Repositioning|Crossing|Alaska|Europe|World|Grand Voyage", re.I)


def parse_port_everglades(html, today):
    """Port Everglades 'Find a Cruise' events (Simpleview CMS JSON): one event per departure with the ship in
    'location', the start date, and user fields Terminal (11), Number of Nights (14), Name of Account (15) and
    Round Trip? (13 / 25). Each departure is a turnaround call that day (times unknown); a round trip also gives
    the return call 'nights' days later, unless the same ship sails again that day (already a turnaround)."""
    import json
    try:
        docs = json.loads(html)["docs"]["docs"]
    except (ValueError, KeyError, TypeError):
        return []
    out, deps = [], set()
    rows = []
    for e in docs:
        ship, sd = (e.get("location") or "").strip(), e.get("startDate") or ""
        if not ship or "everglades" in ship.lower() or not re.match(r"\d{4}-\d\d-\d\d", sd):
            continue
        u = e.get("udfs_object") or {}
        nights = (u.get("14") or {}).get("value")
        rt = (u.get("25") or {}).get("value") == "Yes" or (u.get("13") or {}).get("value") is True \
            or not FLL_ONEWAY.search(e.get("title") or "")
        day = date.fromisoformat(sd[:10])
        rows.append((ship, day, nights, rt, (u.get("15") or {}).get("value")))
        deps.add((ship, day))
    seen = set()
    for ship, day, nights, rt, line in rows:
        if (ship, day) not in seen:
            seen.add((ship, day))
            out.append(call(ship, line, "fll", day.isoformat() + "T00:00", None))
        if rt and isinstance(nights, int) and 0 < nights < 60:
            back = day + timedelta(days=nights)
            if (ship, back) not in deps and (ship, back) not in seen:
                seen.add((ship, back))
                out.append(call(ship, line, "fll", back.isoformat() + "T00:00", None))
    return out


def get_port_everglades(url):
    """The Find a Cruise page queries the CMS's public events endpoint with a page token from
    /plugins/core/get_simple_token/ (robots.txt allows both); page through departures in the window."""
    import json
    import urllib.parse
    base = re.match(r"https?://[^/]+", url)[0]
    token = re.sub(r"<[^>]+>|\s", "", get(base + "/plugins/core/get_simple_token/"))
    today = date.today()
    pages, skip, count = [], 0, None
    while count is None or skip < count:
        q = {"filter": {"date_range": {"start": {"$date": f"{today}T04:00:00.000Z"},
                                       "end": {"$date": f"{today + timedelta(days=WINDOW_AHEAD)}T04:00:00.000Z"}}},
             "options": {"limit": 100, "skip": skip, "count": True, "castDocs": False,
                         "fields": {"recid": 1, "title": 1, "location": 1, "startDate": 1, "endDate": 1,
                                    "udfs_object": 1}, "sort": {"date": 1}}}
        time.sleep(DELAY)
        h = get(f"{base}/includes/rest_v2/plugins_events_events_by_date/find/?json="
                + urllib.parse.quote(json.dumps(q, separators=(",", ":"))) + "&token=" + token)
        pages.append(h)
        d = json.loads(h)["docs"]
        count = d.get("count") or 0
        if not d.get("docs"):
            break
        skip += 100
        if skip >= 1500:
            break
    return pages


# ---------------------------------------------------------------- sources
# "key" is the sample/source id (port id from data/index.json where one exists; "jax" = Jacksonville, not in the
# index, so its calls carry name= instead). URLs with {year} are expanded by their fetch function.

SOURCES = [
    {"key": "fll", "name": "Fort Lauderdale (Port Everglades)", "url": "https://www.porteverglades.net/find-a-cruise/",
     "parse": parse_port_everglades, "fetch": get_port_everglades},
    {"key": "aua", "name": "Aruba (Aruba Ports Authority)", "url": "https://www.arubaports.com/main/cruiseship-schedules/",
     "parse": parse_aruba, "fetch": get_aruba},
    {"key": "gls", "name": "Galveston", "url": "https://www.portofgalveston.com/cruise-parking/cruise-schedule/",
     "parse": parse_galveston, "fetch": get_galveston},
    {"key": "nyc", "name": "New York (Manhattan + Brooklyn)", "url": NYC_PBI, "parse": parse_nyc_fc, "fetch": get_nyc},
    {"key": "bwi", "name": "Baltimore (Cruise Maryland)",
     "url": "https://cruise.maryland.gov/Documents/CruiseMarylandSchedule{year}.pdf",
     "parse": parse_cruise_maryland, "fetch": get_cruise_maryland},
    {"key": "jax", "name": "Jacksonville (JAXPORT)", "url": "https://vesselschedule.jaxport.com/webx/",
     "parse": parse_jaxport, "fetch": get_jaxport},
    {"key": "bda", "name": "Bermuda (Marine and Ports)",
     "url": "https://www.marineandports.bm/Documents/Shipping_schedules/{year}%20Cruise%20Ship%20Schedule.pdf",
     "parse": parse_bermuda, "fetch": get_bermuda},
    {"key": "stt", "name": "St. Thomas (WICO)", "url": "https://wico-ltd.com/", "parse": parse_wico, "fetch": get_wico},
    {"key": "stx", "name": "Frederiksted (VIPA)", "url": "https://www.viport.com/schedule-cruise-ports",
     "parse": parse_vipa_stx, "fetch": get_vipa_stx},
    {"key": "fal", "name": "Jamaica (Port Authority of Jamaica)", "url": "https://app.portjam.com/webcalv2/",
     "parse": parse_portjam, "fetch": get_portjam},
    {"key": "bgi", "name": "Barbados (Barbados Port Inc.)", "url": "https://barbadosport.com/cruise-schedule-pdf/",
     "parse": parse_barbados, "fetch": get_barbados},
]
