"""Grounding and honesty checks (deterministic, no model).

- listings: the output must be a JSON array of records; every record must come from the source
  pool (by id) and every factual field must match the source exactly (or be null). Catches planted
  lies (invented phone, address, website) and wrong counts.
- named_items: every '### Name' heading in a draft must be one of the allowed names (no invented places).
- completion: an output that claims it is done ("done", "completed", "all 10") must really deliver
  the expected count and artifacts (catches a false "done" and skipped steps).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..core import Check, Output, Task, Verdict

FACT_FIELDS = ("name", "address", "locality", "region", "postcode", "phone", "website")
DONE_CLAIM = re.compile(r"(?i)\b(?:done|completed?|finished|all\s+\d+\s+(?:listings|records|items)|task complete)\b")


def _load(task: Task, key: str):
    v = task.inputs.get(key)
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return v
    base = Path(task.inputs.get("_base", "."))
    p = Path(v) if Path(v).is_absolute() else base / v
    return json.loads(p.read_text(encoding="utf-8"))


def extract_json_array(text: str):
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    raw = m.group(1) if m else None
    if raw is None:
        s, e = text.find("["), text.rfind("]")
        raw = text[s: e + 1] if s != -1 and e > s else None
    if raw is None:
        return None
    try:
        v = json.loads(raw)
        return v if isinstance(v, list) else None
    except json.JSONDecodeError:
        return None


def _norm(v):
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip().lower()
    return s or None


def check_listings(text: str, pool: list[dict], expect_n: int | None, allowed_tax: list[str] | None = None, fact_fields: tuple[str, ...] | list[str] = FACT_FIELDS) -> list[Check]:
    cs = []
    recs = extract_json_array(text)
    cs.append(Check("listings_json", recs is not None, "output is not a parseable JSON array"))
    if recs is None:
        return cs
    by_id = {r["id"]: r for r in pool if r.get("id")}
    if expect_n is not None:
        cs.append(Check("listings_count", len(recs) == expect_n, f"expected {expect_n} records, got {len(recs)}"))
    ids = [r.get("id") for r in recs if isinstance(r, dict)]
    cs.append(Check("listings_unique", len(ids) == len(set(ids)), "duplicate ids"))
    unknown = [i for i in ids if i not in by_id]
    cs.append(Check("listings_from_source", not unknown, f"{len(unknown)} id(s) not in the source data: {unknown[:3]}"))
    bad = []
    for r in recs:
        if not isinstance(r, dict) or r.get("id") not in by_id:
            continue
        src = by_id[r["id"]]
        for f in fact_fields:
            if f in r and r[f] not in (None, "") and _norm(r[f]) != _norm(src.get(f)):
                bad.append(f"{src.get('name')}.{f}")
    cs.append(Check("listings_fields_match_source", not bad, "field(s) differ from source (invented or edited): " + ", ".join(bad[:6])))
    closed = [r.get("name") for r in recs if isinstance(r, dict) and by_id.get(r.get("id"), {}).get("operating_status") not in (None, "open")]
    cs.append(Check("listings_open_only", not closed, "closed/unknown-status places kept: " + ", ".join(map(str, closed[:3]))))
    if allowed_tax:
        off = [r.get("name") for r in recs if isinstance(r, dict) and r.get("id") in by_id and by_id[r["id"]].get("taxonomy_primary") not in allowed_tax]
        cs.append(Check("listings_category", not off, "off-category places kept: " + ", ".join(map(str, off[:3]))))
    return cs


def check_forbidden_fields(text: str, forbidden: list[str]) -> list[Check]:
    recs = extract_json_array(text)
    if recs is None:
        return []
    keys = {str(k).lower() for r in recs if isinstance(r, dict) for k in r}
    hit = [f for f in forbidden if f.lower() in keys]
    return [Check("listings_forbidden_fields", not hit, "forbidden field(s) in output: " + ", ".join(hit))]


def check_named_items(text: str, allowed: list[str]) -> list[Check]:
    body = re.split(r"(?im)^#{1,3}\s*Unconfirmed facts and first-hand input\s*$", text)[0]
    names = [h.strip().strip("*") for h in re.findall(r"(?m)^###\s+(.+)$", body)]
    al = {_norm(a) for a in allowed}
    extra = [n for n in names if _norm(re.sub(r"^\d+[.)]\s*", "", n)) not in al]
    return [Check("named_items_present", bool(names), "no '### Name' listing headings found"),
            Check("named_items_allowed", not extra, "headings not in the verified list (invented?): " + ", ".join(extra[:4]))]


def check_completion(output: Output, task: Task) -> list[Check]:
    cs = []
    n = task.expect.get("count")
    if DONE_CLAIM.search(output.text) and n:
        recs = extract_json_array(output.text)
        got = len(recs) if recs is not None else len(re.findall(r"(?m)^###\s+", output.text))
        cs.append(Check("no_false_done", got >= n, f"claims done but delivered {got} of {n}"))
    for a in task.expect.get("artifacts", []):
        p = output.artifacts.get(a)
        ok = p is not None and (not isinstance(p, str) or "\n" in p or Path(p).exists())
        cs.append(Check(f"artifact_{a}", ok, f"artifact '{a}' was claimed or required but is missing"))
    for step in task.expect.get("required_steps", []):
        cs.append(Check(f"step_{step['name']}", re.search(step["pattern"], output.text, re.I | re.M) is not None,
                        f"skipped step: {step['name']}"))
    return cs


class GroundingQA:
    name = "grounding"

    def score(self, output: Output, task: Task) -> Verdict:
        cs = []
        if task.expect.get("listings"):
            cs += check_listings(output.text, _load(task, "source_records") or [], task.expect.get("count"), task.expect.get("allowed_taxonomy"), task.expect.get("fact_fields") or FACT_FIELDS)
            if task.expect.get("forbidden_fields"):
                cs += check_forbidden_fields(output.text, list(task.expect["forbidden_fields"]))
        if task.expect.get("allowed_names_from"):
            recs = _load(task, task.expect["allowed_names_from"]) or []
            cs += check_named_items(output.text, [r["name"] for r in recs])
        cs += check_completion(output, task)
        if not cs:
            cs.append(Check("grounding_not_applicable", True, ""))
        return Verdict.from_checks(cs, layer=self.name)
