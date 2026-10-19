"""Official cruise schedules for European ports (port authorities / terminal operators only, no aggregators).

Each parser: (html, today) -> list of call() dicts, like the parsers in port_schedules.py.
Plug in with:  from sched_europe import SOURCES as EUROPE;  SOURCES += EUROPE
"""
import io
import json
import re
import time
import urllib.parse
import urllib.request
import zipfile
from datetime import date, datetime, timedelta
from xml.etree import ElementTree as ET

from port_schedules import text, cells, iso, call, get, DELAY, WINDOW_AHEAD, UA, TIMEOUT
import port_schedules as _ps

ES_MONTHS = {m: i + 1 for i, m in enumerate(
    ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
     "noviembre", "diciembre"])}


def _next_day_if_before(a, d):
    """Departure given only as a time on the arrival date: an earlier time means it leaves the next day."""
    if a and d and d < a:
        return (datetime.fromisoformat(d) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    return d


def _dmy(s, hm=None):
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    return iso(m[3], m[2], m[1], hm) if m else None


# ---------------------------------------------------------------- Spain

def parse_vigo(h, today):
    """apvigo.es 'Previsión cruceros' (10 rows per page): div.row.registro with div.col fecha llegada 'dd/mm/yyyy' |
    buque | eslora | horaLlegada | horaSalida | procedencia | destino | consignataria. One date per call."""
    out = []
    for row in re.findall(r'<div class="row registro[^"]*">(.*?)</div>\s*</div>', h, re.S):
        f = {k.strip(): text(v) for k, v in re.findall(r'<div class="col ([^"]*)">(.*?)</div>', row, re.S)}
        day, name = f.get("fecha llegada", ""), f.get("buque", "")
        a = _dmy(day, f.get("hora horaLlegada") or None)
        d = _next_day_if_before(a, _dmy(day, f.get("hora horaSalida") or None))
        if name and a:
            out.append(call(name, None, "vgo", a, d))
    return out


def get_vigo(url):
    """Page 1, then every page linked from its paginador (.../desplegar/N/...)."""
    first = get(url)
    pages = [first]
    links = sorted(set(re.findall(r'href="([^"]*/cruceros/desplegar/(\d+)/urlretorno=[^"]*)"', first)), key=lambda x: int(x[1]))
    for link, n in links:
        if n != "1":
            time.sleep(DELAY)
            pages.append(get(link.replace("&amp;", "&")))
    return pages


def parse_cartagena(h, today):
    """apc.es 'Previsión de cruceros': one table per month, <caption>Octubre_2026</caption>,
    rows Día | Hora 'HH:MM - HH:MM' | Buque | Naviera | PAX | Enlace."""
    out = []
    for mon, year, body in re.findall(r"<caption>\s*([A-Za-z]+)_(\d{4})\s*</caption>(.*?)</table>", h, re.S):
        mo = ES_MONTHS.get(mon.lower())
        if not mo:
            continue
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.S):
            c = [text(x) for x in cells(row)]
            if len(c) < 4 or not c[0].isdigit():
                continue
            t = re.findall(r"\d{1,2}:\d\d", c[1])
            a = iso(year, mo, c[0], t[0]) if t else iso(year, mo, c[0])
            d = _next_day_if_before(a, iso(year, mo, c[0], t[1])) if len(t) > 1 else None
            if c[2] and a:
                out.append(call(c[2], c[3] or None, "cgn", a, d))
    return out


