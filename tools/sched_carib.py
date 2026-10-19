"""Official cruise schedules for Caribbean, Florida, Bahamas and Bermuda ports (see port_schedules.py for conventions)."""
import re
from datetime import date, datetime, timedelta

from port_schedules import text, cells, iso, call, get, render, DELAY, WINDOW_AHEAD, MONTHS


def _fix_overnight(a, d):
    """Same-day times where departure < arrival mean the ship leaves after midnight."""
    if a and d and d < a:
        d = (datetime.fromisoformat(d) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    return a, d


def parse_apiqroo(h, today):
    """servicios.apiqroo.com.mx/programacion (APIQROO, Cozumel; the whole current month, server-rendered):
    <td data-title="PUERTO">terminal | PAÍS | CRUCERO 'M/S CARNIVAL BREEZE' | FECHA 'd/m/yyyy' | ETA | FECHA | ETD | ESTATUS
    (circle_red.png = cancelled)."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        if 'data-title="CRUCERO"' not in row or "circle_red" in row:
            continue
        c = [text(x) for x in cells(row)]
        if len(c) < 7:
            continue

        def dt(day, hm):
            m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", day)
            return iso(m[3], m[2], m[1], hm) if m and hm else None
        a, d = dt(c[3], c[4]), dt(c[5], c[6])
        if c[2] and (a or d):
            out.append(call(c[2], None, "coz", a, d))
    return out


MESES = {m: i + 1 for i, m in enumerate(["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                          "septiembre", "octubre", "noviembre", "diciembre"])}


def parse_progreso(h, today):
    """puertosyucatan.com (ASIPONA Progreso) 'Itinerario - Terminal de cruceros': the whole year, date only:
    # | 'jueves, 1 de enero de 2026' | Barco | Naviera 'ccl' | Tripulantes | Pasajeros. No times: arrival = 00:00."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 4:
            continue
        m = re.search(r"(\d{1,2}) de ([a-zé]+) de (\d{4})", c[1].lower())
        if not m or m[2] not in MESES or not c[2]:
            continue
        out.append(call(c[2], None, "prg", iso(m[3], MESES[m[2]], m[1]), None))
    # rows are in date order; drop typos such as one '2027' row among November 2026
    return [x for i, x in enumerate(out) if i + 1 >= len(out) or x["a"] <= out[i + 1]["a"] or
            (datetime.fromisoformat(x["a"]) - datetime.fromisoformat(out[i + 1]["a"])).days < 60]


def parse_cayman(h, today):
    """caymanport.com (Port Authority of the Cayman Islands) month calendar: <td class="calendar-day"> with
    <div class="day-number">d</div> and one <a id="div-ship-detail-N"> Ship </a> per vessel; month/year are the
    selected sc_month/sc_year options. Cargo names end in '*', ships that missed the call are red. No times:
    the call is dated 00:00 (times only via a per-ship popup)."""
    mo = re.search(r'name="sc_month">.*?value="(\d+)" selected', h, re.S)
    yr = re.search(r'name="sc_year">.*?value="(\d{4})" selected', h, re.S)
    if not (mo and yr):
        return []
    out = []
    for day in re.findall(r'<td class="calendar-day "[^>]*>(.*?)</td>', h, re.S):
        dn = re.search(r'class="day-number">(\d+)<', day)
        for attrs, name in re.findall(r'<a id="div-ship-detail-\d+"([^>]*)>([^<]+)</a>', day):
            name = name.strip()
            if dn and name and not name.endswith("*") and "red" not in attrs.lower():
                out.append(call(name, None, "gcm", iso(yr[1], mo[1], dn[1]), None))
    return out


def get_cayman(url):
    """Cruise ships (vessel_type=22) for the current month, then the next 14 months through the page's own
    month form (POST sc_month/sc_year, the form's no-JavaScript action)."""
    import time
    pages = [get(url)]
    try:
        nxt = date.today().replace(day=1)
        for _ in range(14):
            nxt = (nxt + timedelta(days=32)).replace(day=1)
            time.sleep(DELAY)
            pages.append(get(url.split("?")[0], {"sc_month": nxt.month, "sc_year": nxt.year,
                                                 "vessel_type": "22", "vessel_location": "2"}))
    except Exception as e:
        print(f"     Grand Cayman later months: {type(e).__name__}: {str(e)[:100]}")
    return pages


def parse_curports(h, today):
    """hms.curports.com public cruise view (Curaçao Ports Authority, about 3 months ahead; table built by the
    page's grid script): Arrival 'mm/dd/yyyy HH:MM' | Departure | Ship (a title="Ship Info") | Flag | Pax |
    Berth | Harbor | Last/Next port | Cruise line | Agent."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        if 'title="Ship Info"' not in row:
            continue
        c = [text(x) for x in cells(row)]
        if len(c) < 9:
            continue

        def dt(s):
            m = re.match(r"(\d\d)/(\d\d)/(\d{4}) (\d\d:\d\d)", s)
            return iso(m[3], m[1], m[2], m[4]) if m else None
        a, d = dt(c[0]), dt(c[1])
        if c[2] and (a or d):
            out.append(call(c[2], c[8] or None, "cur", a, d))
    return out


def get_curports(url):
    return [render(url, 'a[title="Ship Info"]')]


TPA_CODES = {"RCI": "", "CEL": "Celebrity ", "CCL": "Carnival ", "NCL": "Norwegian ", "MAS": "Margaritaville at Sea ",
             "HAL": "Holland America ", "PCL": "", "DCL": "Disney ", "MSC": "MSC ", "VV": "", "AZ": "Azamara "}


def parse_tampa(h, today):
    """Port Tampa Bay (The Events Calendar REST API, wp-json/tribe/events/v1/events, category cruise-schedules,
    about a year ahead): {"events": [{"title": "RCI Radiance of the Seas", "start_date": "2026-10-19 00:00:00",
    "all_day": true, "categories": [{"name": "Royal Caribbean International"}, ...]}], "next_rest_url"}.
    Titles start with a line code (RCI, CCL, CEL, MAS, NCL). Turnaround days only, no times: dated 00:00."""
    import json
    i = h.find("{")
    d = json.loads(h[i:]) if i >= 0 else {}
    out = []
    for e in d.get("events", []):
        cats = [c.get("name", "") for c in e.get("categories", [])]
        if not any("cruise" in c.lower() for c in cats):
            continue
        title = text(e.get("title", ""))
        m = re.match(r"([A-Z]{2,4})\s+(.+)", title)
        if m and m[1] in TPA_CODES:
            pre, name = TPA_CODES[m[1]], m[2]
            title = name if name.lower().startswith(pre.lower().strip() or "\0") else pre + name
        line = next((c for c in cats if c.lower() != "cruise schedules"), None)
        ds = re.match(r"(\d{4})-(\d\d)-(\d\d)", e.get("start_date", ""))
        if title and ds:
            out.append(call(title, line, "tpa", iso(ds[1], ds[2], ds[3]), None))
    return out


def get_tampa(url):
    """url has {lo}/{hi}; follows next_rest_url (50 events per page, max 15 pages)."""
    import json, time
    today = date.today()
    u = url.format(lo=today.isoformat(), hi=(today + timedelta(days=WINDOW_AHEAD)).isoformat())
    pages = []
    for _ in range(15):
        h = get(u)
        pages.append(h)
        nxt = json.loads(h[h.find("{"):]).get("next_rest_url")
        if not nxt:
            break
        u = nxt if "categories=" in nxt else nxt + "&categories=cruise-schedules"
        time.sleep(DELAY)
    return pages


def parse_portzante(h, today):
    """portzante.com (Port Zante cruise terminal, St. Kitts; whole season, one table per month, server-rendered):
    <caption>... for November 2026 ...</caption>, rows: '1 November<span>Sunday</span>' |
    'Ship<span>Line</span>' (line ignored: often wrong) | pier | '08:00 <span>→</span> 17:00'."""
    out = []
    for cap, body in re.findall(r"<caption[^>]*>(.*?)</caption>(.*?)</table>", h, re.S):
        my = re.search(r"for ([A-Za-z]+) (\d{4})", text(cap))
        if not my or my[1][:3].lower() not in MONTHS:
            continue
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.S):
            c = cells(row)
            if len(c) < 4:
                continue
            dm = re.match(r"\s*(\d{1,2}) ([A-Za-z]+)", c[0])
            ship = text(c[1].split("<span")[0])
            t = re.search(r"(\d{1,2}:\d\d)\D+(\d{1,2}:\d\d)", text(c[3]))
            if not dm or not ship or dm[2][:3].lower() not in MONTHS:
                continue
            mo = MONTHS[dm[2][:3].lower()]
            a = iso(my[2], mo, dm[1], t[1]) if t else iso(my[2], mo, dm[1])
            d = iso(my[2], mo, dm[1], t[2]) if t else None
            a, d = _fix_overnight(a, d)
            out.append(call(ship, None, "skb", a, d))  # the line column is unreliable ('Azamara' under HAL)
    return out


def _fc_cells(h):
    """FullCalendar 3 month grid -> [(yyyy-mm-dd, cell_html)]: each week's .fc-content-skeleton has a <thead> row of
    day cells (data-date) and <tbody> rows whose cells may span columns/rows; map every cell to its day."""
    out = []
    for sk in re.findall(r'<div class="fc-content-skeleton">\s*<table>(.*?)</table>', h, re.S):
        days = [(re.search(r'data-date="(\d{4}-\d\d-\d\d)"', a) or [None, None])[1]
                for a in re.findall(r"<td\b([^>]*)>", sk.split("</thead>")[0])]
        body = sk.split("<tbody>", 1)[1] if "<tbody>" in sk else ""
        busy = {}  # column -> rows still covered by a rowspan
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.S):
            col = 0
            for attrs, inner in re.findall(r"<td\b([^>]*)>(.*?)</td>", row, re.S):
                while busy.get(col, 0) > 0:
                    col += 1
                rs = re.search(r'rowspan="(\d+)"', attrs)
                cs = re.search(r'colspan="(\d+)"', attrs)
                span = int(cs[1]) if cs else 1
                if rs and int(rs[1]) > 1:
                    for k in range(col, col + span):
                        busy[k] = int(rs[1])  # decremented below, so this row counts too
                if col < len(days) and days[col]:
                    out.append((days[col], inner))
                col += span
            busy = {k: v - 1 for k, v in busy.items() if v - 1 > 0}
    return out


def carnival_parser(port):
    """Carnival Corporation port sites (carnival-port theme) embed the bestcruiseports.com public calendar
    (FullCalendar month grid, rendered by JavaScript): <div class="reservation reservation_..."><div>Ship</div>
    <div class="reservation_time">07:00-16:00</div></div> inside day cells."""
    def parse(h, today):
        out = []
        for day, inner in _fc_cells(h):
            for name, t in re.findall(r'<div class="reservation\b[^"]*">\s*<div[^>]*>(.*?)</div>\s*'
                                      r'(?:<div class="reservation_time">(.*?)</div>)?', inner, re.S):
                y, m, d = day.split("-")
                tm = re.match(r"\s*(\d{1,2}:\d\d)\s*-\s*(\d{1,2}:\d\d)", text(t or ""))
                a = iso(y, m, d, tm[1]) if tm else iso(y, m, d)
                dd = iso(y, m, d, tm[2]) if tm else None
                a, dd = _fix_overnight(a, dd)
                if text(name):
                    out.append(call(text(name), None, port, a, dd))
        return out
    parse.__name__ = f"parse_carnival_{port}"
    return parse


def get_carnival(url, months=14):
    """Headless Chrome: the port-schedule page, then the calendar's own 'next' button month by month."""
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    import time
    o = webdriver.ChromeOptions()
    for arg in ("--headless=new", "--no-sandbox", "--disable-dev-shm-usage", "--window-size=1600,1200"):
        o.add_argument(arg)
    drv = webdriver.Chrome(options=o)
    pages = []
    try:
        drv.set_page_load_timeout(90)
        drv.get(url)
        time.sleep(8)
        pages.append(drv.page_source)
        for _ in range(months):
            btn = drv.find_elements(By.CSS_SELECTOR, ".fc-next-button")
            if not btn:
                break
            btn[0].click()
            time.sleep(DELAY + 3)
            pages.append(drv.page_source)
    finally:
        drv.quit()
    return pages


def parse_calendarwiz(port):
    """CalendarWiz month view (calendar.php?crd=..&op=cal&month=M&year=Y), used by the City of Key West's pier
    schedules: each event is <a title="Carnival Dream(B) fm Galveston October 12, 2026 11:00 - 19:00">;
    '(B)' is the pier, 'fm ...' the previous port. Cancelled calls say CANCELED in the title."""
    def parse(h, today):
        out = []
        for t in re.findall(r'<a title="([^"]+)"[^>]*class="cat', h):
            t = text(t)
            m = re.match(r"(.+?) ([A-Z][a-z]+) (\d{1,2}), (\d{4})(?: (\d{1,2}:\d\d)\s*-\s*(\d{1,2}:\d\d))?", t)
            if not m or m[2][:3].lower() not in MONTHS or re.search(r"cancel", t, re.I):
                continue
            ship = re.split(r"\(|\s+fm\s+|\s+\S+/\S+", m[1])[0].strip(" -")
            mo = MONTHS[m[2][:3].lower()]
            a = iso(m[4], mo, m[3], m[5]) if m[5] else iso(m[4], mo, m[3])
            d = iso(m[4], mo, m[3], m[6]) if m[6] else None
            a, d = _fix_overnight(a, d)
            if ship:
                out.append(call(ship, None, port, a, d))
        return out
    parse.__name__ = f"parse_calendarwiz_{port}"
    return parse


def get_calendarwiz(url):
    """url ends with &op=cal; this month and the next 14 (stops early at two empty months)."""
    import time
    pages, empty = [], 0
    m = date.today().replace(day=1)
    for i in range(15):
        if i:
            time.sleep(DELAY)
        h = get(f"{url}&month={m.month}&year={m.year}")
        pages.append(h)
        empty = 0 if re.search(r'<a title="[^"]+\d{4}[^"]*"[^>]*class="cat', h) else empty + 1
        if empty >= 2:
            break
        m = (m + timedelta(days=32)).replace(day=1)
    return pages


def portcall_parser(port, group):
    """PortCall cruise schedule widget (bviports.org, 'rolling 18 months', rendered by React):
    <li class="port-group"><div class="port-name">Road Town</div> ... <div class="year">2026</div> then
    <div class="cruise"> blocks: arrival '19 Oct - 07:00', departure 'dep 17:00' or 'dep 20 Dec 08:00',
    <div class="vessel">RHAPSODY OF THE SEAS</div>. Only the named port group is kept."""
    def parse(h, today):
        out = []
        for g in re.split(r'<li class="port-group">', h)[1:]:
            name = re.search(r'class="port-name">([^<]*)', g)
            if not name or name[1].strip().lower() != group.lower():
                continue
            year = None
            for m in re.finditer(r'class="year">(\d{4})<|class="arrival">(.*?)</div>\s*<div class="departure">(.*?)</div>'
                                 r'.*?class="vessel">(.*?)</div>', g, re.S):
                if m[1]:
                    year = int(m[1])
                    continue
                arr = re.match(r"(\d{1,2}) ([A-Za-z]{3}) - (\d{1,2}:\d\d)", text(m[2]))
                dep = re.match(r"dep\s+(?:(\d{1,2}) ([A-Za-z]{3}) )?(\d{1,2}:\d\d)", text(re.sub(r"<!--.*?-->", "", m[3])))
                if not year or not arr or arr[2].lower() not in MONTHS:
                    continue
                am = MONTHS[arr[2].lower()]
                a = iso(year, am, arr[1], arr[3])
                d = None
                if dep and dep[1] and dep[2].lower() in MONTHS:
                    dm = MONTHS[dep[2].lower()]
                    d = iso(year + (dm < am), dm, dep[1], dep[3])
                elif dep:
                    d = iso(year, am, arr[1], dep[3])
                    a, d = _fix_overnight(a, d)
                if text(m[4]):
                    out.append(call(text(m[4]), None, port, a, d))
        return out
    parse.__name__ = f"parse_portcall_{port}"
    return parse


def get_portcall(url):
    return [render(url, ".homepage-cruiseschedule .cruise .vessel")]


CARNIVAL_SITES = [  # (port id, name, site) - Carnival Corporation ports on the bestcruiseports.com calendar
    ("amb", "Amber Cove", "https://www.ambercoveport.com"),
    ("gtk", "Grand Turk", "https://www.grandturkport.com"),
    ("cel", "Celebration Key", "https://www.celebrationkeyport.com"),
    ("rtb", "Roatan (Isla Tropicale)", "https://www.islatropicaleport.com"),
]

SOURCES = [
    {"key": "coz", "name": "Cozumel (APIQROO)", "url": "https://servicios.apiqroo.com.mx/programacion/", "parse": parse_apiqroo},
    {"key": "prg", "name": "Progreso (ASIPONA)", "url": "https://www.puertosyucatan.com/pr/calendariodearribo.shtml",
     "parse": parse_progreso},
    {"key": "gcm", "name": "Grand Cayman", "url": "https://www.caymanport.com/ship-schedules-calendar/?vessel_type=22",
     "parse": parse_cayman, "fetch": get_cayman},
    {"key": "cur", "name": "Curacao", "url": "https://hms.curports.com/webx/dashb.ashx?db=curps.public&MENU_ID=WEBX-TB-PUBLIC-CRUISE",
     "parse": parse_curports, "fetch": get_curports},
    {"key": "tpa", "name": "Tampa", "url": "https://www.porttb.com/wp-json/tribe/events/v1/events?categories=cruise-schedules"
     "&start_date={lo}&end_date={hi}&per_page=50", "parse": parse_tampa, "fetch": get_tampa},
    {"key": "skb", "name": "St. Kitts (Port Zante)", "url": "https://portzante.com/cruiseship-schedule/", "parse": parse_portzante},
    {"key": "kwe", "name": "Key West (Pier B)", "url": "https://www.calendarwiz.com/calendars/calendar.php?crd=caribenautical&op=cal",
     "parse": parse_calendarwiz("kwe"), "fetch": get_calendarwiz},
    {"key": "tor", "name": "Tortola (BVI Ports Authority)", "url": "https://bviports.org/services/cruise",
     "parse": portcall_parser("tor", "Road Town"), "fetch": get_portcall},
] + [{"key": _id, "name": _name, "url": _site + "/port-schedule/", "parse": carnival_parser(_id), "fetch": get_carnival}
     for _id, _name, _site in CARNIVAL_SITES]
