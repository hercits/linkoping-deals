#!/usr/bin/env python3
"""Fetch Matpriskollen store pages and extract the offers embedded in the page data.

Usage:
  python3 tools/scrape.py                 # fetch every store in stores.json -> data.json
  python3 tools/scrape.py --html f.html   # parse one saved page and print a summary
"""
import argparse, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
PUSH = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)')
OFFER_START = re.compile(r'\{"id":"[0-9a-f-]{36}","offerKey"')
IMG_ID = re.compile(r"/([0-9a-f-]{36})/")


def page_text(html):
    """Join the streamed page-data chunks into one string."""
    parts = []
    for m in PUSH.finditer(html):
        try:
            parts.append(json.loads(m.group(1)))
        except Exception:
            pass
    return "".join(parts)


def offers_from_html(html):
    text = page_text(html)
    dec = json.JSONDecoder()
    seen, out = set(), []
    for m in OFFER_START.finditer(text):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except Exception:
            continue
        if obj.get("id") in seen or "priceLabel" not in obj:
            continue
        seen.add(obj["id"])
        out.append(obj)
    return out


def clean(v):
    return "" if v in (None, "$undefined", "-") else str(v).strip()


def slim(o):
    img = IMG_ID.search(clean(o.get("image")) or "")
    cats = [c.get("name") for c in (o.get("categories") or []) if isinstance(c, dict)]
    parents = [c.get("parent_category") for c in (o.get("categories") or []) if isinstance(c, dict) and c.get("parent_category")]
    return {
        "id": o["id"],
        "t": clean(o.get("title")),
        "s": clean(o.get("subtitle")),
        "br": clean(o.get("productBrand")),
        "v": clean(o.get("volume")),
        "pr": clean(o.get("priceLabel")),
        "cp": clean(o.get("comprice")),
        "cat": clean(o.get("category")),
        "pcat": clean(parents[0]) if parents else "",
        "cond": clean(o.get("condition")),
        "disc": clean(o.get("discount")),
        "img": img.group(1) if img else "",
        "from": o.get("validFrom") if isinstance(o.get("validFrom"), int) else None,
        "to": o.get("validTo") if isinstance(o.get("validTo"), int) else None,
        "tags": [t.get("name") for t in (o.get("productTags") or []) if isinstance(t, dict) and t.get("name")],
        "origin": clean(o.get("productOrigin")),
    }


def fetch(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "sv-SE,sv;q=0.9"})
            with urllib.request.urlopen(req, timeout=40) as r:
                html = r.read().decode("utf-8", "replace")
            offers = offers_from_html(html)
            if offers:
                return offers
            print(f"  attempt {i+1}: page had no offers", file=sys.stderr)
        except Exception as e:
            print(f"  attempt {i+1}: {e}", file=sys.stderr)
        time.sleep(5 * (i + 1))
    return None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--html")
    a = ap.parse_args()
    if a.html:
        offers = [slim(o) for o in offers_from_html(open(a.html, encoding="utf-8", errors="replace").read())]
        print(len(offers), "offers")
        for o in offers[:3]:
            print(json.dumps(o, ensure_ascii=False))
        from collections import Counter
        print(Counter(o["cat"] for o in offers).most_common())
        print("conditions:", Counter(o["cond"] for o in offers).most_common(8))


# ---------------------------------------------------------------- reference photos from Willys' catalogue
WORD = re.compile(r"[a-zåäöéü]{3,}")
STOP = {"med", "och", "eko", "naturell", "original", "skivad", "skivat", "flerpack", "konserv", "pack", "refill"}


def words(text):
    return {w for w in WORD.findall((text or "").lower()) if w not in STOP}


def axfood_photo(title, brand):
    """Photo of the same product in Willys' online catalogue, or None. Brand must match and the name must overlap."""
    if not brand or len(brand) < 2:
        return None
    q = f"{brand} {title.split(',')[0].split('/')[0]}".strip()
    url = "https://www.willys.se/search?" + urllib.parse.urlencode({"q": q, "size": 12})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            res = json.load(r).get("results") or []
    except Exception as e:
        print("  willys search failed:", q, e, file=sys.stderr)
        return None
    want = words(title)
    b = brand.lower()
    for p in res:
        maker = (p.get("manufacturer") or "").lower()
        if not maker or not (b in maker or maker in b):
            continue
        have = words(p.get("name", "")) | words(p.get("productLine2", ""))
        overlap = any(w == h or (len(w) >= 5 and (w.startswith(h) or h.startswith(w))) for w in want for h in have)
        img = (p.get("image") or {}).get("url")
        if overlap and img:
            return {"url": img, "name": f"{p.get('name','')} {p.get('displayVolume','')}".strip()}
    return None


