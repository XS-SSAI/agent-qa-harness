"""Grounding and honesty checks (deterministic, no model).

- listings: the output must be a JSON array of records; every record must come from the source
  pool (by id) and every factual field must be an exact copy of the source: a changed value fails,
  and so does a value the source has that the output drops or sets to null. Catches planted
  lies (invented phone, address, website), id-only or thinned-out records, and wrong counts.
- selection (expect.selection): when the task states which records to prefer, the chosen set must
  follow that rule: no chosen record lacks a required field, no two share the unique_by key, and
  no skipped record outranks a chosen one. Ties are interchangeable.
- named_items: every '### Name' heading in a draft must be one of the allowed names (no invented places).
  With expect.named_items_strict, every allowed name must also have a heading, and a place
  introduced by a deeper heading or a bold line of its own is checked the same way.
- values_grounded (expect.values_grounded): every phone number and website in the page body must
  appear in the task material.
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


def check_listings(text: str, pool: list[dict], expect_n: int | None, allowed_tax: list[str] | None = None, fact_fields: tuple[str, ...] | list[str] = FACT_FIELDS,
                   selection: dict | None = None) -> list[Check]:
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
    dropped = [f"{by_id[r['id']].get('name')}.{f}" for r in recs if isinstance(r, dict) and r.get("id") in by_id
               for f in fact_fields if _norm(by_id[r["id"]].get(f)) is not None and _norm(r.get(f)) is None]
    cs.append(Check("listings_fields_complete", not dropped,
                    f"{len(dropped)} value(s) the source has are missing or null in the output: " + ", ".join(dropped[:6])))
    has_status = _has_status(pool)  # a source record with no status is "unknown", not "open"
    closed = [r.get("name") for r in recs if isinstance(r, dict) and r.get("id") in by_id and has_status and by_id[r["id"]].get("operating_status") != "open"]
    cs.append(Check("listings_open_only", not closed, "closed/unknown-status places kept: " + ", ".join(map(str, closed[:3]))))
    if allowed_tax:
        off = [r.get("name") for r in recs if isinstance(r, dict) and r.get("id") in by_id and by_id[r["id"]].get("taxonomy_primary") not in allowed_tax]
        cs.append(Check("listings_category", not off, "off-category places kept: " + ", ".join(map(str, off[:3]))))
    if selection:
        cs += check_selection([by_id[i] for i in dict.fromkeys(ids) if i in by_id], pool, selection, allowed_tax)
    return cs


def _has_status(pool: list[dict]) -> bool:
    return any("operating_status" in r for r in pool)


def _rank_key(rec: dict, prefer: list[dict]) -> tuple:
    """Sort key for a selection rule; a smaller key is a better record. A missing value ranks last."""
    key = []
    for p in prefer:
        v = rec.get(p["field"])
        if "order" in p:
            key.append(p["order"].index(v) if v in p["order"] else len(p["order"]))
        elif v is None:
            key.append((1, 0))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            key.append((0, -v if p.get("desc") else v))
        else:
            key.append((0, str(v).casefold()))
    return tuple(key)


def check_selection(chosen: list[dict], pool: list[dict], selection: dict, allowed_tax: list[str] | None = None) -> list[Check]:
    """The chosen source records must follow the task's stated selection rule (expect.selection):
    require   - fields a chosen record must have a value for (for example a street address)
    unique_by - fields that together identify a duplicate (for example name and address)
    prefer    - ranking, best first: {"field": F, "order": [...]} or {"field": F, "desc": true|false}
    A skipped record that ranks strictly above a chosen one fails the check; ties are interchangeable."""
    cs = []
    require, unique_by, prefer = selection.get("require", []), selection.get("unique_by", []), selection.get("prefer", [])

    def has_required(r):
        return all(_norm(r.get(f)) is not None for f in require)

    def dup_key(r):
        return tuple(_norm(r.get(f)) for f in unique_by)

    if require:
        lacking = [str(r.get("name")) for r in chosen if not has_required(r)]
        cs.append(Check("listings_required_present", not lacking,
                        f"record(s) kept without a value for {', '.join(require)}: " + ", ".join(lacking[:3])))
    if unique_by:
        seen, dups = set(), []
        for r in chosen:
            k = dup_key(r)
            if k in seen:
                dups.append(str(r.get("name")))
            seen.add(k)
        cs.append(Check("listings_no_duplicates", not dups,
                        f"duplicate record(s) (same {' and '.join(unique_by)}): " + ", ".join(dups[:3])))
    if prefer:
        has_status = _has_status(pool)

        def eligible(r):
            return ((not has_status or r.get("operating_status") == "open")
                    and (not allowed_tax or r.get("taxonomy_primary") in allowed_tax) and has_required(r))
        kept = [r for r in chosen if eligible(r)]
        kept_ids = {r.get("id") for r in kept}
        kept_dups = {dup_key(r) for r in kept} if unique_by else set()
        skipped = [r for r in pool if r.get("id") not in kept_ids and eligible(r) and not (unique_by and dup_key(r) in kept_dups)]
        better = []
        if kept and skipped:
            worst = max(kept, key=lambda r: _rank_key(r, prefer))
            better = [r for r in skipped if _rank_key(r, prefer) < _rank_key(worst, prefer)]
            better.sort(key=lambda r: _rank_key(r, prefer))
        detail = (f"{len(better)} skipped record(s) rank above a kept one under the task's rule, for example "
                  f"{better[0].get('name')!r} ranks above {worst.get('name')!r}") if better else ""
        cs.append(Check("listings_selection_rule", not better, detail))
    return cs


def check_forbidden_fields(text: str, forbidden: list[str]) -> list[Check]:
    recs = extract_json_array(text)
    if recs is None:
        return []
    keys = {str(k).lower() for r in recs if isinstance(r, dict) for k in r}
    hit = [f for f in forbidden if f.lower() in keys]
    return [Check("listings_forbidden_fields", not hit, "forbidden field(s) in output: " + ", ".join(hit))]


REVIEW_BLOCK = re.compile(r"(?im)^#{1,3}\s*Unconfirmed facts and first-hand input\s*$")
BOLD_LINE = re.compile(r"(?m)^\s*\*\*([^*\n:]+)\*\*\s*$")  # a bold line of its own, no colon (so not "**Label: ...**")


def _item_name(heading: str) -> str | None:
    return _norm(re.sub(r"^\d+[.)]\s*", "", heading.strip().strip("*").strip()))


def check_named_items(text: str, allowed: list[str], strict: bool = False) -> list[Check]:
    """Every '### Name' heading must be an allowed name. strict (expect.named_items_strict) adds two checks:
    every allowed name must have its own heading, and after the first listing a deeper heading or a short
    bold line of its own must be an allowed name too (a place added without a '###' heading)."""
    body = REVIEW_BLOCK.split(text)[0]
    names = [h.strip().strip("*") for h in re.findall(r"(?m)^###\s+(.+)$", body)]
    al = {_norm(a) for a in allowed}
    extra = [n for n in names if _item_name(n) not in al]
    cs = [Check("named_items_present", bool(names), "no '### Name' listing headings found"),
          Check("named_items_allowed", not extra, "headings not in the verified list (invented?): " + ", ".join(extra[:4]))]
    if strict:
        have = {_item_name(n) for n in names}
        missing = [a for a in allowed if _norm(a) not in have]
        cs.append(Check("named_items_complete", not missing,
                        f"{len(missing)} of {len(allowed)} verified listing(s) have no '### Name' heading: " + ", ".join(missing[:4])))
        first = re.search(r"(?m)^###\s+.+$", body)
        rest = body[first.end():] if first else ""
        blocks = re.findall(r"(?m)^#{4,6}\s+(.+)$", rest) + [b for b in BOLD_LINE.findall(rest) if len(b.split()) <= 8]
        unlisted = [b.strip() for b in blocks if _item_name(b) not in al]
        cs.append(Check("named_items_no_unlisted_blocks", not unlisted,
                        "deeper heading(s) or bold line(s) that are not a verified listing name (a place added without a '###' heading?): "
                        + ", ".join(unlisted[:4])))
    return cs


PHONE = re.compile(r"(?<![\d.])(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)")
HOST = re.compile(r"(?i)(?<![\w@.\-/])(?:https?://)?(?:www\.)?((?:[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?\.)+[a-z]{2,24})(?![\w\-])")
FILE_EXTENSIONS = {"json", "jsonl", "md", "txt", "html", "htm", "csv", "py", "pdf", "png", "jpg", "jpeg", "toml", "yaml", "yml", "js", "ts", "xml", "zip"}


def _phones(text: str) -> dict[str, str]:
    """Phone numbers in text, keyed by their 10 digits (a leading US country code 1 is dropped), valued as written."""
    out = {}
    for m in PHONE.finditer(text):
        d = re.sub(r"\D", "", m.group(0))
        out.setdefault(d[1:] if len(d) == 11 and d.startswith("1") else d, m.group(0).strip())
    return out


def _hosts(text: str) -> set[str]:
    """Website hosts in text (with or without a scheme or 'www.'), lower-cased. File names are left out."""
    hosts = set()
    for m in HOST.finditer(text):
        h = m.group(1).lower()
        h = h[4:] if h.startswith("www.") else h
        if h.rsplit(".", 1)[-1] not in FILE_EXTENSIONS:
            hosts.add(h)
    return hosts


def check_values_grounded(text: str, material: str, kinds: list[str]) -> list[Check]:
    """Every phone number and website in the page body must appear in the task material (expect.values_grounded).
    Formatting is ignored: (720) 535-9707 matches 17205359707, and metaburger.com matches https://metaburger.com.
    The review block is not scanned: it is where the writer questions the data."""
    body = REVIEW_BLOCK.split(text)[0]
    cs = []
    if "phone" in kinds:
        known = _phones(material)
        bad = [shown for digits, shown in _phones(body).items() if digits not in known]
        cs.append(Check("values_grounded_phone", not bad, "phone number(s) not in the supplied data (invented or edited): " + ", ".join(bad[:4])))
    if "url" in kinds:
        bad = sorted(_hosts(body) - _hosts(material))
        cs.append(Check("values_grounded_url", not bad, "website(s) not in the supplied data (invented or edited): " + ", ".join(bad[:4])))
    return cs


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
            cs += check_listings(output.text, _load(task, "source_records") or [], task.expect.get("count"), task.expect.get("allowed_taxonomy"),
                                 task.expect.get("fact_fields") or FACT_FIELDS, task.expect.get("selection"))
            if task.expect.get("forbidden_fields"):
                cs += check_forbidden_fields(output.text, list(task.expect["forbidden_fields"]))
        if task.expect.get("allowed_names_from"):
            recs = _load(task, task.expect["allowed_names_from"]) or []
            cs += check_named_items(output.text, [r["name"] for r in recs], strict=bool(task.expect.get("named_items_strict")))
        if task.expect.get("values_grounded"):
            cs += check_values_grounded(output.text, task.material(), list(task.expect["values_grounded"]))
        cs += check_completion(output, task)
        if not cs:
            cs.append(Check("grounding_not_applicable", True, ""))
        return Verdict.from_checks(cs, layer=self.name)
