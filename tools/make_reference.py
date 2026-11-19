"""Build the fixed reference list used by the page-draft task (deterministic, no model).

Vegan: open vegan or vegetarian restaurant, has address, confidence >= 0.7;
vegan_restaurant first, then by confidence; first 10.
  python tools/make_reference.py denver

Wedding venues: open event_venue, has address, confidence >= 0.7;
higher confidence first, then name; first 10.
  python tools/make_reference.py wedding denver
"""
import json, sys
from pathlib import Path

KEEP = ["id", "name", "taxonomy_primary", "address", "locality", "region", "postcode", "website", "phone"]

def write(path, rows):
    Path(path).write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(len(rows), "written to", path)

def vegan(city: str) -> None:
    d = json.loads(Path(f"data/overture/vegan_{city}.json").read_text(encoding="utf-8"))
    ok = [r for r in d if r.get("operating_status") == "open" and r.get("taxonomy_primary") in ("vegan_restaurant", "vegetarian_restaurant")
          and r.get("address") and (r.get("confidence") or 0) >= 0.7]
    ok.sort(key=lambda r: (r["taxonomy_primary"] != "vegan_restaurant", -(r["confidence"] or 0), r.get("name") or "", r.get("id") or ""))
    out = [{k: r.get(k) for k in KEEP} for r in ok[:10]]
    write(f"data/overture/reference_{city}_top10.json", out)
    print(len(ok), "eligible")

def wedding(city: str) -> None:
    d = json.loads(Path(f"data/overture/wedding_{city}.json").read_text(encoding="utf-8"))
    ok = [r for r in d if r.get("operating_status") == "open" and r.get("taxonomy_primary") == "event_venue"
          and r.get("address") and (r.get("confidence") or 0) >= 0.7]
    ok.sort(key=lambda r: (-(r.get("confidence") or 0), r.get("name") or "", r.get("id") or ""))
    out = [{k: r.get(k) for k in KEEP} for r in ok[:10]]
    write(f"data/overture/reference_wedding_{city}_top10.json", out)
    print(len(ok), "eligible")

if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "wedding":
        wedding(args[1] if len(args) > 1 else "denver")
    else:
        vegan(args[0] if args else "denver")
