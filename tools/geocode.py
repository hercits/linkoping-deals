#!/usr/bin/env python3
"""Look up store and home coordinates on OpenStreetMap (Nominatim) and write geo.json.
Runs in GitHub Actions. Stores with fixed coordinates in stores.json keep them."""
import json, time, urllib.parse, urllib.request

UA = "linkoping-deals/1.0 (https://github.com/hercits/linkoping-deals)"
HOME = ["Vallastaden, Linköping, Sweden"]


def nominatim(q):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "jsonv2", "limit": 1, "countrycodes": "se"})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "sv"})
    with urllib.request.urlopen(req, timeout=30) as r:
        res = json.load(r)
    time.sleep(1.2)  # Nominatim usage policy: max 1 request per second
    return res[0] if res else None


def lookup(queries):
    for q in queries:
        try:
            hit = nominatim(q)
        except Exception as e:
            print("  error", q, e)
            continue
        if hit:
            print(f"  {q!r} -> {hit['lat']},{hit['lon']} ({hit.get('category')}/{hit.get('type')}) {hit.get('display_name','')[:80]}")
            return {"lat": round(float(hit["lat"]), 5), "lon": round(float(hit["lon"]), 5), "src": "OpenStreetMap", "match": q}
        print("  no match", q)
    return None


stores = json.load(open("stores.json", encoding="utf-8"))
out = {"attribution": "© OpenStreetMap contributors", "stores": {}}
print("home")
out["home"] = dict(lookup(HOME) or {"lat": None, "lon": None}, name="Vallastaden")
for s in stores:
    g = s.get("geo", {})
    print(s["id"])
    if "lat" in g:
        out["stores"][s["id"]] = {"lat": g["lat"], "lon": g["lon"], "src": g.get("src", "fixed")}
        continue
    hit = lookup(g.get("q", []))
    if hit:
        out["stores"][s["id"]] = hit
json.dump(out, open("geo.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote geo.json with", len(out["stores"]), "stores")
