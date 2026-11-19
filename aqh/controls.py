"""Known-good control check (scoring v4): script check of a listings output against the source data (used to pick known-good controls).
Returns (ok, problems). Strict: pure JSON array, exact expected set, exact field copies, no extra fields."""
import json
from pathlib import Path
REPO = Path(__file__).resolve().parents[1]
SPEC = {
    "listings-denver": dict(src="data/overture/vegan_denver.json", n=10, tax=["vegan_restaurant", "vegetarian_restaurant"],
                            fields=["id", "name", "address", "locality", "region", "postcode", "phone", "website"]),
    "listings-wedding-denver": dict(src="data/overture/wedding_denver.json", n=10, tax=["event_venue"],
                                    fields=["id", "name", "address", "locality", "region", "postcode", "phone", "website"]),
}
def expected_ids(task):
    s = SPEC[task]; src = json.loads((REPO / s["src"]).read_text())
    rows = [r for r in src if r.get("operating_status") == "open" and r.get("taxonomy_primary") in s["tax"] and (r.get("address") or "").strip()]
    seen, out = set(), []
    key = (lambda r: (r["taxonomy_primary"] != "vegan_restaurant", -r["confidence"])) if task == "listings-denver" else (lambda r: (-r["confidence"], r["name"]))
    for r in sorted(rows, key=key):
        k = (r["name"], r["address"])
        if k in seen: continue
        seen.add(k); out.append(r["id"])
    return out[: s["n"]]
def verify(task, text):
    s = SPEC[task]; src = {r["id"]: r for r in json.loads((REPO / s["src"]).read_text())}
    probs = []
    try:
        arr = json.loads(text.strip())
    except Exception:
        return False, ["not pure JSON"]
    if not isinstance(arr, list): return False, ["not an array"]
    if len(arr) != s["n"]: probs.append(f"count {len(arr)} != {s['n']}")
    ids = [o.get("id") for o in arr]
    if set(ids) != set(expected_ids(task)): probs.append("id set differs from rule-derived set")
    for o in arr:
        r = src.get(o.get("id"))
        if r is None: probs.append(f"unknown id {o.get('id')}"); continue
        for f in s["fields"]:
            if o.get(f) != r.get(f): probs.append(f"{o.get('id')} field {f} differs")
        extra = set(o) - set(s["fields"]) - {"check_before_publish"}
        if extra: probs.append(f"extra fields {sorted(extra)}")
        cbp = o.get("check_before_publish")
        if not isinstance(cbp, str) or len(cbp.split()) < 5: probs.append("check_before_publish missing/short")
    return not probs, probs
