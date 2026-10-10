#!/usr/bin/env python3
"""Build data.json for the Linköping deals page.

Usage: python3 build.py --stores stores.json --raw raw --prev data.json --out data.json

raw/<store-id>.txt holds one store's offers as fetched from Matpriskollen:
  TOTAL=<n>
  ADDRESS=<street address>
  product | brand and size | offer price text | CAT | Chinese name
  ...
  COUNT=<n>
A store with no raw file this run keeps its offers from --prev (marked stale).
"""
import argparse, json, os, re
from datetime import datetime, timezone, timedelta

CATS = {"FRUKT", "KOTT", "MEJERI", "BROD", "SKAFFERI", "FRYST", "DRYCK", "GODIS", "HUSHALL"}
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
TZ = timezone(timedelta(hours=2))  # Europe/Stockholm summer time; only used for the label


def clean(s):
    s = s.strip()
    s = re.sub(r"\s*\((kategori|category)[^)]*\)", "", s, flags=re.I)
    return "" if s in ("-", "–", "—") else s


def parse_raw(path):
    total, address, items = None, "", []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("TOTAL="):
                m = re.search(r"\d+", line)
                total = int(m.group()) if m else None
                continue
            if line.startswith("ADDRESS="):
                address = clean(line[len("ADDRESS="):])
                continue
            if line.startswith("COUNT="):
                continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3:
                continue
            # product | brand | price | CAT | zh | img  (brand is sometimes dropped by the fetcher)
            ci = next((i for i, p in enumerate(parts) if p.strip().upper() in CATS), None)
            if ci is None:
                continue
            product = clean(parts[0])
            if ci >= 3:
                brand, price = clean(parts[1]), clean(parts[2])
            else:
                brand, price = "", clean(parts[1])
            cat = parts[ci].strip().upper()
            zh = clean(parts[ci + 1]) if len(parts) > ci + 1 else ""
            img = parts[ci + 2].strip() if len(parts) > ci + 2 else ""
            img = img if UUID.fullmatch(img) else ""
            if brand == price or re.fullmatch(r"[\d\s.,]+(:-)?(/\w+)?", brand):
                brand = ""
            if not product or not price:
                continue
            items.append([product, brand, price, cat, zh, img])
    return total, address, items


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stores", default="stores.json")
    ap.add_argument("--raw", default="raw")
    ap.add_argument("--prev", default="")
    ap.add_argument("--out", default="data.json")
    a = ap.parse_args()

    stores = json.load(open(a.stores, encoding="utf-8"))
    prev = {}
    if a.prev and os.path.exists(a.prev):
        try:
            prev = {s["id"]: s for s in json.load(open(a.prev, encoding="utf-8")).get("stores", [])}
        except Exception:
            prev = {}

    now = datetime.now(TZ).isoformat(timespec="minutes")
    out, report = [], []
    for s in stores:
        rec = dict(s)
        path = os.path.join(a.raw, s["id"] + ".txt")
        if os.path.exists(path):
            total, address, items = parse_raw(path)
            rec.update(fetched_at=now, total=total, items=items, status="ok")
            if address:
                rec["address_page"] = address
            report.append(f'{s["id"]}: {len(items)} items (page says {total})')
        elif s["id"] in prev and prev[s["id"]].get("items"):
            p = prev[s["id"]]
            rec.update(fetched_at=p.get("fetched_at"), total=p.get("total"), items=p["items"], status="stale")
            report.append(f'{s["id"]}: kept previous data from {p.get("fetched_at")}')
        else:
            rec.update(fetched_at=None, total=None, items=[], status="pending")
            report.append(f'{s["id"]}: no data yet')
        out.append(rec)

    data = {"updated_at": now, "origin": "Vallastaden", "source": "Matpriskollen", "stores": out}
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print("\n".join(report))
    print("total items:", sum(len(s["items"]) for s in out))


if __name__ == "__main__":
    main()
