"""Print what a schedule source returns on this machine, to fix parsers: python tools/debug_source.py KEY [KEY...]"""
import sys
from datetime import datetime, timezone

import port_schedules as ps

keys = set(sys.argv[1:])
today = datetime.now(timezone.utc).date()
for s in ps.all_sources():
    if s["key"] not in keys:
        continue
    print(f"===== {s['key']} {s['name']} {s['url']}")
    try:
        pages = s["fetch"](s["url"]) if "fetch" in s else [ps.get(s["url"])]
    except Exception as e:
        print(f"FETCH {type(e).__name__}: {str(e)[:300]}")
        continue
    print(f"pages={len(pages)} sizes={[len(p) for p in pages]}")
    for i, p in enumerate(pages[:2]):
        print(f"----- page {i} -----")
        print(str(p)[:3500])
    try:
        got = [c for p in pages for c in s["parse"](p, today)]
        print(f"PARSED {len(got)} calls; first: {got[:3]}")
    except Exception as e:
        print(f"PARSE {type(e).__name__}: {e}")
