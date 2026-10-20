"""Official cruise schedules for northern European / North Atlantic ports (port authorities, harbour masters, VTS,
cruise-terminal operators only, no aggregators).

Each parser: (html, today) -> list of call() dicts, like the parsers in port_schedules.py.
Plug in with:  from sched_north import SOURCES as NORTH;  SOURCES += NORTH
"""
import html as _html
import json
import re
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone

from port_schedules import text, cells, iso, call, get, render, DELAY, WINDOW_AHEAD
import port_schedules as _ps
import sched_europe as _eu
import sched_pacific as _pac  # PDF helpers: get_bytes, pdf_text, table_rows


def _later(a, d):
    """Departure that would sort before the arrival (time-less 'PM' etc.): drop it rather than invent a time."""
    return d if not (a and d and d < a) else None


# ---------------------------------------------------------------- UK

def parse_southampton_xml(h, today):
    """ABP Southampton VTS raw cruise list /xml/sotcruiseship.xml (the page's own data file; the HTML page fills its
    table from it with JavaScript): <row> ship_name, arrival '19-Oct-26 06:13', departure, berth, agent.
    Far-off calls show 'AM'/'PM'/'TBA' instead of a time: the date is kept (00:00), a departure that would then sort
    before the arrival is dropped."""
    out = []

    def dt(s):
        m = re.match(r"\s*(\d{1,2})-([A-Za-z]{3})-(\d{2,4})\s*(\d{1,2}:\d\d)?", s or "")
        if not m or m[2].lower() not in _ps.MONTHS:
            return None
        y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        return iso(y, _ps.MONTHS[m[2].lower()], m[1], m[4]) if m[4] else iso(y, _ps.MONTHS[m[2].lower()], m[1])
    for row in re.findall(r"<row>(.*?)</row>", h, re.S):
        f = dict(re.findall(r"<([a-z_.]+)>([^<]*)</\1>", row))
        a, d = dt(f.get("arrival")), dt(f.get("departure"))
        name = text(f.get("ship_name", ""))
        if name and (a or d):
            out.append(call(name, None, "sou", a, _later(a, d)))
    return out


