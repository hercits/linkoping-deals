#!/usr/bin/env python3
"""Fetch Matpriskollen store pages and extract the offers embedded in the page data.

Usage:
  python3 tools/scrape.py                 # fetch every store in stores.json -> data.json
  python3 tools/scrape.py --html f.html   # parse one saved page and print a summary
"""
import argparse, json, os, re, sys, time, urllib.request
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