def parse_tenerife(h, today):
    """puertosdetenerife.org 'Agenda de cruceros' (one server-side table, paged by DataTables in the browser):
    Llegada dd/mm/yyyy | hora | Salida dd/mm/yyyy | hora | Consignatario | Buque | Pax | Crew | Puerto | Muelle | ...
    The list covers all the province's ports; only 'S/C DE TENERIFE' is Tenerife (La Palma/La Gomera/El Hierro skipped)."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 9 or "TENERIFE" not in c[8].upper():
            continue
        a, d = _dmy(c[0], c[1] or None), _dmy(c[2], c[3] or None)
        if c[5] and (a or d):
            out.append(call(c[5], None, "tci", a, d))
    return out


# ---------------------------------------------------------------- Greece

def parse_piraeus(h, today):
    """olp.gr 'CRUISE_SCHEDULE YYYY' spreadsheet (as an HTML table, see get_piraeus): a month calendar - a row of
    7 dates 'YYYY-MM-DD' (Sun..Sat columns) followed by rows of entries in the same columns:
    '(LOA) SHIP NAME (EX OLD NAME) HH:MM-HH:MM PAX E'. A multi-day stay is 'HH:MM-' on the first day, the bare
    name on middle days and '-HH:MM' on the last day. Cells are sometimes cut short ('08:00-18')."""
    out, open_ = [], {}
    days = None
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)][:7]
        if sum(bool(re.fullmatch(r"\d{4}-\d\d-\d\d", x)) for x in c) >= 1 and all(
                not x or re.fullmatch(r"\d{4}-\d\d-\d\d", x) for x in c):
            days = c
            continue
        if not days:
            continue
        for day, s in zip(days, c):
            if not day or not s.startswith("("):
                continue
            s = re.sub(r"^\([\d,.]*\)\s*", "", s)
            s = re.sub(r"\(EX [^)]*\)?|\bEX\s+\S.*?(?=\s\d|\s-|$)", "", s).strip()
            m = re.search(r"(?:^|\s)(\d{1,2}:\d\d)?\s*-\s*(\d{1,2}(?::\d\d)?)?(?=\s|$)", s)
            if not m or not (m[1] or m[2]):
                continue
            name = re.sub(r"\s*\([^)]*\)?\s*", " ", s[:m.start()]).strip()
            name = re.sub(r"^AIDA (\w+)$", r"AIDA\1", name)  # 'AIDA BLU' -> 'AIDABLU' (-> AIDAblu)
            y, mo, dd = day.split("-")
            dep = m[2] and (m[2] if ":" in m[2] else m[2] + ":00")
            a = iso(y, mo, dd, m[1]) if m[1] else None
            d = iso(y, mo, dd, dep) if dep else None
            if not name:
                continue
            if a and not d:
                open_[name] = a
                continue
            if d and not a:
                a = open_.pop(name, None)
            elif a and d:
                d = _next_day_if_before(a, d)  # '08:00-01:00' leaves after midnight
            out.append(call(name, None, "pir", a, d))
    out += [call(n, None, "pir", a, None) for n, a in open_.items()]  # still in port at the end of the file
    return out


def _get_bytes(url):
    url = urllib.parse.quote(url, safe=":/?&=%#+,;@")  # file names with spaces
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with _ps._opener.open(req, timeout=TIMEOUT) as r:
        return r.read()


def xlsx_to_html(data):
    """First sheet of an .xlsx as a plain <table> (stdlib only): one <tr> per sheet row, one <td> per column
    (gaps filled), shared strings resolved, date-formatted numbers written as YYYY-MM-DD."""
    z = zipfile.ZipFile(io.BytesIO(data))
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
    date_styles = set()
    if "xl/styles.xml" in z.namelist():
        st = ET.fromstring(z.read("xl/styles.xml"))
        custom = {n.get("numFmtId"): n.get("formatCode", "") for n in st.iter("{%s}numFmt" % ns["m"])}
        xfs = st.find("m:cellXfs", ns)
        for i, xf in enumerate(xfs if xfs is not None else []):
            f = xf.get("numFmtId", "0")
            if 14 <= int(f) <= 22 or re.search(r"[dy]", re.sub(r'"[^"]*"|\[[^]]*\]', "", custom.get(f, "")), re.I):
                date_styles.add(i)
    sheet = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))[0]
    rows = []
    for r in ET.fromstring(z.read(sheet)).iter("{%s}row" % ns["m"]):
        vals = {}
        for c in r.findall("m:c", ns):
            col = 0
            for ch in re.match(r"[A-Z]+", c.get("r", "A"))[0]:
                col = col * 26 + ord(ch) - 64
            v = c.find("m:v", ns)
            t = c.get("t")
            if t == "s" and v is not None:
                val = shared[int(v.text)]
            elif t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
            else:
                val = v.text if v is not None else ""
                if val and int(c.get("s", "0")) in date_styles and re.fullmatch(r"\d+(\.\d+)?", val):
                    val = (date(1899, 12, 30) + timedelta(days=int(float(val)))).isoformat()
            vals[col] = val
        width = max(vals) if vals else 0
        rows.append("<tr>" + "".join(f"<td>{htmllib_escape(vals.get(i, ''))}</td>" for i in range(1, width + 1)) + "</tr>")
    return "<table>" + "\n".join(rows) + "</table>"


def htmllib_escape(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def get_piraeus(url):
    """The cruise-terminal page links one spreadsheet per year ('CRUISE_SCHEDULE 2027 03-10-2026.xlsx', the date in
    the name changes with every update). Download this year's and next year's and turn them into HTML tables."""
    page = get(url)
    years = {date.today().year, date.today().year + 1}
    pages = []
    for href, y in re.findall(r'href="([^"]*CRUISE_SCHEDULE(?:%20|\s)+(\d{4})[^"]*\.xlsx)"', page):
        if int(y) in years:
            time.sleep(DELAY)
            pages.append(xlsx_to_html(_get_bytes(urllib.parse.urljoin(url, href.replace("&amp;", "&")))))
    return pages


# ---------------------------------------------------------------- Germany, Sweden, Netherlands

def parse_rostock(h, today):
    """rostock-port.de 'Kreuzfahrtanläufe' (Warnemünde + Rostock): per call <h3 data-date="2026-05-27 00:00:00">,
    <p>07:00-17:00</p> (overnight: '07:00-14. 18:00' = leaves on the 14th at 18:00), ship link, <p>line</p>."""
    out = []
    for y, mo, dd, t, name, line in re.findall(
            r'data-date="(\d{4})-(\d\d)-(\d\d)[^"]*">[^<]*</h3>\s*<p>([^<]*)</p>.*?class="async"[^>]*>([^<]+)<span'
            r'.*?</h3>\s*<p>([^<]*)</p>', h, re.S):
        m = re.match(r"\s*(\d{1,2}:\d\d)?\s*-\s*(?:(\d{1,2})\.\s*)?(\d{1,2}:\d\d)?", t)
        a = iso(y, mo, dd, m[1]) if m and m[1] else iso(y, mo, dd)
        d = None
        if m and m[3]:
            dep = datetime(int(y), int(mo), int(dd))
            if m[2]:
                while dep.day != int(m[2]):
                    dep += timedelta(days=1)
            d = iso(dep.year, dep.month, dep.day, m[3])
            d = _next_day_if_before(a, d)
        if name.strip():
            out.append(call(name.strip(), text(line) or None, "wnm", a, d))
    return out


STOCKHOLM_API = ("https://www.portsofstockholm.com/api/stm/portentry/Get/?pagesize=500"
                 "&filter=(vesseltype%20%3D%20119%20OR%20vesseltype%20%3D%20209)&status=InPortAndExpected"
                 "&lazy=true&ajax=true&requestKey=request-{key}")


def get_stockholm(url):
    """The vessel-calls page fills its list from this JSON API (cruise ship types 119/209, in port + expected)."""
    return [get(STOCKHOLM_API.format(key=int(time.time()) % 100000000))]


def parse_stockholm(h, today):
    """portsofstockholm.com API: {"items": [{"harbor": "Stohab", "vesselName", "calculatedArrivalDateTime",
    "calculatedDepartureDateTime", "arrivalDateTime", "departureDateTime"}]} (local time). Nynäshamn/Kapellskär skipped."""
    out = []
    for it in json.loads(h).get("items", []):
        if it.get("harbor") != "Stohab":
            continue
        a = (it.get("arrivalDateTime") or it.get("calculatedArrivalDateTime") or "")[:16] or None
        d = (it.get("departureDateTime") or it.get("calculatedDepartureDateTime") or "")[:16] or None
        if it.get("vesselName") and (a or d):
            out.append(call(it["vesselName"], None, "sto", a, d))
    return out


def parse_amsterdam(h, today):
    """sea.cruiseportamsterdam.com/cruise-calendar/YYYY (year = the active data-year button): per ship
    <figcaption><span>04<br>Apr</span>, <p class="ship-title">, <p class="ship-time"><strong>20:00</strong> -
    <strong>17:30 uur</strong> [Departure: 06 Apr]."""
    m = re.search(r'data-year="(\d{4})" class="button button-active"', h)
    year = int(m[1]) if m else today.year
    out = []
    for b in h.split("ship-image")[1:]:
        cap = re.search(r"<figcaption[^>]*>\s*<span>(\d{1,2})<br>([A-Za-z]{3})", b)
        name = re.search(r'<p class="ship-title">(.*?)</p>', b, re.S)
        tm = re.search(r'<p class="ship-time">(.*?)</p>', b, re.S)
        if not (cap and name and tm) or cap[2].lower() not in _ps.MONTHS:
            continue
        t = re.findall(r"\d{1,2}:\d\d", text(tm[1]))
        mo = _ps.MONTHS[cap[2].lower()]
        a = iso(year, mo, cap[1], t[0]) if t else iso(year, mo, cap[1])
        dep = re.search(r"Departure:\s*(\d{1,2}) ([A-Za-z]{3})", text(tm[1]))
        dy, dmo = (dep[1], _ps.MONTHS.get(dep[2].lower(), mo)) if dep else (cap[1], mo)
        d = iso(year + (1 if dmo < mo else 0), dmo, dy, t[1]) if len(t) > 1 else None
        out.append(call(text(name[1]), None, "ams", a, _next_day_if_before(a, d)))
    return out


def get_amsterdam(url):
    y = date.today().year
    pages = [get(url)]
    for yy in (y, y + 1):
        time.sleep(DELAY)
        pages.append(get(f"{url.rstrip('/')}/{yy}"))
    return pages[1:]


# ---------------------------------------------------------------- Iceland (Dokk port-call platform)

DOKK_PORTS = {"ISREY": "rkv", "AKU": "aey"}  # Reykjavík (Faxaflóahafnir), Akureyri (Hafnasamlag Norðurlands)
DOKK_API = "https://portal.dokk.is/api/embed/calendar/?start_date={lo}&end_date={hi}&port=&location=&vessel="


def parse_dokk(h, today):
    """portal.dokk.is public cruise calendar JSON (what portal.dokk.is/embed/calendar shows): a list of
    {"port_locode", "vessel_name", "arrival": "2027-07-01T09:00:00Z", "departure", "status", "vessel_type"}.
    Icelandic ports keep UTC all year, so the UTC times are local times."""
    out = []
    for e in json.loads(h):
        p = DOKK_PORTS.get(e.get("port_locode"))
        if not p or e.get("status") in ("cancelled", "rejected"):
            continue
        a, d = (e.get("arrival") or "")[:16] or None, (e.get("departure") or "")[:16] or None
        if e.get("vessel_name") and (a or d):
            out.append(call(e["vessel_name"], None, p, a, d))
    return out


def get_dokk(url):
    """One request per month, as the calendar page does, from this month to the end of next year."""
    pages, first = [], date.today().replace(day=1)
    end = date.today() + timedelta(days=WINDOW_AHEAD)
    while first <= end:
        nxt = (first + timedelta(days=32)).replace(day=1)
        pages.append(get(DOKK_API.format(lo=first.isoformat(), hi=(nxt - timedelta(days=1)).isoformat())))
        first = nxt
        time.sleep(DELAY)
    return pages


# ---------------------------------------------------------------- Croatia

def parse_dubrovnik(h, today):
    """portdubrovnik.hr 'Preuzmi raspored - najave za YYYY.xlsx' (as an HTML table, see get_dubrovnik): report rows
    Pokret | Smještaj | Berth | 'SHIP NAME Prev port/Next port' | Flag Owner | LOA | GT | 'YYYY-MM-DD HH:MM:SS' (from) |
    'YYYY-MM-DD HH:MM:SS' (to) | ... (day/month subtotal rows in between are skipped). Gruž cruise port."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 9 or not re.match(r"\d{4}-\d\d-\d\d", c[7]):
            continue
        words = c[3].split()
        k = next((i for i, w in enumerate(words) if "/" in w), len(words))
        name = words[:k]
        while len(name) > 1 and not name[-1].isupper():  # 'MONET Vela Luka/Kotor': drop the port's first words
            name.pop()
        a, d = c[7][:16].replace(" ", "T"), c[8][:16].replace(" ", "T") if re.match(r"\d{4}-", c[8]) else None
        if name:
            out.append(call(" ".join(name), None, "dbv", a, d))
    return out