def parse_dover(h, today):
    """portofdover.com 'Cruise - Schedule & Tickets' table: Date 'October 28, 2026' | Cruise Line | Vessel |
    Terminal | Arrives '06:00' | Departs '18:00' | Call Type (a hidden placeholder ferry table is skipped)."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        m = re.fullmatch(r"([A-Za-z]+) (\d{1,2}), (\d{4})", c[0]) if len(c) >= 6 else None
        if not m or m[1][:3].lower() not in _ps.MONTHS:
            continue
        y, mo, dd = m[3], _ps.MONTHS[m[1][:3].lower()], m[2]
        a = iso(y, mo, dd, c[4] or None) or iso(y, mo, dd)
        d = iso(y, mo, dd, c[5]) if re.match(r"\d{1,2}:\d\d", c[5]) else None
        if a and d and d < a:  # overnight
            d = (datetime.fromisoformat(d) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        if c[2] and not re.search(r"cancel", " ".join(c), re.I):
            out.append(call(c[2], c[1] or None, "dvr", a, d))
    return out


# ---------------------------------------------------------------- Denmark / Sweden

def parse_cmp_all(h, today):
    """Copenhagen Malmö Port 'ships in port' (cmport.com, about one week ahead): one <div class="singleCall"> per
    call with 'columnTitle : ' / 'columnValue' pairs (Vessel name, Vessel type 'Cruise ship', Purpose 'Cruise call',
    Terminal, Status, ETD '19 Oct - 26 at 1700'); the ETA is in the call's header row. Copenhagen and Visby calls
    get their port ids, Malmö calls are kept by name (no port page, but part of the ship's itinerary)."""
    out = []

    def dt(s):
        m = re.search(r"(\d{1,2}) ([A-Za-z]{3})[a-z]* - (\d{2}) at (\d\d)(\d\d)", s or "")
        if not m or m[2].lower() not in _ps.MONTHS:
            return None
        return iso(2000 + int(m[3]), _ps.MONTHS[m[2].lower()], m[1], f"{m[4]}:{m[5]}")
    for b in h.split('<div class="singleCall')[1:]:
        f = {text(k).rstrip(" :"): text(v) for k, v in re.findall(
            r'<span class="columnTitle">(.*?)</span>\s*<span class="columnValue">(.*?)</span>', b, re.S)}
        if "cruise" not in (f.get("Vessel type", "") + f.get("Purpose", "")).lower():
            continue
        q = re.search(r'To quay <span class="greenColored">\s*([^<]*?)\s*<', b)
        quay, term = (q[1] if q else "").upper(), f.get("Terminal", "").lower()
        port, pname = ("vby", None) if "visby" in term or quay.startswith("V") else ("cph", None) \
            if quay.startswith("C") or term in ("oceankaj", "langelinie", "nordre toldbod") else (None, "Malmö") \
            if quay.startswith("M") else (None, None)
        head = re.search(r"\d{1,2} [A-Za-z]{3}[a-z]* - \d{2} at \d{4}", text(b[:3000]))
        a, d = dt(head[0] if head else None), dt(f.get("ETD"))
        name = f.get("Vessel name")
        if (port or pname) and name and (a or d) and not re.search(r"cancel", f.get("Status", ""), re.I):
            out.append(call(name, None, port, a, _later(a, d), name=pname))
    return out


def get_cmp(url):
    """Plain GET; if the served page has no call blocks (consent/JS shell), render it in headless Chrome."""
    h = get(url)
    if '<div class="singleCall' not in h:
        h = render(url, "div.singleCall")
    return [h]


def parse_rotterdam(h, today):
    """Cruise Port Rotterdam 'Cruise Calls' (cruiseportrotterdam.nl, WordPress events grid, 15 per page): per call
    <h3><a href=".../events/20102026/?event_date=2026-10-20">MSC Preziosa</a></h3> then 'dinsdag, 07:00 - 17:00'.
    A departure time earlier than the arrival means the next morning; an equal one is unknown and left out."""
    out = []
    for b in re.split(r'<li class="[^"]*grid-item', h)[1:]:
        m = re.search(r'<h3><a href="[^"]*event_date=(\d{4})-(\d\d)-(\d\d)"[^>]*>(.*?)</a>', b, re.S)
        if not m:
            continue
        t = re.search(r"(\d{1,2}:\d\d)\s*-\s*(\d{1,2}:\d\d)", text(b))
        a = iso(m[1], m[2], m[3], t[1] if t else None) or iso(m[1], m[2], m[3])
        d = iso(m[1], m[2], m[3], t[2]) if t else None
        if a and d and d < a:
            d = (datetime.fromisoformat(d) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        name = re.sub(r"\s*\((maiden call|eerste bezoek)[^)]*\)", "", text(m[4]), flags=re.I)
        if name and not re.search(r"geannuleerd|cancel", b, re.I):
            out.append(call(name, None, "rtm", a, d if d != a else None))
    return out


def get_rotterdam(url):
    """Page 1 and the further pages its pagination links (/cruise-calls/page/N/), max 30."""
    pages = [get(url)]
    n = max([int(x) for x in re.findall(r'/cruise-calls/page/(\d+)/', pages[0])] or [1])
    for i in range(2, min(n, 30) + 1):
        time.sleep(DELAY)
        pages.append(get(f"{url.rstrip('/')}/page/{i}/"))
    return pages


# ---------------------------------------------------------------- Norway

def parse_flam(h, today):
    """Flåm Port arrival list (flamport.no/arrival-list, this year and next): Date 'dd.mm.yy' | Ship | ETA | ETD |
    No. Of Hours '24:00' | From | To | Pier/Anchor | LOA | GRT | PAX. The departure is arrival + hours (so stays
    over midnight land on the right day).
    The page builds that table in the browser from api.flamport.no/Open/index.php: a JSON list of {"ship",
    "eta": "2027-04-29 04:30:00", "etd", ...} in UTC, which is what the daily run fetches."""
    i = h.find("[{")
    if i >= 0:
        try:
            rows = json.loads(h[i:h.rfind("}]") + 2])
        except ValueError:
            rows = []

        def local(s):
            m = re.match(r"(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)", s or "")
            return _eu._eu_local(f"{m[1]}{m[2]}{m[3]}T{m[4]}{m[5]}00Z", 1) if m else None
        out = []
        for r in rows:
            ship = (r.get("ship") or "").strip() if isinstance(r, dict) else ""
            a, d = local(r.get("eta")), local(r.get("etd"))
            if ship and (a or d) and not re.search(r"cancel|kansel", ship, re.I):
                out.append(call(ship, None, "flm", a, _later(a, d)))
        if out:
            return out
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", c[0]) if len(c) >= 5 else None
        if not m or not c[1]:
            continue
        y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
        a = iso(y, m[2], m[1], c[2] or None) or iso(y, m[2], m[1])
        hrs = re.fullmatch(r"(\d{1,3}):(\d\d)", c[4])
        if hrs and int(hrs[1]) + int(hrs[2]):
            d = (datetime.fromisoformat(a) + timedelta(hours=int(hrs[1]), minutes=int(hrs[2]))).strftime("%Y-%m-%dT%H:%M")
        else:
            d = _later(a, iso(y, m[2], m[1], c[3]) if c[3] else None)
        if not re.search(r"cancel|kansel", " ".join(c), re.I):
            out.append(call(c[1], None, "flm", a, d))
    return out


def parse_tromso(h, today):
    """Tromsø Havn 'Cruise calls' (tromso.havn.no): DataTables tables #cruisearrival (upcoming, all rows in the
    served HTML) and #cruisearrivalpast: Vessel | Port (quay) | Arrival 'YYYY-MM-DD HH:MM' | Departure | From port |
    To port | Passengers. Coastal-express suffixes like 'Midnatsol LEFO' (call sign) are dropped."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 4:
            continue
        a, d = (re.fullmatch(r"(\d{4})-(\d\d)-(\d\d) (\d\d:\d\d)", x) for x in c[2:4])
        if not a:
            continue
        a = iso(a[1], a[2], a[3], a[4])
        d = iso(d[1], d[2], d[3], d[4]) if d else None
        name = re.sub(r"\s+(?=[A-Z0-9]*\d)[A-Z0-9]{4,6}$|\s+L[A-Z]{3}$|\s*\(cruise\)", "", c[0], flags=re.I).strip()
        if name:
            out.append(call(name, None, "tos", a, _later(a, d)))
    return out


def portcall_parser(port, other=None):
    """Norwegian harbour sites built on the Grieg/Portwin port-call system render each call as
    <div class="anlopsitem" data-port-call="{JSON}"> with portCallId, statusCode, arrivalTime/departureTime (local,
    'YYYY-MM-DDTHH:MM:SS'), quayVisit[].quayUsage.name and vessel{name, vesselType 'Cruiseskip'}.
    other: {quay-name substring: port name} for anchorages/harbours of the same authority without a page in the app
    (e.g. Kristiansand Havn's 'Reden Mandal')."""
    def parse(h, today):
        out = []
        for raw in re.findall(r'data-port-call="([^"]*)"', h):
            try:
                e = json.loads(_html.unescape(raw))
            except ValueError:
                continue
            v = e.get("vessel") or {}
            if "cruise" not in (v.get("vesselType") or "cruise").lower() or str(e.get("statusCode")) in ("9", "C"):
                continue
            quays = " ".join(((q.get("quayUsage") or {}).get("name") or "") for q in e.get("quayVisit") or [])
            pname = next((n for k, n in (other or {}).items() if k.lower() in quays.lower()), None)

            def dt(s):
                m = re.match(r"(\d{4})-(\d\d)-(\d\d)T(\d\d:\d\d)", s or "")
                return iso(m[1], m[2], m[3], m[4]) if m else None
            a, d = dt(e.get("arrivalTime")), dt(e.get("departureTime"))
            name = smart(v.get("name") or "")
            if name and (a or d):
                out.append(call(name, None, None if pname else port, a, _later(a, d), name=pname))
        return out
    parse.__name__ = f"parse_portcall_{port}"
    return parse


def smart(n):
    """'AidaNova' (as some registers write it) -> 'AIDAnova'."""
    return re.sub(r"^Aida(?=[A-Z])", "AIDA", n.strip())


def _utc_ms_local(ms, base_hours=1):
    """Epoch milliseconds (UTC) -> local ISO for a CET/CEST port."""
    return _eu._eu_local(datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y%m%dT%H%M%SZ"), base_hours)


def parse_powerpages_calendar(port):
    """Microsoft Power Pages 'EntityList/Calendar' JSON (what the port's cruise calendar page loads for its month
    view): {"success": 1, "result": [{"title": ship, "start": epoch ms UTC, "end": ..., "description":
    "Kai: ...\\nFra: ...\\nTil: ..."}]}."""
    def parse(h, today):
        i = h.find("{")
        data = json.loads(h[i:]) if i >= 0 else {}
        out = []
        for e in data.get("result") or []:
            name, a, d = (e.get("title") or "").strip(), e.get("start"), e.get("end")
            if not name or not a or re.search(r"kansel|cancel", name + (e.get("description") or ""), re.I):
                continue
            a = _utc_ms_local(a)
            out.append(call(name, None, port, a, _later(a, _utc_ms_local(d) if d else None)))
        return out
    parse.__name__ = f"parse_powerpages_{port}"
    return parse


def get_powerpages_calendar(url):
    """The calendar JSON for today .. end of next year, in 3-month slices (the month view asks for ~6 weeks)."""
    pages, lo = [], date.today().replace(day=1)
    end = date(date.today().year + 1, 12, 31)
    while lo <= end:
        hi = (lo + timedelta(days=95)).replace(day=1)
        pages.append(get(f"{url}?from={lo.isoformat()}T00:00:00Z&to={hi.isoformat()}T00:00:00Z"))
        lo = hi
        time.sleep(DELAY)
    return pages


# ---------------------------------------------------------------- Atlantic islands

def parse_tenerife_islands(h, today):
    """Puertos de Tenerife 'Agenda de cruceros' (same page as sched_europe.parse_tenerife, which keeps only Santa Cruz
    de Tenerife): Llegada dd/mm/yyyy | hora | Salida | hora | Consignatario | Buque | Pax | Crew | Puerto | Muelle.
    Here the province's other ports: S/C de La Palma -> spc, La Gomera and El Hierro by name."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 9 or "TENERIFE" in c[8].upper() or not c[8].strip():
            continue
        port = c[8].upper()
        p, n = ("spc", None) if "PALMA" in port else (None, "La Gomera") if "GOMERA" in port else \
            (None, "El Hierro") if "HIERRO" in port else (None, c[8].title())
        a, d = _eu._dmy(c[0], c[1] or None), _eu._dmy(c[2], c[3] or None)
        if c[5] and (a or d):
            out.append(call(c[5], None, p, a, _later(a, d), name=n))
    return out


def parse_apram(h, today):
    """APRAM (Portos da Madeira) 'Reserva de cais' (apram.pt/reserva-cais?port=ptfnc, about two months ahead):
    Dia | Navio | Chegada 'dd/mm/yyyy HH:MM' | Partida | Porto de Origem | Porto de Destino | Agente.
    get_apram marks Porto Santo pages with '<!--port=ptpxo-->'; those calls are kept by name."""
    p, n = (None, "Porto Santo") if h.startswith("<!--port=ptpxo-->") else ("fnc", None)
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.S)]
        if len(c) < 4:
            continue
        a, d = _eu._dmy(c[2], c[2][-5:]), _eu._dmy(c[3], c[3][-5:])
        if c[1] and a:
            out.append(call(c[1], None, p, a, _later(a, d), name=n))
    return out


def get_apram(url):
    pages = [get(url)]
    time.sleep(DELAY)
    try:
        pages.append("<!--port=ptpxo-->" + get(url.replace("ptfnc", "ptpxo")))
    except Exception as e:
        print(f"     Porto Santo: {type(e).__name__}: {str(e)[:80]}")
    return pages


# ---------------------------------------------------------------- Iceland / Faroe (Dokk port-call platform)

# Reykjavík and Akureyri come from sched_europe (key rkv); this source takes every other harbour in the same feed.
DOKK_OTHER = {"ISA": "ifj", "ISSEY": "sey", "GRF": "gjr", "FOTOR": "tho"}


def parse_dokk_other(h, today):
    """portal.dokk.is public cruise calendar JSON (same feed as sched_europe.parse_dokk): {"port_locode",
    "port_name", "port_time_zone", "vessel_name", "arrival": "...Z", "departure", "status"}. Ísafjörður,
    Seyðisfjörður, Grundarfjörður and Tórshavn get their ids; the other Icelandic/Faroese harbours are kept by name.
    Times are converted with the port's own time zone (Faroe has summer time, Iceland not)."""
    from zoneinfo import ZoneInfo
    out = []
    for e in json.loads(h):
        code = e.get("port_locode")
        if code in _eu.DOKK_PORTS or not e.get("port_name") or code == "000" \
                or e.get("status") in ("cancelled", "rejected"):
            continue
        try:
            tz = ZoneInfo(e.get("port_time_zone") or "UTC")
        except Exception:
            tz = timezone.utc

        def local(s):
            if not s:
                return None
            t = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return t.astimezone(tz).strftime("%Y-%m-%dT%H:%M")
        a, d = local(e.get("arrival")), local(e.get("departure"))
        p = DOKK_OTHER.get(code)
        if e.get("vessel_name") and (a or d):
            out.append(call(e["vessel_name"], None, p, a, _later(a, d), name=None if p else e["port_name"]))
    return out


# ---------------------------------------------------------------- Belgium

# The Zeebrugge page fills its table in the browser from the port's own Algolia index (public search-only key,
# printed in the site's JavaScript): hits {schipnaam, Rederij, eta_d, ets_d (epoch seconds of the local time,
# shown with timeZone UTC), ...}.
ZEE_ALGOLIA = ("GWKHDNJ7PR", "b6388093d08e5c9d805f187404c1fb6d", "prod_MBZ_CRUISES")


def parse_zeebrugge(h, today):
    """Port of Antwerp-Bruges 'Arrivals and departures of cruises in Zeebruges': the Algolia JSON (see get_zeebrugge),
    or the rendered table (10 per page, ?page=N): Arrival 'dd/mm/yyyy, HH:MM' | Departure | Ship | Shipping company |
    Website | Length | Flag."""
    out = []
    if h.lstrip().startswith("{"):
        def ts(v):
            try:
                return datetime.fromtimestamp(int(float(v)), timezone.utc).strftime("%Y-%m-%dT%H:%M")
            except (TypeError, ValueError, OverflowError, OSError):
                return None
        for hit in json.loads(h).get("hits", []):
            ship = (hit.get("schipnaam") or "").strip()
            a, d = ts(hit.get("eta_d")), ts(hit.get("ets_d"))
            line = re.sub(r"\s*-\s*Hal$", "", (hit.get("Rederij") or "").strip()) or None
            if ship and (a or d):
                out.append(call(ship, line, "zee", a, _later(a, d)))
        return out
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 4:
            continue

        def dt(s):
            m = re.match(r"(\d\d)/(\d\d)/(\d{4}),?\s*(\d{1,2}:\d\d)?", s)
            return (iso(m[3], m[2], m[1], m[4]) if m[4] else iso(m[3], m[2], m[1])) if m else None
        a, d = dt(c[0]), dt(c[1])
        line = re.sub(r"\s*-\s*Hal$", "", c[3]) or None
        if c[2] and (a or d):
            out.append(call(c[2], line, "zee", a, _later(a, d)))
    return out


def get_zeebrugge(url):
    """The served page has no table (it is built in the browser), so read the same Algolia index the page uses,
    1000 hits per page. Falls back to the paged HTML ('Page 1 of N', ?page=N) if that fails."""
    app, key, index = ZEE_ALGOLIA
    try:
        pages, n = [], 0
        while True:
            q = urllib.parse.urlencode({"query": "", "hitsPerPage": 1000, "page": n,
                                        "x-algolia-application-id": app, "x-algolia-api-key": key})
            h = get(f"https://{app}-dsn.algolia.net/1/indexes/{index}?{q}")
            pages.append(h)
            n += 1
            if n >= min(int(json.loads(h).get("nbPages") or 1), 10):
                break
            time.sleep(DELAY)
        if any(json.loads(h).get("hits") for h in pages):
            return pages
        print("     Zeebrugge: Algolia index returned no hits; reading the HTML table")
    except Exception as e:
        print(f"     Zeebrugge Algolia: {type(e).__name__}: {str(e)[:80]}; reading the HTML table")
    pages = [get(url)]
    m = re.search(r"</span>\s*of</span>\s*(\d+)|of</span> (\d+)", pages[0])
    n = int(m[1] or m[2]) if m else 1
    for i in range(2, min(n, 30) + 1):
        time.sleep(DELAY)
        pages.append(get(f"{url}?page={i}"))
    return pages


# ---------------------------------------------------------------- France

def parse_lehavre(h, today):
    """HAROPA PORT | LE HAVRE port community 'Escales croisières' list (havre-port.com/fr/liste/2077, whole year and
    next): Armateur | Consignation | Navire | Lloyd | Nat. | ... | Quai | Jour | PVA 'dd/mm/yyyy HH:MM' | Jour |
    PVD | Provenance | Destination."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 14:
            continue
        ts = [re.fullmatch(r"(\d\d)/(\d\d)/(\d{4}) (\d\d:\d\d)", x) for x in c]
        k = [i for i, m in enumerate(ts) if m]
        if not k:
            continue
        a = iso(ts[k[0]][3], ts[k[0]][2], ts[k[0]][1], ts[k[0]][4])
        d = iso(ts[k[1]][3], ts[k[1]][2], ts[k[1]][1], ts[k[1]][4]) if len(k) > 1 else None
        if c[2] and a:
            out.append(call(c[2], c[0] or None, "lhv", a, _later(a, d)))
    return out


# ---------------------------------------------------------------- Germany

DE_DAYS = {"mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6}


def _first_tokens(c, n=4):
    """pdftotext may put single-space-separated columns ('04.01.26 So 8:00') in one cell: split the first n
    columns on any whitespace, keep the rest of the row's cells as they are."""
    out = []
    for x in c:
        parts = x.split() if len(out) < n else [x]
        if not parts:
            out.append("")
        while parts:
            if len(out) < n:
                out.append(parts.pop(0))
            else:
                out.append(" ".join(parts))
                break
    return out


def parse_kiel(h, today):
    """PORT OF KIEL 'Kreuzfahrerliste' PDF (pdftotext -layout text, or the Markdown table of the same PDF):
    DATE 'dd.mm.yy' | DAY 'So' | ETA '8:00' | ETD '17:00' | SHIP'S NAME | BERTH | QUAY | GT | LOA | ... | FROM | TO.
    Multi-day stays span several rows with '>>' for 'continues': the first row has the ETA and ETD '>>', middle rows
    may show '>>' instead of the date (the weekday still given) and carry the ship name, the last row has ETA '>>' and
    the ETD. Rows of different calls can interleave, so a stay is closed by the next row with an ETD."""
    out, pend, cur, last = [], None, None, ""

    def day_of(c0, wd, base):
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", c0)
        if m:
            y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            try:
                return date(y, int(m[2]), int(m[1]))
            except ValueError:
                return None
        if base and wd[:2].lower() in DE_DAYS:  # '>>' date: the next day with this weekday
            return base + timedelta(days=(DE_DAYS[wd[:2].lower()] - base.weekday()) % 7)
        return base

    def at(d, hm):
        return iso(d.year, d.month, d.day, hm) if d and re.fullmatch(r"\d{1,2}:\d\d", hm or "") else None
    for c in map(_first_tokens, _pac.table_rows(h)):
        if len(c) < 4 or not (re.fullmatch(r"\d{1,2}\.\d{1,2}\.\d{2,4}", c[0]) or c[0] == ">>"):
            continue
        c = c + [""] * 5
        name = c[4] if c[4] and not re.match(r"(>>|LP\b)", c[4]) else ""
        d = day_of(c[0], c[1], pend["day"] if pend and c[0] == ">>" else cur)
        if c[0] != ">>":
            cur = d
        a, e = at(d, c[2]), at(d, c[3])
        if pend and d and c[0] == ">>":
            pend["day"] = d
        if a and e:
            if name:
                out.append(call(name, None, "kel", a, _later(a, e)))
            elif pend:  # leaves and comes back the same day: close the open stay at this ETD, reopen at this ETA
                out.append(call(pend["name"], None, "kel", pend["a"], e))
                pend = {"name": pend["name"], "a": a, "day": d}
        elif a:
            if pend and pend["name"]:
                out.append(call(pend["name"], None, "kel", pend["a"], None))
            prev = (pend["name"] if pend else last) if c[0] == ">>" else ""  # '>> Fr 21:00 >>': same ship back
            pend = {"name": name or prev, "a": a, "day": d}
        elif e:
            if pend and (not name or not pend["name"] or name.lower() == pend["name"].lower()):
                n = pend["name"] or name
                if n:
                    out.append(call(n, None, "kel", pend["a"], _later(pend["a"], e)))
                pend, last = None, n
            elif name:
                out.append(call(name, None, "kel", None, e))
        elif pend and name and not pend["name"]:
            pend["name"] = name
    if pend and pend["name"]:
        out.append(call(pend["name"], None, "kel", pend["a"], None))
    return out


def get_kiel(url):
    return [_pac.pdf_text(_pac.get_bytes(url))]


# ---------------------------------------------------------------- Netherlands

def get_amsterdam(url):
    """Cruise Port Amsterdam calendar, one page per year (/cruise-calendar/2026, /2027; parser
    sched_europe.parse_amsterdam). The plain GET came back without ship cards on the daily run, so a page without
    'ship-title' is rendered in headless Chrome instead."""
    pages = []
    for y in (date.today().year, date.today().year + 1):
        u = f"{url.rstrip('/')}/{y}"
        h = get(u)
        if "ship-title" not in h:
            h = render(u, "p.ship-title")
        pages.append(f"<!-- gangway-year:{y} -->" + h)  # the served page may lack the active-year button
        time.sleep(DELAY)
    return pages


def parse_azores(h, today):
    """Portos dos Açores 'Cruzeiros' tab (Ponta Delgada preselected):
    IMO | Navio | Tipo | Pax | Trip | Origem | Destino | ETA | ETD ('YYYY-MM-DD HH:MM', local)."""
    i = h.find("table_cruzeiros")
    j = h.find("</table>", i)
    if i < 0:
        return []
    out = []
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", h[i:j]):
        c = cells(row)
        if len(c) < 9 or "cruz" not in c[2].lower():
            continue
        a, d = (re.match(r"(\d{4})-(\d\d)-(\d\d) (\d\d:\d\d)", x) for x in (c[7], c[8]))
        if not a:
            continue
        a = iso(int(a[1]), int(a[2]), int(a[3]), a[4])
        d = iso(int(d[1]), int(d[2]), int(d[3]), d[4]) if d else None
        out.append(call(c[1], None, "pdl", a, _later(a, d)))
    return out


SOURCES = [
    {"key": "sou", "name": "Southampton", "url": "https://www.southamptonvts.co.uk/xml/sotcruiseship.xml",
     "parse": parse_southampton_xml},
    {"key": "dvr", "name": "Dover", "url": "https://www.portofdover.com/cruise/schedule-tickets/", "parse": parse_dover},
    {"key": "cph", "name": "Copenhagen + Visby + Malmö", "url": "https://www.cmport.com/terminals/ships-in-port/",
     "parse": parse_cmp_all, "fetch": get_cmp},
    {"key": "ams", "name": "Amsterdam", "url": "https://sea.cruiseportamsterdam.com/cruise-calendar/",
     "parse": _eu.parse_amsterdam, "fetch": get_amsterdam},
    {"key": "rtm", "name": "Rotterdam", "url": "https://www.cruiseportrotterdam.nl/cruise-calls/", "parse": parse_rotterdam,
     "fetch": get_rotterdam},
    {"key": "svg", "name": "Stavanger",
     "url": "https://www.stavangerhavn.com/EntityList/Calendar/11edb967-d955-498e-a354-7c6a96bd089f/"
            "5605d242-d639-ef11-8409-6045bdf3b319/a1c61573-79f0-4441-8a01-925a4621fc77",
     "parse": parse_powerpages_calendar("svg"), "fetch": get_powerpages_calendar},
    {"key": "tos", "name": "Tromsø", "url": "https://tromso.havn.no/en/traffic/cruise-calls/", "parse": parse_tromso},
    {"key": "krs", "name": "Kristiansand + Mandal", "url": "https://en.portofkristiansand.no/maritimt-og-trafikk/cruise",
     "parse": portcall_parser("krs", {"Mandal": "Mandal"})},
    {"key": "fnc", "name": "Funchal + Porto Santo", "url": "https://apram.pt/reserva-cais?port=ptfnc", "parse": parse_apram,
     "fetch": get_apram},
    {"key": "spc", "name": "La Palma, La Gomera, El Hierro", "url": "https://www.puertosdetenerife.org/cruceros-previstos/",
     "parse": parse_tenerife_islands},
    {"key": "ifj", "name": "Iceland & Faroe harbours (Dokk)", "url": "https://portal.dokk.is/embed/calendar",
     "parse": parse_dokk_other, "fetch": _eu.get_dokk},
    {"key": "flm", "name": "Flåm", "url": "https://api.flamport.no/Open/index.php", "parse": parse_flam},  # data of flamport.no/arrival-list
    {"key": "zee", "name": "Zeebrugge",
     "url": "https://www.portofantwerpbruges.com/en/shipping/cruises/arrivals-and-departures-cruises-zeebruges",
     "parse": parse_zeebrugge, "fetch": get_zeebrugge},
    {"key": "lhv", "name": "Le Havre", "url": "https://www.havre-port.com/fr/liste/2077/escales-croisieres",
     "parse": parse_lehavre},
    {"key": "kel", "name": "Kiel", "url": "https://www.portofkiel.com/files/pok/Downloads/Kreuzfahrerlisten/Kreuzfahrtliste.pdf",
     "parse": parse_kiel, "fetch": get_kiel},
    {"key": "pdl", "name": "Ponta Delgada", "url": "https://portosdosacores.pt/movimento-portuario/",
     "parse": parse_azores},
]
