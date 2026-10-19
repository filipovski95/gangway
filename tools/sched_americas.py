"""Official cruise schedules for Mexico (Pacific), US West Coast extras, Alaska extras, Central America and
South America (see port_schedules.py for conventions).

Parsers: (html_or_text, today) -> [call(...)]. PDF sources are read with poppler `pdftotext -layout` (via
sched_pacific.pdf_text); their saved samples are the same tables as Markdown, which table_rows() reads too.
"""
import re
import time
import urllib.parse
from datetime import date, datetime, timedelta

from port_schedules import text, cells, iso, call, get, render, DELAY, WINDOW_AHEAD, MONTHS
from sched_pacific import (DAYS, MONTH_NAMES, claa_parser, claa_fetch, get_bytes, pdf_text, table_rows,
                           pdf_link_fetch)

MESES = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8, "sep": 9, "set": 9,
         "oct": 10, "nov": 11, "dic": 12}
# Spelling slips seen in the published lists (typed by hand), and short forms -> the ship's real name.
TYPOS = {
    "sappire princess": "Sapphire Princess", "crown princes": "Crown Princess", "silver down": "Silver Dawn",
    "niew amsterdam": "Nieuw Amsterdam", "nieuw ansterdam": "Nieuw Amsterdam", "clud med ii": "Club Med 2",
    "club med ii": "Club Med 2", "hebrideam sky": "Hebridean Sky", "jorney azamara": "Azamara Journey",
    "symphony": "Crystal Symphony", "mv europa": "Europa", "ms europa": "Europa", "aida bella": "AIDAbella",
    "esmerald princess": "Emerald Princess", "gran princess": "Grand Princess", "sylvia earl": "Sylvia Earle",
    "rci navigator": "Navigator of the Seas", "rci brillance": "Brilliance of the Seas",
    "rci quantum": "Quantum of the Seas", "rci radiance": "Radiance of the Seas", "ms world": "The World",
    "mcc splendida": "MSC Splendida", "l' austral": "Le Austral", "fridtof nansen": "Fridtjof Nansen",
    "nat. geo. explorer": "National Geographic Explorer", "nat geo venture": "National Geographic Venture",
    "nat geo quest": "National Geographic Quest",
}


def fix_name(n):
    n = re.sub(r"\s*\((?:KO|[A-Z]{2})\)$", "", re.sub(r"\s+", " ", n or "").strip(" *"))  # 'KONINGSDAM (KO)'
    return TYPOS.get(n.lower(), n)


def month_no(s):
    s = (s or "").strip().lower()[:3]
    return MONTHS.get(s) or MESES.get(s) or {"jna": 1}.get(s)  # 'Jnauary' (sic) on the Catalina page