def get_dubrovnik(url):
    """The 'Najave dolazaka' page lists one file per year; take the .xlsx ones for this year and later."""
    page = get(url)
    pages = []
    for href, y in re.findall(r'href="([^"]*?(\d{4})\.*\.xlsx)"', page):
        if int(y) >= date.today().year:
            time.sleep(DELAY)
            pages.append(xlsx_to_html(_get_bytes(urllib.parse.urljoin(url, href.replace("&amp;", "&")))))
    return pages

def parse_split(h, today):
    """portsplit.hr 'Plan posjeta brodova' (whole year, server-rendered): # | Ship | 'dd.mm. yyyy.' [+ 'noćenje dd.mm.' or
    'odlazak dd.mm.' = departure day] | 'HH:MM → HH:MM' | GT | LOA | draft | pax | | agent | status."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 11 or re.search(r"otkaz", c[10], re.I):
            continue
        m = re.match(r"(\d{1,2})\.(\d{1,2})\.\s*(\d{4})", c[2])
        if not m:
            continue
        t = re.findall(r"\d{1,2}:\d\d", c[3])
        a = iso(m[3], m[2], m[1], t[0]) if t else iso(m[3], m[2], m[1])
        d = None
        if len(t) > 1:
            n = re.search(r"(?:noćenje|odlazak)\s*(\d{1,2})\.(\d{1,2})\.", c[2])
            if n:
                y = int(m[3]) + (1 if int(n[2]) < int(m[2]) else 0)
                d = iso(y, n[2], n[1], t[1])
            else:
                d = _next_day_if_before(a, iso(m[3], m[2], m[1], t[1]))
        if c[1]:
            out.append(call(c[1], None, "spu", a, d))
    return out



# ---------------------------------------------------------------- Norway

def _eu_local(utc, base_hours):
    """UTC 'YYYYMMDDTHHMMSSZ' -> local ISO for a European zone (base offset + EU summer time rule)."""
    t = datetime.strptime(utc[:15], "%Y%m%dT%H%M%S")

    def last_sunday(y, mo):
        d = date(y, mo, 31)
        return datetime(y, mo, d.day - (d.weekday() + 1) % 7, 1)
    summer = last_sunday(t.year, 3) <= t < last_sunday(t.year, 10)
    return (t + timedelta(hours=base_hours + summer)).strftime("%Y-%m-%dT%H:%M")


def parse_ical(port, base_hours):
    """iCalendar feed: one VEVENT per call, SUMMARY = ship, DTSTART/DTEND in UTC ('...Z')."""
    def parse(h, today):
        h = re.sub(r"\r?\n[ \t]", "", h)  # unfold
        out = []
        for ev in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", h, re.S):
            f = dict(re.findall(r"^([A-Z-]+)(?:;[^:\n]*)?:(.*)$", re.sub(r"BEGIN:VALARM.*?END:VALARM", "", ev, flags=re.S), re.M))
            name = f.get("SUMMARY", "").strip()
            a, d = f.get("DTSTART", ""), f.get("DTEND", "")
            if not name or not a.endswith("Z") or re.search(r"cancel|kansel", f.get("STATUS", "") + name, re.I):
                continue
            out.append(call(name, None, port, _eu_local(a, base_hours), _eu_local(d, base_hours) if d.endswith("Z") else None))
        return out
    parse.__name__ = f"parse_ical_{port}"
    return parse


# ---------------------------------------------------------------- UK

def parse_lerwick(h, today):
    """lerwick-harbour.co.uk/sectors/cruise/YYYY ('Visiting Cruise Ships and Tall Ships - 2026'): a month heading row
    ('April') then rows (class tall-ship skipped) Arr 'Fri 03' | ETA | Ship | From | LOA | Berth | Pax | Agent | Dep 'Fri 03' | ETD | To."""
    m = re.search(r"Visiting Cruise Ships[^<]*?(\d{4})", h)
    year = int(m[1]) if m else today.year
    out, mo = [], None
    for attrs, row in re.findall(r"<tr\b([^>]*)>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if "tall-ship" in attrs:  # sail-training vessels, not cruise ships
            continue
        if len(c) == 1 and c[0][:3].lower() in _ps.MONTHS and len(c[0]) <= 9:
            mo = _ps.MONTHS[c[0][:3].lower()]
            continue
        if not mo or len(c) < 10:
            continue
        ad, dd = re.search(r"(\d{1,2})", c[0]), re.search(r"(\d{1,2})", c[8])
        if not ad:
            continue
        a = iso(year, mo, ad[1], c[1] or None) or iso(year, mo, ad[1])
        d = None
        if dd and c[9]:
            dmo, dy = (mo, year) if int(dd[1]) >= int(ad[1]) else ((mo % 12) + 1, year + (mo == 12))
            d = iso(dy, dmo, dd[1], c[9])
        if c[2]:
            out.append(call(c[2], None, "ler", a, d))
    return out


def get_lerwick(url):
    """One page per season (/sectors/cruise/2026); next year's page appears once its list is published."""
    pages = []
    for y in (date.today().year, date.today().year + 1):
        try:
            pages.append(get(f"{url}{y}"))
        except Exception as e:  # next season not published yet (404)
            print(f"     Lerwick {y}: {type(e).__name__}: {str(e)[:80]}")
        time.sleep(DELAY)
    return pages