# ---------------------------------------------------------------- Willys / Hemköp: regular price, saving, 30-day lowest
def money(text):
    m = re.search(r"(\d[\d\s]*)(?:[.,:](\d{1,2}))?", text or "")
    return float(m.group(1).replace(" ", "") + "." + (m.group(2) or "0")) if m else None


def unit_of(text):
    m = re.search(r"kr\s*/\s*(\w+)", text or "") or re.search(r"/\s*(\w+)", text or "")
    return m.group(1).lower() if m else ""


def name_key(text):
    return re.sub(r"[^a-z0-9åäöéü]+", " ", (text or "").lower()).strip()


def axfood_campaigns(host, store):
    """All in-store campaign products for one Willys/Hemköp store, from the chain's own website."""
    out, page = [], 0
    while True:
        url = f"https://{host}/search/campaigns/offline?" + urllib.parse.urlencode(
            {"q": store, "type": "PERSONAL_GENERAL", "page": page, "size": 50})
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=40) as r:
            d = json.load(r)
        out += d.get("results") or []
        pages = (d.get("pagination") or {}).get("numberOfPages") or 1
        page += 1
        if page >= pages or page > 20:
            return out
        time.sleep(1)


def enrich_axfood(items, host, store):
    try:
        prods = axfood_campaigns(host, store)
    except Exception as e:
        print("  campaign lookup failed:", e, file=sys.stderr)
        return 0
    groups = {}
    for p in prods:
        promo = (p.get("potentialPromotions") or [{}])[0]
        for key in {name_key(promo.get("name")), name_key(p.get("name"))} - {""}:
            groups.setdefault(key, []).append((p, promo))
    matched = 0
    for o in items:
        k = name_key(o["t"])
        cands = groups.get(k) or [c for key, v in groups.items() if key.startswith(k + " ") or k.startswith(key + " ") for c in v]
        b = (o.get("br") or "").lower()
        if b:
            same = [c for c in cands if b in (c[0].get("manufacturer") or "").lower() or (c[0].get("manufacturer") or "").lower() in b]
            cands = same or cands
        if not cands:
            continue
        matched += 1
        regs = sorted({money(c[0].get("priceNoUnit")) for c in cands if money(c[0].get("priceNoUnit"))})
        unit = (cands[0][0].get("priceUnit") or "").replace("kr/", "")
        promo = cands[0][1]
        o["reg"] = (f"{regs[0]:.2f}".replace(".", ",") + (f"–{regs[-1]:.2f}".replace(".", ",") if len(regs) > 1 else "") + f" kr/{unit}") if regs else ""
        o["save"] = (promo.get("savePrice") or "").strip()
        o["low30"] = (cands[0][0].get("offlinePromotionLowestHistoricalPrice") or "").strip()
        o["member"] = promo.get("campaignType") == "LOYALTY"
        if promo.get("redeemLimitLabel") and not o.get("cond"):
            o["cond"] = promo["redeemLimitLabel"] + "."
        # verdict: is the price per item (or per kg) below the lowest price of the past 30 days?
        each = None
        m = re.search(r"(\d+)\s*för\s*(\d[\d\s]*(?:[.,]\d+)?)", o.get("pr") or "", re.I)
        if m:
            each = money(m.group(2)) / int(m.group(1))
        elif isinstance(promo.get("price"), (int, float)):
            each = promo["price"] / max(1, int(promo.get("qualifyingCount") or 1))
        lows = [float(a.replace(",", ".")) for a in re.findall(r"\d+(?:[.,]\d+)?", (o["low30"] or "").split("kr")[0])]
        if each and lows:
            if each < min(lows) - 0.005:
                o["verified"] = True
            elif each >= max(lows) - 0.005:
                o["verified"] = False
        img = (cands[0][0].get("image") or {}).get("url")
        big = (cands[0][0].get("originalImage") or {}).get("url")
        if img:
            o["imgurl"], o["imgbig"] = img, big or img
            o.pop("imgsrc", None)
    return matched


# ---------------------------------------------------------------- daily build
GROUPS = [  # Matpriskollen category (lowercase substring) -> page group
    ("frukt", "FRUKT"), ("grönsak", "FRUKT"),
    ("kött", "KOTT"), ("korv", "KOTT"), ("pålägg", "KOTT"), ("chark", "KOTT"), ("fisk", "KOTT"),
    ("fågel", "KOTT"), ("kyckling", "KOTT"), ("vego", "KOTT"), ("vegetar", "KOTT"),
    ("mejeri", "MEJERI"), ("ost", "MEJERI"), ("ägg", "MEJERI"),
    ("bröd", "BROD"), ("kak", "BROD"),
    ("färdig", "FRYST"), ("fryst", "FRYST"), ("frys", "FRYST"),
    ("dryck", "DRYCK"), ("kaffe", "SKAFFERI"),
    ("godis", "GODIS"), ("snacks", "GODIS"), ("glass", "GODIS"), ("dessert", "GODIS"), ("mellanmål", "GODIS"),
    ("skafferi", "SKAFFERI"), ("krydd", "SKAFFERI"),
]


