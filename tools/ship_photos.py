"""Find a photo of each cruise ship on Wikipedia and save a small copy in data/ships/,
so the app can show crew their own ship even offline.

Ships come from data/fleets.json and data/ships.json. When several ships have carried
the same name, the newest article ("Sun Princess (2024)") wins, since that one sails now.
Photos are from Wikimedia Commons; data/ship_photos.json keeps the article for credit.
"""
import gzip, json, os, re, sys, time, urllib.parse, urllib.request

DATA = os.path.join(os.path.dirname(__file__), "..", "data")
API = "https://en.wikipedia.org/w/api.php"
UA = "Gangway/0.2 (offline cruise port guide; https://github.com/filipovski95/linguapath)"
WIDTH = 480


def get(url, binary=False):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Api-User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40) as r:
                body = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return body if binary else json.loads(body)
        except Exception as e:
            print(f"  {e} {url[:160]}", flush=True)
            time.sleep(3 + 5 * attempt)
    return None


def query(**params):
    params.update(action="query", format="json", formatversion=2)
    return (get(API + "?" + urllib.parse.urlencode(params)) or {}).get("query", {}).get("pages", [])


key = lambda n: re.sub(r"[^a-z0-9]", "", n.lower())


def is_ship(pg):
    d = (pg.get("description") or "").lower()
    return "missing" not in pg and "disambiguation" not in d and re.search(r"\b(ship|liner|vessel)\b", d) and pg.get("thumbnail")


def find(name):
    common = dict(prop="pageimages|description", piprop="thumbnail", pithumbsize=WIDTH, redirects=1)
    found = query(generator="search", gsrsearch=f'intitle:"{name}" cruise ship', gsrlimit=10, **common)
    found += query(titles=name, **common)
    best, best_year = None, -1
    for pg in found:
        t = pg.get("title", "")
        m = re.fullmatch(re.escape(name) + r"(?: \((?:ship, )?(\d{4})(?: ship)?\))?", t, re.I)
        if not m or not is_ship(pg):
            continue
        year = int(m[1]) if m[1] else 0
        if year > best_year:
            best, best_year = pg, year
    return best


def main():
    with open(os.path.join(DATA, "fleets.json")) as f:
        names = [n for line in json.load(f).values() for n in line["ships"]]
    try:
        with open(os.path.join(DATA, "ships.json")) as f:
            names += [s["name"] for s in json.load(f)["ships"]]
    except FileNotFoundError:
        pass
    path = os.path.join(DATA, "ship_photos.json")
    try:
        with open(path) as f:
            photos = json.load(f)
    except FileNotFoundError:
        photos = {}
    os.makedirs(os.path.join(DATA, "ships"), exist_ok=True)
    redo = "--all" in sys.argv
    seen = set()
    for name in names:
        k = key(name)
        if k in seen or (k in photos and not redo):
            continue
        seen.add(k)
        pg = find(name)
        time.sleep(0.4)
        if not pg:
            print(f"{name}: no article with a photo", flush=True)
            continue
        jpg = get(pg["thumbnail"]["source"], binary=True)
        if not jpg:
            continue
        fn = f"ships/{k}.jpg"
        with open(os.path.join(DATA, fn), "wb") as f:
            f.write(jpg)
        photos[k] = {"f": fn, "wpu": pg["title"]}
        print(f"{name}: {pg['title']} ({len(jpg) // 1024} KB)", flush=True)
        with open(path, "w") as f:
            json.dump(photos, f, ensure_ascii=False, indent=0, sort_keys=True)
        time.sleep(0.6)
    with open(path, "w") as f:
        json.dump(photos, f, ensure_ascii=False, indent=0, sort_keys=True)
    print(f"{len(photos)} ships have a photo", flush=True)


if __name__ == "__main__":
    main()