# ---------------------------------------------------------------- Cádiz

def parse_cadiz(h, today):
    """puertocadiz.com cruise table, one month per table: header 'Octubre 2026', then rows Nº | Buque | Día escala |
    Día semana | Eslora | Origen | Destino | Primera escala | Consignatario | Hora llegada | Hora salida."""
    out = []
    for mon, year, body in re.findall(r'<th[^>]*colspan="11"[^>]*>\s*([A-Za-zé]+)\s+(\d{4})\s*</th>(.*?)</table>', h, re.S):
        m = ES_MONTHS.get(mon.lower())
        if not m:
            continue
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
            c = cells(row)
            dm = re.fullmatch(r"(\d{1,2})(?:\s*-\s*(\d{1,2}))?", c[2].strip()) if len(c) == 11 else None
            if not dm:
                continue
            a = iso(year, m, dm[1], c[9].strip() or None)
            if dm[2]:  # overnight '10-11' (a range ending on a smaller day runs into the next month)
                ey, em = (int(year), m) if int(dm[2]) > int(dm[1]) else ((int(year) + 1, 1) if m == 12 else (int(year), m + 1))
                d = iso(ey, em, dm[2], c[10].strip() or None)
            else:
                d = _next_day_if_before(a, iso(year, m, dm[1], c[10].strip() or None))
            if c[1].strip() and a:
                out.append(call(c[1].strip(), None, "cad", a, d))
    return out