def group(cat, pcat=""):
    for name in (cat, pcat):
        low = (name or "").lower()
        for key, g in GROUPS:
            if key in low:
                return g
    return "HUSHALL"


def main():
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo("Europe/Stockholm")
    except Exception:
        tz = timezone(timedelta(hours=1))
    now = datetime.now(tz)
    stores = json.load(open("stores.json", encoding="utf-8"))
    zh = json.load(open("zh.json", encoding="utf-8")) if os.path.exists("zh.json") else {}
    prev = {}
    if os.path.exists("data.json"):
        try:
            prev = {s["id"]: s for s in json.load(open("data.json", encoding="utf-8"))["stores"]}
        except Exception:
            prev = {}

    out, failed, missing_zh = [], [], set()
    for i, s in enumerate(stores):
        if i:
            time.sleep(3)
        print(s["id"], file=sys.stderr)
        rec = {k: s[k] for k in ("id", "name", "chain", "address", "km", "source") if k in s}
        offers = fetch(s["source"])
        if offers:
            items = []
            for o in map(slim, offers):
                if o["to"] and o["to"] < now.timestamp():
                    continue  # already expired
                o["g"] = group(o["cat"], o["pcat"])
                o["zh"] = zh.get(o["t"], "")
                if not o["zh"]:
                    missing_zh.add(o["t"])
                del o["pcat"]
                items.append(o)
            if s.get("axfood"):
                n = enrich_axfood(items, s["axfood"]["host"], s["axfood"]["store"])
                print(f"  {n}/{len(items)} offers checked against {s['axfood']['host']}", file=sys.stderr)
            rec.update(status="ok", fetched_at=now.isoformat(timespec="minutes"), total=len(offers), items=items)
        elif prev.get(s["id"], {}).get("items"):
            p = prev[s["id"]]
            rec.update(status="stale", fetched_at=p.get("fetched_at"), total=p.get("total"),
                       items=[o for o in p["items"] if isinstance(o, dict) and (not o.get("to") or o["to"] >= now.timestamp())])
            failed.append(s["id"])
        else:
            rec.update(status="pending", fetched_at=None, total=None, items=[])
            failed.append(s["id"])
        out.append(rec)

    # Offers without a photo: borrow the photo of the identical product (same name and brand) from another store
    exact, by_title = {}, {}
    for rec in out:
        for o in rec["items"]:
            if o.get("img"):
                exact.setdefault((o["t"].lower(), o["br"].lower()), o["img"])
                by_title.setdefault(o["t"].lower(), set()).add(o["img"])
    borrowed = 0
    for rec in out:
        for o in rec["items"]:
            if o.get("img") or o.get("imgurl"):
                continue
            img = exact.get((o["t"].lower(), o["br"].lower()))
            if not img and len(by_title.get(o["t"].lower(), ())) == 1 and len(o["t"]) > 6:
                img = next(iter(by_title[o["t"].lower()]))
            if img:
                o["img"], o["imgsrc"] = img, "same product in another store"
                borrowed += 1
    print(f"borrowed {borrowed} photos from identical products in other stores", file=sys.stderr)

    # Still no photo: look the product up in Willys' catalogue (reference photo, labelled as such on the page)
    found, cache = 0, {}
    for rec in out:
        for o in rec["items"]:
            if o.get("img") or o.get("imgurl"):
                continue
            key = (o["t"].lower(), o["br"].lower())
            if key not in cache:
                cache[key] = axfood_photo(o["t"], o["br"])
                time.sleep(1)
            hit = cache[key]
            if hit:
                o["imgurl"], o["imgsrc"] = hit["url"], f"Willys: {hit['name']}"
                found += 1
    left = sum(1 for rec in out for o in rec["items"] if not o.get("img") and not o.get("imgurl"))
    print(f"found {found} reference photos at Willys; {left} offers still without a photo", file=sys.stderr)

    data = {"updated_at": now.isoformat(timespec="minutes"), "origin": "Vallastaden", "source": "Matpriskollen", "stores": out}
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    with open("missing_zh.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(missing_zh)) + ("\n" if missing_zh else ""))
    n = sum(len(s["items"]) for s in out)
    print(f"{n} offers from {len(out) - len(failed)} stores; failed: {', '.join(failed) or 'none'}; "
          f"{len(missing_zh)} products without Chinese name")


if __name__ == "__main__" and len(sys.argv) == 1:
    main()
