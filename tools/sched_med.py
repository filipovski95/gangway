"""Official cruise schedules for Mediterranean ports (port authorities / terminal operators / port service
companies only, no aggregators).

Each parser: (html, today) -> list of call() dicts, like the parsers in port_schedules.py.
Plug in with:  from sched_med import SOURCES as MED;  SOURCES += MED
"""
import html as htmllib
import json
import re
import time
import urllib.parse
from datetime import date, datetime, timedelta

from port_schedules import text, cells, iso, call, get, render, DELAY, WINDOW_AHEAD, MONTHS
import port_schedules as _ps
from sched_pacific import pdf_link_fetch  # PDF -> `pdftotext -layout` text

IT_MONTHS = {m: i + 1 for i, m in enumerate(
    ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre",
     "novembre", "dicembre"])}
EN_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
             "november", "december"]


def _next_day_if_before(a, d):
    """Departure given only as a time on the arrival date: an earlier time means it leaves the next day."""
    if a and d and d < a:
        return (datetime.fromisoformat(d) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    return d


def _dmy(s, hm=None):
    m = re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", s or "")
    return iso(m[3], m[2], m[1], hm) if m else None


def _ots(name):
    """Port clerks' shorthand: 'LEGEND OTS' -> 'LEGEND OF THE SEAS'."""
    return re.sub(r"\s+OTS$", " OF THE SEAS", name.strip(), flags=re.I)


def _cols(line):
    """A table row as cells: a Markdown row ('| a | b |') or a `pdftotext -layout` line (cells = runs of 2+ spaces)."""
    line = line.strip()
    if line.startswith("|"):
        return [c.strip() for c in line.strip("|").split("|")]
    return [c.strip() for c in re.split(r"\s{2,}", line)]


def _hm(s):
    m = re.fullmatch(r"(\d{1,2})[:.](\d\d)", (s or "").strip())
    return f"{int(m[1]):02d}:{m[2]}" if m else None


def merge_overnight(rows, port, name=None):
    """rows: (ship, line, a, d, d_open). A stay over midnight is written as one row per day: '07:00 | 00:00' then
    '00:00 | 17:00' the next day (d_open = departure written as 00:00). Join those into one call."""
    out, open_ = [], {}
    for ship, line, a, d, d_open in sorted(rows, key=lambda r: (r[2] or r[3] or "")):
        prev = open_.pop(ship.upper(), None)
        if prev is not None and a and a[11:] <= "00:01" and a[:10] > prev["a"][:10]:
            prev["d"] = None if d_open else d
            if d_open:
                open_[ship.upper()] = prev
            continue
        c = call(ship, line, port, a, None if d_open else d, name=name)
        out.append(c)
        if d_open and a:
            open_[ship.upper()] = c
    return out


# ---------------------------------------------------------------- Italy

def parse_ravenna(h, today):
    """rccp.it (Ravenna Civitas Cruise Port, terminal operator) 'BERTHING-RESERVATION-YYYY' PDF (as `pdftotext -layout`
    text or a Markdown table): DATE dd/mm/yyyy | DAY | ETB | ETD | Ship | T/H | TRAN | DIS | EMB | CL (line) | PA (agent).
    An overnight stay is two rows: 'ETB | ---' then '--- | ETD' the next day."""
    rows = []
    for line in h.splitlines():
        c = _cols(line)
        k = next((i for i, x in enumerate(c) if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", x)), None)
        if k is None or len(c) < k + 5:
            continue
        ta, td, ship = _hm(c[k + 2]), _hm(c[k + 3]), c[k + 4]
        a = _dmy(c[k], ta) if ta else None
        d = _next_day_if_before(a, _dmy(c[k], td)) if td else None
        line_ = c[k + 9] if len(c) > k + 9 and not c[k + 9].isdigit() else None
        if ship and (a or d):
            rows.append((ship, line_, a or _dmy(c[k]), d, not td))
    return merge_overnight(rows, "rav")


def parse_trieste(h, today):
    """triesteterminal.it 'CALENDARIO-NAVI-YYYY.pdf' (as `pdftotext -layout` text or a Markdown table):
    NAVE | DATA 'giovedì 12 febbraio 2026' | ARRIVO 'H:MM' | PARTENZA | OPERAZIONI | COMPAGNIA. Times may be
    'tba'/'tbc'/empty; an overnight stay is split per day with 00:00 as the break."""
    rows = []
    for line in h.splitlines():
        c = _cols(line)
        k = next((i for i, x in enumerate(c) if re.search(r"\b\d{1,2}\s+[a-z]+\s+\d{4}\b", x, re.I)), None)
        if not k:
            continue
        m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", c[k], re.I)
        mo = IT_MONTHS.get(m[2].lower())
        if not mo:
            continue
        ta, td = _hm(c[k + 1] if len(c) > k + 1 else ""), _hm(c[k + 2] if len(c) > k + 2 else "")
        a = iso(m[3], mo, m[1], ta) if ta else iso(m[3], mo, m[1])
        d = iso(m[3], mo, m[1], td) if td else None
        d_open = td == "00:00"
        line_ = c[-1] if len(c) > k + 4 and not re.fullmatch(r"(partial )?TA|transit|", c[-1], re.I) else None
        if d and a and d < a and not d_open:
            d = _next_day_if_before(a, d)
        rows.append((c[0], line_, a, d, d_open))
    return merge_overnight(rows, "trs")


def parse_civitavecchia(h, today):
    """civitavecchia.portmobility.it (Port Mobility, the port authority's port-services company) monthly page
    'Cruises: October 2026': heading '<Month> YYYY: Cruise Schedule ...', one table: weekday | day | month number |
    arrival 'HH:MM' | departure | SHIP | dock. A departure earlier than the arrival is the next morning."""
    m = re.search(r"(" + "|".join(EN_MONTHS) + r")\s+(\d{4})\s*:?\s*Cruise", text(h), re.I)
    if not m:
        return []
    year, hmon = int(m[2]), EN_MONTHS.index(m[1].lower()) + 1
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 6 or not (c[1].isdigit() and c[2].isdigit()):
            continue
        mo = int(c[2])
        y = year + (1 if mo < hmon - 6 else 0)
        a = iso(y, mo, c[1], c[3] or None)
        d = _next_day_if_before(a, iso(y, mo, c[1], c[4] or None))
        if c[5] and (a or d):
            out.append(call(_ots(c[5]), None, "civ", a, d))
    return out


def get_civitavecchia(url):
    """One page per month ('...-october'); this month and the next two (a month not published yet is skipped)."""
    pages, t = [], date.today().replace(day=1)
    for i in range(3):
        mo = (t.month - 1 + i) % 12
        try:
            pages.append(get(url.format(month=EN_MONTHS[mo])))
        except Exception as e:
            print(f"     Civitavecchia {EN_MONTHS[mo]}: {type(e).__name__}: {str(e)[:80]}")
        time.sleep(10)  # robots.txt asks for 10 s between requests
    return pages


def parse_spezia(h, today):
    """speziacarrara.cruises (Spezia & Carrara Cruise Terminal) Ninja Tables JSON (see get_spezia), one table per
    port: [{"value": {"month", "date": "dd/mm/yyyy", "day", "ship", "timeofarrival": "7.00", "timeofdeparture"}}].
    get_spezia puts 'PORT=<table title>' on the first line; La Spezia is 'spz', Carrara and Lerici are named."""
    m = re.match(r"PORT=([^\n]*)\n", h)
    title = (m[1] if m else "LA SPEZIA").upper()
    port, name = ("spz", None) if "SPEZIA" in title else (None, "Carrara" if "CARRARA" in title else "Lerici")
    i, j = h.find("["), h.rfind("]")
    rows = []
    for r in (json.loads(h[i:j + 1]) if 0 <= i < j else []):
        v = r.get("value", {}) if isinstance(r, dict) else {}
        ship = _ots(text(v.get("ship", "")))
        ta, td = (v.get("timeofarrival") or "").strip(), (v.get("timeofdeparture") or "").strip()
        a = _dmy(v.get("date"), ta) if ta else None
        d = _next_day_if_before(a, _dmy(v.get("date"), td)) if td else None
        if ship and (a or d) and not re.search(r"cancel|annull", ship, re.I):
            rows.append([ship, a or _dmy(v.get("date")), d, bool(a)])
    # an overnight stay is two rows: arrival only on day 1, departure only on day 2
    rows.sort(key=lambda r: (r[0], r[1]))
    out = []
    for k, (ship, a, d, has_a) in enumerate(rows):
        if not has_a and k and rows[k - 1][0] == ship and rows[k - 1][2] is None and out:
            out[-1]["d"] = d
            continue
        out.append(call(ship, None, port, a, d, name=name))
    return out


def get_spezia(url):
    """The calendar page holds one Ninja Tables table per port, each loaded by the browser from its
    'data_request_url' (admin-ajax, with a public nonce printed in the page). Fetch every table's JSON.
    A page served from a stale cache carries an expired nonce and the table request then fails (HTTP 400), so on
    failure the page is fetched once more with a cache-busting query for a fresh nonce."""
    def tables(page):
        titles = re.findall(r"""aria-label=["']?([^"'>]*CALENDARIO[^"'>]*)""", page)
        ids = re.findall(r"""data-footable_id=["']?(\d+)""", page)
        by_id = dict(zip(ids, titles))
        out = []
        for u in dict.fromkeys(re.findall(r'"data_request_url":"([^"]+)"', page)):
            u = htmllib.unescape(u.replace("\\/", "/").replace("\\u0026", "&"))
            tid = re.search(r"table_id=(\d+)", u)
            time.sleep(DELAY)
            out.append(f"PORT={by_id.get(tid[1] if tid else '', '')}\n" + get(u))
        if not out:
            raise RuntimeError("no Ninja Tables data_request_url in the page")
        return out

    fresh = f"{url}{'&' if '?' in url else '?'}nocache={int(time.time())}"
    try:
        return tables(get(url))
    except Exception as e:
        print(f"     La Spezia: {type(e).__name__}: {str(e)[:80]}; retrying with a fresh page")
        time.sleep(DELAY)
        return tables(get(fresh))


# ferry operators that share the passenger terminals with cruise ships
FERRY_LINES = r"g\.?n\.?v|tirrenia|moby|co\.?tu\.?nav|grimaldi|corsica|algerie|ctn|minoan|anek|superfast|blue star|" \
              r"jadrolinija|snav|caronte|siremar|liberty lines|gnv|baleari|trasmed|fred\.? olsen|naviera armas|la meridionale"


def parse_genoa(h, today):
    """smge.it (Stazioni Marittime, Genoa passenger terminal operator) 'previsioni.html': per day a row
    '17 Ottobre 2026 Sabato', an ARRIVI table (NAVE | PROVENIENZA | COMPAGNIA | ORARIO 'HH.MM') and a PARTENZE
    table (NAVE | DESTINAZIONE | COMPAGNIA | ORARIO). Covers today and the next couple of days; ferries are
    skipped, arrivals and departures paired per ship."""
    events, day, kind = [], None, None
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S | re.I):
        c = [text(x) for x in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", row, re.S | re.I)]
        c = [x for x in c if x]
        if not c:
            continue
        m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", c[0])
        if m and IT_MONTHS.get(m[2].lower()):
            day = (m[3], IT_MONTHS[m[2].lower()], m[1])
            continue
        if c[0].upper() in ("ARRIVI", "PARTENZE"):
            kind = "A" if c[0].upper() == "ARRIVI" else "D"
            continue
        if not day or not kind or len(c) < 4 or c[0].upper() == "NAVE" or re.search(FERRY_LINES, c[2], re.I):
            continue
        t = iso(*day, c[3])
        if t:
            events.append((c[0], c[2] or None, kind, t))
    return _ps.pair_moves(events, "goa", max_days=3)


# ---------------------------------------------------------------- Italy: Coast Guard National Maritime Single Window

def _utc_to_rome(s):
    """'2026-10-20T16:30:00Z' -> Italian local time (CET, EU summer time)."""
    t = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")

    def last_sunday(y, mo):
        d = date(y, mo, 31)
        return datetime(y, mo, d.day - (d.weekday() + 1) % 7, 1)
    summer = last_sunday(t.year, 3) <= t < last_sunday(t.year, 10)
    return (t + timedelta(hours=1 + summer)).strftime("%Y-%m-%dT%H:%M")


# UN/LOCODE -> guide port id (None: not in the guide, the call is kept with the port's name)
MNSW_PORTS = {"ITNAP": ("nap", None), "ITLIV": ("liv", None), "ITMSN": ("mss", None), "ITPMO": ("pmo", None),
              "ITSAL": ("sal", None), "ITOLB": ("olb", None), "ITVCE": ("vce", None), "ITBDS": ("bds", None),
              "ITBRI": (None, "Bari"), "ITAOI": (None, "Ancona"), "ITCTA": (None, "Catania"),
              "ITTPS": (None, "Trapani"), "ITPTO": (None, "Porto Torres"),
              "ITTAR": (None, "Taranto"), "ITSVN": (None, "Savona")}
MNSW_API = "https://www.mnsw.gov.it/arrivals_departures-api/v1/"


def parse_mnsw(h, today):
    """mnsw.gov.it (Italian Coast Guard 'Arrivi e Partenze porti italiani', public REST API, see get_mnsw): a JSON list
    of API pages {"content": [{"visitId", "arrivalPort"|"departurePort" (UN/LOCODE), "ship": {"name", "statCode5"},
    "eta"|"etd": UTC ISO, "status"}]}. Cruise ships only (StatCode5 A37A = passenger/cruise; ferries are A36);
    arrival and departure are paired by visitId."""
    i, j = h.find("["), h.rfind("]")
    pages = json.loads(h[i:j + 1]) if 0 <= i < j else []
    visits = {}
    for pg in pages if isinstance(pages, list) else [pages]:
        for v in (pg.get("content") or []) if isinstance(pg, dict) else []:
            ship = v.get("ship") or {}
            if not str(ship.get("statCode5", "")).startswith("A37A") or str(v.get("status", "")).upper() == "CANCELLED":
                continue
            port = v.get("arrivalPort") or v.get("departurePort")
            if port not in MNSW_PORTS:
                continue
            r = visits.setdefault(v.get("visitId") or (port, ship.get("name"), v.get("eta") or v.get("etd")),
                                  {"port": port, "name": ship.get("name"), "a": None, "d": None})
            if v.get("eta"):
                r["a"] = _utc_to_rome(v["eta"])
            if v.get("etd"):
                r["d"] = _utc_to_rome(v["etd"])
    out = []
    for r in visits.values():
        pid, pname = MNSW_PORTS[r["port"]]
        if r["name"] and (r["a"] or r["d"]) and not (r["a"] and r["d"] and r["d"] < r["a"]):
            out.append(call(r["name"], None, pid, r["a"], r["d"], name=pname))
    return out


def get_mnsw(url):
    """The API serves only a few days around today (a later date answers 400): for each port, arrivals and
    departures of passenger ships from yesterday until the API stops answering (at most a week)."""
    pages = []
    t = date.today()
    for code in MNSW_PORTS:
        for kind, key in (("arrivals", "arrivalPort"), ("departures", "departurePort")):
            for k in range(-1, 7):
                day = (t + timedelta(days=k)).isoformat()
                time.sleep(DELAY / 2)
                try:
                    pages.append(json.loads(get(f"{MNSW_API}{kind}?{key}={code}&startDate={day}&shipType=PASSENGER")))
                except Exception:
                    if k > 0:  # beyond the published window
                        break
    return [json.dumps(pages)]


# ---------------------------------------------------------------- Croatia (replaces sched_europe 'spu')

def parse_split_json(h, today):
    """portsplit.hr '/api/plan-posjeta.json[?godina=YYYY]' (the JSON the 'Plan posjeta brodova' page renders in the
    browser; the HTML itself has an empty table): {"godina", "godine": [years], "posjeti": [{"brod", "arr":
    "YYYY-MM-DD", "dep": "YYYY-MM-DD"|null, "time": ["HH:MM", "HH:MM"], "agent", ...}]}."""
    i, j = h.find("{"), h.rfind("}")
    data = json.loads(h[i:j + 1]) if 0 <= i < j else {}
    out = []
    for v in data.get("posjeti") or []:
        m = re.match(r"(\d{4})-(\d\d)-(\d\d)", v.get("arr") or "")
        if not m or not v.get("brod") or re.search(r"otkaz|cancel", str(v.get("status", "")), re.I):
            continue
        t = [x for x in (v.get("time") or []) if x and _hm(x)]
        a = iso(m[1], m[2], m[3], _hm(t[0])) if t else iso(m[1], m[2], m[3])
        d = None
        if len(t) > 1:
            dm = re.match(r"(\d{4})-(\d\d)-(\d\d)", v.get("dep") or "") or m
            d = _next_day_if_before(a, iso(dm[1], dm[2], dm[3], _hm(t[1])))
        out.append(call(v["brod"], None, "spu", a, d))
    return out


def get_split_json(url):
    """This season's JSON, plus next year's once it is listed in 'godine'."""
    first = get(url)
    pages = [first]
    try:
        years = json.loads(first).get("godine") or []
        for y in years:
            if int(y) > date.today().year:
                time.sleep(DELAY)
                pages.append(get(f"{url}?godina={y}"))
    except Exception as e:
        print(f"     Split next season: {type(e).__name__}: {str(e)[:80]}")
    return pages


# ---------------------------------------------------------------- Spain

def parse_valencia(h, today):
    """valenciaport.com 'Previsión de Cruceros para YYYY' PDFs (as `pdftotext -layout` text or a Markdown table):
    FECHA DE LLEGADA 'sábado, 02/01/27' (blank = same day as the row above) | CRUCERO | Nº IMO | ESLORA | CALADO |
    HORA DE LLEGADA | HORA DE SALIDA | FECHA DE SALIDA ('.' = same day, else dd/mm/yyyy) | CONSIGNATARIO | Total.
    Rows are found by the IMO column (7 digits, or 'En construcción' for a new ship)."""
    out, day = [], None
    for line in h.splitlines():
        c = [x for x in _cols(line)]
        k = next((i for i, x in enumerate(c) if re.fullmatch(r"\d{7}|En construcci\S*", x)), None)
        if not k:
            continue
        # pdftotext can leave one space between the date and the ship ('jueves, 01/01/26 MSC MAGNIFICA')
        m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})\b", " ".join(c[:k]))
        if m:
            y = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
            day = (y, int(m[2]), int(m[1]))
        ship = re.sub(r"^.*\b\d{1,2}/\d{1,2}/\d{2,4}\s*", "", c[k - 1]).strip()
        if not day or not ship or ship.isdigit():
            continue
        rest = c[k + 1:]
        times = [_hm(x) for x in rest if _hm(x)]
        a = iso(*day, times[0]) if times else iso(*day)
        d = iso(*day, times[1]) if len(times) > 1 else None
        dd = next((x for x in rest if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", x)), None)
        if dd and len(times) > 1:
            d = _dmy(dd, times[1])
        out.append(call(ship, None, "vlc", a, _next_day_if_before(a, d)))
    return out


# ---------------------------------------------------------------- France

def parse_marseille(h, today):
    """marseille-cruise.com (Association Marseille Provence Croisière, the port's cruise club) public planning, a
    wpDataTables table (next ~2 weeks): Date d'arrivée dd/mm/yyyy | ETA | ETD | Navire | Compagnie | Observation
    ('OVERNIGHT - Départ le 31/10') | Terminal | Capacité | Type | Statut."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S):
        c = [text(x) for x in cells(row)]
        if len(c) < 10 or not re.match(r"\d{1,2}/\d{1,2}/\d{4}", c[0]) or re.search(r"annul|cancel", c[9], re.I):
            continue
        a = _dmy(c[0], c[1] or None) or _dmy(c[0])
        d = _dmy(c[0], c[2]) if c[2] else None
        m = re.search(r"d[ée]part\s+le\s+(\d{1,2})/(\d{1,2})", c[5], re.I)
        if m and c[2]:
            y = int(c[0][-4:]) + (1 if int(m[2]) < int(c[0][3:5]) else 0)
            d = iso(y, m[2], m[1], c[2])
        d = _next_day_if_before(a, d)
        if c[3]:
            out.append(call(c[3], c[4] or None, "mrs", a, d))
    return out


def get_cadiz_list(url):
    """Same as sched_europe.get_cadiz but returns the list of pages (fetch_all iterates the result;
    the original joins them into one string, which is why cad parsed 0 calls on the live run)."""
    import sched_europe
    from datetime import date as _date
    pages = [get(url)]
    t = _date.today()
    y, m = t.year, t.month
    for _ in range(WINDOW_AHEAD // 30 + 1):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        time.sleep(DELAY)
        try:
            pages.append(get("https://www.puertocadiz.com/wp-admin/admin-ajax.php",
                             {"action": "apbc_cruceros_search", "apbcAnyo": ny, "apbcMes": nm,
                              "apbcAnyoOld": y, "apbcMesOld": m}))
            if 'colspan="11"' not in pages[-1] and ny > t.year:
                break
        except Exception:
            pass
        y, m = ny, nm
    return pages


def parse_cadiz(h, today=None):
    import sched_europe
    return sched_europe.parse_cadiz(h, today)


SOURCES = [
    {"key": "civ", "name": "Rome (Civitavecchia)", "url": "https://civitavecchia.portmobility.it/en/cruises-port-civitavecchia-{month}",
     "parse": parse_civitavecchia, "fetch": get_civitavecchia},
    {"key": "spz", "name": "La Spezia + Carrara + Lerici", "url": "https://speziacarrara.cruises/calendario-crociere/",
     "parse": parse_spezia, "fetch": get_spezia},
    {"key": "trs", "name": "Trieste", "url": "https://www.triesteterminal.it/",
     "parse": parse_trieste, "fetch": pdf_link_fetch("https://www.triesteterminal.it/", r"CALENDARIO-NAVI", every=True)},
    {"key": "rav", "name": "Ravenna", "url": "https://rccp.it/calendario-scali/",
     "parse": parse_ravenna, "fetch": pdf_link_fetch("https://rccp.it/calendario-scali/", r"BERTHING|calendar|scali")},
    {"key": "vlc", "name": "Valencia", "url": "https://www.valenciaport.com/negocio/cruceros/", "parse": parse_valencia,
     "fetch": pdf_link_fetch("https://www.valenciaport.com/negocio/cruceros/", r"prevision-de-cruceros", every=True)},
    {"key": "nap", "name": "Italian ports (Coast Guard MNSW): Naples, Livorno, Messina, Palermo, Salerno, Olbia, Venice, Brindisi...",
     "url": "https://www.mnsw.gov.it/arrivals_departures/tables", "parse": parse_mnsw, "fetch": get_mnsw},
    {"key": "spu", "name": "Split", "url": "https://portsplit.hr/api/plan-posjeta.json", "parse": parse_split_json,
     "fetch": get_split_json},
    {"key": "mrs", "name": "Marseille", "url": "https://marseille-cruise.com/escales-maritimes-planning/", "parse": parse_marseille},
    {"key": "cad", "name": "Cádiz", "url": "https://www.puertocadiz.com/el-puerto/instalaciones-para-traficos-especificos/cruceros-y-trafico-de-pasajeros/",
     "parse": parse_cadiz, "fetch": get_cadiz_list},
    {"key": "goa", "name": "Genoa (Stazioni Marittime)", "url": "https://www.smge.it/assets/files/previsioni.html", "parse": parse_genoa},
]