def get_cadiz(url):
    """The page server-renders the current month; later months come from the site's own WordPress ajax search
    (form POST action=apbc_cruceros_search). Best effort: a failing month is skipped."""
    pages = [get(url)]
    t = date.today()
    y, m = t.year, t.month
    for _ in range(WINDOW_AHEAD // 30 + 1):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        time.sleep(DELAY)
        try:
            pages.append(get("https://www.puertocadiz.com/wp-admin/admin-ajax.php",
                             {"action": "apbc_cruceros_search", "apbcAnyo": ny, "apbcMes": nm,
                              "apbcAnyoOld": y, "apbcMesOld": m}))
            if 'colspan="11"' not in pages[-1] and ny > t.year:
                break  # the site only offers years that have published schedules
        except Exception:
            pass
        y, m = ny, nm
    return "\n".join(pages)


SOURCES = [
    {"key": "pir", "name": "Athens (Piraeus)", "url": "https://www.olp.gr/en/services-olp/cruise-terminal",
     "parse": parse_piraeus, "fetch": get_piraeus},
    {"key": "tci", "name": "Tenerife", "url": "https://www.puertosdetenerife.org/cruceros-previstos/", "parse": parse_tenerife},
    {"key": "cgn", "name": "Cartagena (Spain)", "url": "https://www.apc.es/webapc/actAPC/cruceros/prevision",
     "parse": parse_cartagena},
    {"key": "vgo", "name": "Vigo", "url": "https://www.apvigo.es/es/paginas/prevision_cruceros", "parse": parse_vigo,
     "fetch": get_vigo},
    {"key": "wnm", "name": "Warnemünde (Rostock)", "url": "https://www.rostock-port.de/schiffsverkehr/kreuzschifffahrt/anlaeufe",
     "parse": parse_rostock},
    {"key": "sto", "name": "Stockholm", "url": "https://www.portsofstockholm.com/vessel-calls/", "parse": parse_stockholm,
     "fetch": get_stockholm},
    {"key": "ams", "name": "Amsterdam", "url": "https://sea.cruiseportamsterdam.com/cruise-calendar/",
     "parse": parse_amsterdam, "fetch": get_amsterdam},
    {"key": "dbv", "name": "Dubrovnik", "url": "https://www.portdubrovnik.hr/index.php/hr/promet/najave-dolazaka",
     "parse": parse_dubrovnik, "fetch": get_dubrovnik},
    {"key": "spu", "name": "Split", "url": "https://portsplit.hr/plan-posjeta", "parse": parse_split},
    {"key": "svg", "name": "Stavanger",
     "url": "https://www.stavangerhavn.com/EntityList/Calendar/11edb967-d955-498e-a354-7c6a96bd089f/"
            "5605d242-d639-ef11-8409-6045bdf3b319/a1c61573-79f0-4441-8a01-925a4621fc77/icalendar",
     "parse": parse_ical("svg", 1)},
    {"key": "ler", "name": "Lerwick", "url": "https://www.lerwick-harbour.co.uk/sectors/cruise/", "parse": parse_lerwick,
     "fetch": get_lerwick},
    {"key": "cad", "name": "Cádiz", "parse": parse_cadiz, "fetch": get_cadiz,
     "url": "https://www.puertocadiz.com/el-puerto/instalaciones-para-traficos-especificos/cruceros-y-trafico-de-pasajeros/"},
    {"key": "rkv", "name": "Reykjavík + Akureyri", "url": "https://portal.dokk.is/embed/calendar", "parse": parse_dokk,
     "fetch": get_dokk},
]

# Global Ports Holding sites in this region that use the same schedule JSON as port_schedules.GPH_SITES.
GPH_EU = [("lis", "Lisbon", "https://lisboncruiseport.pt"), ("kus", "Kuşadası", "https://kusadasicruiseport.com")]
SOURCES += [{"key": _id, "name": _name, "url": _site + _ps.GPH_API, "parse": _ps.gph_parser(_id), "fetch": _ps.get_gph}
            for _id, _name, _site in GPH_EU]