def _next_day_if_before(a, d):
    """Same-day times where departure < arrival mean the ship leaves after midnight."""
    if a and d and d <= a:
        d = (datetime.fromisoformat(d) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    return d


def join_overnights(out, days=4):
    """Lists that give a multi-day stay as one row per day ('ETD: ON' / blank, next row 'ETA: ON' / blank): merge
    a call with no departure into the same ship's next call (same port) within a few days that has no arrival."""
    out = sorted(out, key=lambda c: (c["raw"].lower(), c["p"] or c["n"] or "", (c["a"] or c["d"] or "")))
    res = []
    for c in out:
        prev = res[-1] if res else None
        if prev and prev["raw"].lower() == c["raw"].lower() and (prev["p"], prev["n"]) == (c["p"], c["n"]) \
                and prev["d"] is None and (c["a"] is None or c["a"].endswith("T00:00")) and c["d"] \
                and prev["a"] and (datetime.fromisoformat(c["d"]) - datetime.fromisoformat(prev["a"])).days <= days:
            prev["d"] = c["d"]
            continue
        if prev and prev["raw"].lower() == c["raw"].lower() and prev["d"] is None and prev["a"] is None:
            res.pop()  # a stray middle day ('ON | ON') whose stay was already merged
        res.append(dict(c))
    return [c for c in res if c["a"] or c["d"]]


# ---------------------------------------------------------------- Mexico

def parse_puertochiapas(h, today):
    """puertochiapas.com (ASIPONA Puerto Chiapas) '<year>_calendario_crucero.pdf': title 'ARRIBOS 2026', then
    month headings and rows # | BUQUE | NAVIERA | AGENTE | MUNICIPIO | ... | FECHA '2-Jan' / '15-feb' | ETA | ETD |
    TRB | ... (a few rows lack the running number, so the ship is the first non-number cell)."""
    m = re.search(r"ARRIBOS\s+(\d{4})", h)
    if not m:
        return []
    year, out = int(m[1]), []
    for c in table_rows(h):
        i = next((k for k, x in enumerate(c) if re.fullmatch(r"\d{1,2}-[A-Za-z]{3}\.?", x)), None)
        if i is None or i + 2 >= len(c):
            continue
        dd, mon = c[i].split("-")
        mo = month_no(mon)
        name = next((x for x in c[:i] if x and not x.isdigit()), "")
        if not mo or not name or re.search(r"SIN PROGRAMACI", name, re.I):
            continue
        line = c[c.index(name) + 1] if c.index(name) + 1 < i else None
        a = iso(year, mo, dd, c[i + 1])
        d = _next_day_if_before(a, iso(year, mo, dd, c[i + 2]))
        if a:
            out.append(call(fix_name(name), line, "tap", a, d))
    return out


def get_puertochiapas(url):
    """One PDF per calendar year at a fixed path: this year's and next year's (when published)."""
    out = []
    for y in (date.today().year, date.today().year + 1):
        try:
            out.append(pdf_text(get_bytes(url.format(year=y))))
        except Exception as e:
            print(f"     Puerto Chiapas {y}: {type(e).__name__}: {str(e)[:100]}")
        time.sleep(DELAY)
    return out


def parse_topolobampo(h, today):
    """puertotopolobampo.com.mx (ASIPONA Topolobampo) 'Programación de arribos' (server-rendered, the whole
    programme ahead): one table, cruise ships under the 'CRUCEROS - CRUISES' heading, cells BUQUE | TIPO 'CRUCERO' |
    ESLORA | BANDERA | TRÁFICO | ETA date 'dd/mm/yyyy' | ETA hour | ... The hours are placeholders (02:30 /
    04:00-23:00 on every row), so calls are dated only."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S | re.I):
        c = [text(x) for x in cells(row)]
        if len(c) < 6 or c[1].upper() != "CRUCERO":
            continue
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", c[5])
        if m and c[0]:
            out.append(call(fix_name(c[0]), None, None, iso(m[3], m[2], m[1]), None, name="Topolobampo"))
    return out


# ---------------------------------------------------------------- US West Coast

def parse_santabarbara(h, today):
    """santabarbaraca.gov (City of Santa Barbara Waterfront Department) '2026 Cruise Ship Schedule': table
    No. | Date 'MM/DD/YYYY' | Ship | Arrival & Departure '7:00 AM - 4:30 PM' | Passenger Capacity."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S | re.I):
        c = [text(x) for x in cells(row)]
        if len(c) < 4:
            continue
        m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", c[1])
        t = re.findall(r"\d{1,2}:\d\d\s*[AP]\.?M\.?", c[3], re.I)
        if not m or not c[2]:
            continue
        a = iso(m[3], m[1], m[2], t[0]) if t else iso(m[3], m[1], m[2])
        d = _next_day_if_before(a, iso(m[3], m[1], m[2], t[1])) if len(t) > 1 else None
        out.append(call(fix_name(c[2]), None, "sbq", a, d))
    return out


def parse_catalina(h, today):
    """lovecatalina.com (Catalina Island Tourism Authority) cruise ship schedule: one line per call under month
    headings, 'Monday, January 5, 2026 / Carnival Firenze (4232-5260 pax) / 8:00 / 17:30' (separators and times
    vary; some lines have no times). Cancelled calls are struck through (<s>...</s>) and skipped."""
    body = re.sub(r"<s>.*?</s>", "\n", h, flags=re.S | re.I)
    out = []
    for ln in re.split(r"<br\s*/?>|</p>|</h\d>|\n", body, flags=re.I):
        ln = text(ln)
        m = re.match(rf"{DAYS},\s+([A-Za-z]+)\s+(\d{{1,2}}),\s+(\d{{4}})\s*/?\s*(.+)$", ln)
        if not m or not month_no(m[1]) or re.search(r"cancel", ln, re.I):
            continue
        rest = m[4]
        name = re.split(r"\(|/|\s{2,}|\d{1,2}:\d\d", rest)[0].strip(" /")
        name = re.sub(r"\s+INAUGURAL$", "", name, flags=re.I)
        t = re.findall(r"\b\d{1,2}:\d\d\b", rest)
        y, mo, dd = m[3], month_no(m[1]), m[2]
        a = iso(y, mo, dd, t[0]) if t else iso(y, mo, dd)
        d = _next_day_if_before(a, iso(y, mo, dd, t[1])) if len(t) > 1 else None
        if name and a:
            out.append(call(fix_name(re.sub(r"^Virgin\s+", "", name)), None, "avl", a, d))
    return out


# ---------------------------------------------------------------- Costa Rica

def parse_incop(port, name=None):
    """incop.go.cr (INCOP, Costa Rica's Pacific port authority) 'LISTA DE CRUCEROS TEMPORADA 2026-2027' PDFs, one
    per port: TEMPORADA | NOMBRE DEL CRUCERO | LÍNEA | ESLORA | TRB | AGENTE | FECHA LLEGADA 'dd/mm/yyyy' | ETA |
    ETD | BASE. Overnight stays are one row per day with 'ON' for the missing arrival/departure."""
    def parse(h, today):
        out = []
        for c in table_rows(h):
            i = next((k for k, x in enumerate(c) if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", x)), None)
            if i is None or i < 2 or i + 2 >= len(c) or not re.fullmatch(r"\d{4}-\d{4}", c[0]):
                continue
            dd, mo, y = c[i].split("/")
            a = iso(y, mo, dd, c[i + 1]) if re.match(r"\d", c[i + 1]) else None
            d = iso(y, mo, dd, c[i + 2]) if re.match(r"\d", c[i + 2]) else None
            d = _next_day_if_before(a, d)
            out.append(call(fix_name(c[1]), c[2] or None, port, a, d, name=name))
        return join_overnights(out)
    parse.__name__ = f"parse_incop_{port or name}"
    return parse


def parse_japdeva(h, today):
    """japdeva.go.cr (JAPDEVA, Puerto Limón / Terminal Hernán Garrón Salazar) 'PROGRAMACION CRUCEROS 2026-2027.pdf':
    No. | NAVE | DIA 'SAB' | FECHA LLEGADA 'd/m/yyyy' | AG. NAVIERA | ETA | ETD | ESLORA | CALADO | L. NAVIERA | ...
    Overnight stays are one row per day with the arrival or departure left blank."""
    out, open_stay = [], {}
    for c in table_rows(h):
        i = next((k for k, x in enumerate(c[:6]) if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", x)), None)
        if i is None or i < 2 or i + 2 >= len(c):
            continue
        name = c[i - 2]
        if not name or name.isdigit():
            continue
        dd, mo, y = c[i].split("/")
        # Markdown keeps blank cells; pdftotext drops them, so read the times that follow the agent cell.
        if h.lstrip().startswith(("|", "*", "#")):
            t = [x if re.fullmatch(r"\d{1,2}:\d\d", x) else None for x in c[i + 2:i + 4]]
        else:
            t = [x for x in c[i + 2:i + 4] if re.fullmatch(r"\d{1,2}:\d\d", x)]
            if len(t) == 1:  # one time: a departure if the ship arrived the day before and has not left
                t = [None, t[0]] if open_stay.get(name.lower()) else [t[0], None]
        t += [None] * (2 - len(t))
        a = iso(y, mo, dd, t[0]) if t[0] else None
        d = iso(y, mo, dd, t[1]) if t[1] else None
        if a and a.endswith("T00:00") and d:  # '00:00' = continuing stay
            a = None
        if d and d.endswith("T00:00") and a:
            d = None
        d = _next_day_if_before(a, d)
        open_stay[name.lower()] = d is None
        rest = [x for x in c[i + 2:] if x and not re.fullmatch(r"[\d.,:/]+", x)]
        out.append(call(fix_name(name), rest[0] if rest else None, "lim", a, d))
    return join_overnights(out)


def get_japdeva(url):
    """The season PDF sits at a fixed name per season: the current one and the next (when published)."""
    y, out = date.today().year, []
    for s in ([y - 1, y] if date.today().month < 7 else [y, y + 1]):
        try:
            out.append(pdf_text(get_bytes(url.format(season=f"{s}-{s + 1}"))))
        except Exception as e:
            print(f"     JAPDEVA {s}-{s + 1}: {type(e).__name__}: {str(e)[:100]}")
        time.sleep(DELAY)
    return out


INCOP_PAGE = "https://incop.go.cr/temporada-de-cruceros/"


def incop_fetch(port_word):
    """The newest season PDF(s) for one port linked on INCOP's 'Temporada de Cruceros' page."""
    def fetch(url):
        h = get(INCOP_PAGE)
        links = [urllib.parse.urljoin(INCOP_PAGE, u.replace(" ", "%20"))
                 for u in re.findall(r'href="([^"]+\.pdf)"', h, re.I) if re.search(port_word, u, re.I)]
        seasons = sorted({m for u in links for m in re.findall(r"(20\d\d-20\d\d)", u)})[-2:]
        want = [u for u in dict.fromkeys(links) if any(s in u for s in seasons)]
        if not want:
            raise ValueError(f"no {port_word} PDF linked on {INCOP_PAGE}")
        out = []
        for u in want:
            time.sleep(DELAY)
            out.append(pdf_text(get_bytes(u)))
        return out
    return fetch


# ---------------------------------------------------------------- Argentina

def parse_ushuaia(h, today):
    """findelmundo.tur.ar (Instituto Fueguino de Turismo; compiled from the Dirección Provincial de Puertos list)
    'Cronograma de cruceros', one month per page: Buque | Operador | Arribo 'd/m/yyyy  hh:mm' | Partida | Capacidad |
    Tipo de viaje (Antártico / Regional / Internacional). The same rows are repeated as mobile cards; only the
    <table> is read."""
    out = []
    for tb in re.findall(r"<table\b.*?</table>", h, re.S | re.I):
        for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", tb, re.S | re.I):
            c = [text(x) for x in cells(row)]
            if len(c) < 4:
                continue

            def dt(s):
                m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}:\d\d)", s)
                return iso(m[3], m[2], m[1], m[4]) if m else None
            a, d = dt(c[2]), dt(c[3])
            if c[0] and (a or d):
                out.append(call(fix_name(c[0]), c[1] or None, "ush", a, None if d and a and d <= a else d))
    return out


def get_ushuaia(url):
    """The page shows one month (?p=YYYYMM); read every month of the season listed in its pagination from the
    current month on."""
    first = get(url)
    months = sorted(set(re.findall(r"cronograma\?p=(\d{6})", first)))
    now = date.today().strftime("%Y%m")
    pages = [first]
    for m in [x for x in months if x > now][:12]:
        time.sleep(DELAY)
        pages.append(get(f"{url}?p={m}"))
    return pages


def parse_agp(h, today):
    """argentina.gob.ar (AGP, Puerto Buenos Aires, Subdirección de Cruceros) 'BUQUES EN CRUCEROS TURISTICOS
    TEMPORADA 2026/2027' PDF: N° | BUQUE | ENTRADA 'dd-mm-yy' | HORA | PROCEDENCIA | SALIDA 'dd-mm-yy' | HORA |
    DESTINO | AGENCIA | ... A departure dated before the arrival (year typos such as '04-02-25') is dropped."""
    out = []
    for c in table_rows(h):
        i = next((k for k, x in enumerate(c[:4]) if re.fullmatch(r"\d{1,2}-\d{1,2}-\d{2}", x)), None)
        if i is None or i < 1 or i + 4 >= len(c) or not re.search(r"[A-Za-z]", c[i - 1]):
            continue

        def dt(s, hm):
            m = re.fullmatch(r"(\d{1,2})-(\d{1,2})-(\d{2})", s)
            return iso(2000 + int(m[3]), m[2], m[1], hm) if m and re.fullmatch(r"\d{1,2}:\d\d", hm) else None
        a = dt(c[i], c[i + 1])
        d = next((dt(c[k], c[k + 1]) for k in range(i + 2, min(i + 4, len(c) - 1))
                  if re.fullmatch(r"\d{1,2}-\d{1,2}-\d{2}", c[k])), None)
        if a and d and d <= a:
            d = None
        if a:
            out.append(call(fix_name(c[i - 1]), None, "bue", a, d))
    return out


AGP_PAGE = ("https://www.argentina.gob.ar/economia/administracion-general-de-puertos-sau/puertos/buques/"
            "informes-de-cruceros-por-temporada")


def get_agp(url):
    """The PDFs are linked as 'Temporada 2026-2027' (file names change with each update): read the seasons that
    end this year or later."""
    h = get(url)
    out = []
    for u, y1, y2 in re.findall(r'href="([^"]+\.pdf)"[^>]*>\s*Temporada\s+(\d{4})-(\d{4})', h, re.I):
        if int(y2) >= date.today().year:
            time.sleep(DELAY)
            out.append(pdf_text(get_bytes(urllib.parse.urljoin(url, u))))
    if not out:
        raise ValueError("no current 'Temporada' PDF linked")
    return out


# ---------------------------------------------------------------- Brazil

def parse_santos(h, today):
    """portodesantos.com.br (Autoridade Portuária de Santos) 'Navios Esperados - Passageiros': Navio | Bandeira |
    Com/Cal | Nav | Cheg/Arrival 'dd/mm/yyyy hh:mm:ss' | Carimbo | Agência | Viagem | DUV | P | Terminal. Only rows
    berthing at the PASSAGEIROS terminal (Concais) are cruise ships; the rest are harbour craft and navy. Arrival
    only."""
    out = []
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", h, re.S | re.I):
        c = [text(x) for x in cells(row)]
        if len(c) < 11 or "PASSAGEIRO" not in c[10].upper():
            continue
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})(?:\s+(\d{1,2}:\d\d))?", c[4])
        if m and c[0]:
            out.append(call(fix_name(c[0]), None, None, iso(m[3], m[2], m[1], m[4]) if m[4] else iso(m[3], m[2], m[1]),
                            None, name="Santos"))
    return out


def parse_piermaua(h, today):
    """piermaua.rio (Pier Mauá, Rio de Janeiro cruise terminal) 'Programação Navios', a The Events Calendar site;
    read through its REST list (/wp-json/tribe/events/v1/events). Ship calls are the events in category 'Terminal'
    (title = ship, start/end = local berth times); category 'Evento' is the venue's own events and is skipped."""
    import json
    s = h[h.find("{"):h.rfind("}") + 1]
    try:
        events = json.loads(s).get("events", [])
    except ValueError:
        return []
    out = []
    for e in events:
        if not any(c.get("name") == "Terminal" for c in e.get("categories") or []):
            continue
        a, d = (e.get("start_date") or "")[:16], (e.get("end_date") or "")[:16]
        a = a.replace(" ", "T") if re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", a) else None
        d = d.replace(" ", "T") if re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d", d) else None
        name = text(e.get("title") or "")
        if a and name:
            out.append(call(fix_name(name), None, "rio", a, d if d and d > a else None))
    return out


def get_piermaua(url):
    """Follow next_rest_url from today to WINDOW_AHEAD days ahead (50 events a page)."""
    start = date.today()
    nxt = (f"{url}?per_page=50&start_date={start.isoformat()}"
           f"&end_date={(start + timedelta(days=WINDOW_AHEAD)).isoformat()}")
    pages = []
    while nxt and len(pages) < 10:
        if pages:
            time.sleep(DELAY)
        pages.append(get(nxt))
        m = re.search(r'"next_rest_url"\s*:\s*"([^"]+)"', pages[-1])
        nxt = m[1].replace("\\/", "/") if m else None
    return pages


def parse_valparaiso(h, today):
    """puertovalparaiso.cl (Empresa Portuaria Valparaíso) 'Itinerario de Cruceros', one season table:
    N° | Nave | Eslora | Agencia | Terminal | Fecha de Atraque 'dd-mm-yyyy h:mm' | Fecha de Zarpe | Observación."""
    out = []
    for r in re.findall(r"<tr\b.*?</tr>", h, re.S | re.I):
        c = [text(x) for x in cells(r)]
        if len(c) < 7 or not re.fullmatch(r"\d+", c[0]):
            continue

        def dt(v):
            m = re.match(r"(\d{1,2})-(\d{1,2})-(\d{4})\s+(\d{1,2}:\d\d)", v)
            return iso(m[3], m[2], m[1], m[4]) if m else None
        a, d = dt(c[5]), dt(c[6])
        if a and c[1] and "cancel" not in " ".join(c[7:]).lower():
            out.append(call(fix_name(c[1]), None, "vap", a, d if d and d > a else None))
    return out


# ---------------------------------------------------------------- sources

# key: sample-file prefix for --test
SOURCES = [
    {"key": "tap", "name": "Puerto Chiapas (ASIPONA)",
     "url": "https://www.puertochiapas.com.mx/documentos/transparencia/datos_personales/{year}_calendario_crucero.pdf",
     "parse": parse_puertochiapas, "fetch": get_puertochiapas},
    {"key": "topo", "name": "Topolobampo (ASIPONA)", "url": "https://www.puertotopolobampo.com.mx/archivos/programacion.php",
     "parse": parse_topolobampo},
    {"key": "sbq", "name": "Santa Barbara", "url": "https://santabarbaraca.gov/things-do/waterfront/cruise-ship-visits",
     "parse": parse_santabarbara},
    {"key": "avl", "name": "Catalina Island (Avalon)",
     "url": "https://www.lovecatalina.com/community-information/cruise-ship-schedule/", "parse": parse_catalina},
    {"key": "anc", "name": "Anchorage (CLAA)", "url": "https://claalaska.com/?page_id=1250",
     "parse": claa_parser("anc", "ANC"), "fetch": claa_fetch("ANC")},
    {"key": "hom", "name": "Homer (CLAA)", "url": "https://claalaska.com/?page_id=1250",
     "parse": claa_parser("hom", "HOM"), "fetch": claa_fetch("HOM")},
    {"key": "pun", "name": "Puntarenas (INCOP)", "url": INCOP_PAGE, "parse": parse_incop("pun"),
     "fetch": incop_fetch("PUNTARENAS")},
    {"key": "lim", "name": "Puerto Limón (JAPDEVA)", "url": "https://www.japdeva.go.cr/PROGRAMACION%20CRUCEROS%20{season}.pdf",
     "parse": parse_japdeva, "fetch": get_japdeva},
    {"key": "ush", "name": "Ushuaia (InFuETur)", "url": "https://findelmundo.tur.ar/es/cruceros/cronograma",
     "parse": parse_ushuaia, "fetch": get_ushuaia},
    {"key": "bue", "name": "Buenos Aires (AGP)", "url": AGP_PAGE, "parse": parse_agp, "fetch": get_agp},
    {"key": "sts", "name": "Santos (Autoridade Portuária)",
     "url": "https://www.portodesantos.com.br/informacoes-operacionais/operacoes-portuarias/navegacao-e-movimento-de-navios/"
            "navios-esperados-passageiros/", "parse": parse_santos},
    {"key": "rio", "name": "Rio de Janeiro (Pier Mauá)", "url": "https://piermaua.rio/wp-json/tribe/events/v1/events",
     "parse": parse_piermaua, "fetch": get_piermaua},
    {"key": "vap", "name": "Valparaíso (EPV)", "url": "https://www.puertovalparaiso.cl/itinerario-de-cruceros",
     "parse": parse_valparaiso},
]
