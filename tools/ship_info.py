"""Read the basic facts about each cruise ship (guests, crew, tonnage, length, year)
from the infobox of its Wikipedia article and save them in data/ship_info.json,
so crew can see them offline after picking their ship.

Uses the article ship_photos.py already matched where there is one, otherwise the
same search without needing a photo.
"""
import html, json, os, re, sys, time
from ship_photos import DATA, find, key, get, API
import urllib.parse


def find_title(name):
    pg = find(name, photo=False)
    return pg and pg["title"]


def clean(v):
    v = re.sub(r"<sup.*?</sup>", "", v, flags=re.S)
    v = re.sub(r"<(br|li)[^>]*>", "; ", v)
    v = re.sub(r"<style.*?</style>", "", v, flags=re.S)
    v = html.unescape(re.sub(r"<[^>]+>", "", v))
    return re.sub(r"\s+", " ", v).strip(" ;")


def infobox(title):
    r = get(API + "?" + urllib.parse.urlencode(dict(action="parse", page=title, prop="text", section=0, format="json", formatversion=2, redirects=1)))
    text = ((r or {}).get("parse") or {}).get("text", "")
    rows = {}
    for lab, val in re.findall(r'<t[hd][^>]*class="infobox-label"[^>]*>(.*?)</t[hd]>\s*<td[^>]*class="infobox-data"[^>]*>(.*?)</td>', text, re.S):
        lab = clean(lab).rstrip(":").lower()
        val = clean(val)
        if val:
            rows.setdefault(lab, []).append(val)
    return rows


num = lambda s: (re.search(r"\d{1,3}(?:,\d{3})+|\d+", s or "") or [None])[0]


def facts(rows):
    last = lambda *ks: next((rows[k][-1] for k in ks if k in rows), "")
    first = lambda *ks: next((rows[k][0] for k in ks if k in rows), "")
    out = {}
    t = last("tonnage")
    m = re.search(r"(\d{1,3}(?:,\d{3})+|\d{4,})\s*(?:GT|gross)", t) or re.search(r"(\d{1,3}(?:,\d{3})+)", t)
    if m: out["gt"] = m[1]
    m = re.search(r"(\d+(?:\.\d+)?)\s*m\b", last("length"))
    if m: out["len"] = m[1]
    cap = last("capacity")
    if num(cap): out["pax"] = num(cap)
    if num(last("crew")): out["crew"] = num(last("crew"))
    if num(last("decks")): out["decks"] = num(last("decks"))
    m = re.search(r"\b(19|20)\d{2}\b", first("in service", "maiden voyage", "completed", "launched"))
    if m: out["built"] = m[0]
    b = first("builder")
    if b: out["builder"] = re.split(r",|;|\(", b)[0].strip()[:40]
    c = first("class and type")
    if c: out["class"] = re.split(r";|\bcruise ship\b", c)[0].strip(" ,-")[:40]
    return out


def main():
    with open(os.path.join(DATA, "fleets.json")) as f:
        names = [n for line in json.load(f).values() for n in line["ships"]]
    try:
        with open(os.path.join(DATA, "ship_photos.json")) as f:
            photos = json.load(f)
    except FileNotFoundError:
        photos = {}
    path = os.path.join(DATA, "ship_info.json")
    try:
        with open(path) as f:
            info = json.load(f)
    except FileNotFoundError:
        info = {}
    redo = "--all" in sys.argv
    for name in names:
        k = key(name)
        if k in info and not redo:
            continue
        title = (photos.get(k) or {}).get("wpu") or find_title(name)
        if not title:
            print(f"{name}: no article", flush=True)
            continue
        f = facts(infobox(title))
        time.sleep(0.5)
        if not f:
            print(f"{name}: no infobox facts in {title}", flush=True)
            continue
        f["wpu"] = title
        info[k] = f
        print(f"{name}: {f}", flush=True)
    with open(path, "w") as fh:
        json.dump(info, fh, ensure_ascii=False, indent=0, sort_keys=True)
    print(f"{len(info)} ships have facts", flush=True)


if __name__ == "__main__":
    main()
