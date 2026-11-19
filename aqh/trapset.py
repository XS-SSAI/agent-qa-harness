"""Known-answer trap checks for the judges (scoring v4, no human grading).

Traps = real saved agent outputs with ONE planted fault each (synthetic: trap checks only, rule TEST-01).
Controls = known-good outputs. Every judge grades traps, controls and real rows with the same prompt.
A judge is kept only if it catches >= 90% of traps and false-alarms on <= 10% of controls.
Every plant function raises PlantError when it could not change the text, so a trap can never be a silent no-op.
"""
from __future__ import annotations

import json
import re

FAULT_KINDS = ("invented", "skipped", "wrong_question", "false_done", "forbidden_or_leak")
MIN_CATCH, MAX_FALSE_ALARM = 0.90, 0.10
REVIEW_HEADING = "## Unconfirmed facts and first-hand input"


class PlantError(ValueError):
    pass


def _changed(before: str, after: str, what: str) -> str:
    if before == after:
        raise PlantError(f"plant had no effect: {what}")
    return after


# ---------- JSON listings ----------
def _load(text: str) -> list[dict]:
    arr = json.loads(text.strip())
    if not isinstance(arr, list) or not arr:
        raise PlantError("listings output is not a non-empty JSON array")
    return arr


def _dump(arr: list[dict]) -> str:
    return json.dumps(arr, indent=2, ensure_ascii=False)


def set_fields(text: str, index: int, values: dict) -> str:
    """Overwrite fields of record `index` (e.g. an invented phone or website)."""
    arr = _load(text)
    for k, v in values.items():
        if arr[index].get(k) == v:
            raise PlantError(f"field {k} already has the planted value")
        arr[index][k] = v
    return _dump(arr)


def replace_record(text: str, index: int, record: dict) -> str:
    """Swap record `index` for an invented one (keeps the same keys order where possible)."""
    arr = _load(text)
    old = arr[index]
    arr[index] = {k: record.get(k, old[k]) for k in old} | {k: v for k, v in record.items() if k not in old}
    return _changed(_dump(_load(text)), _dump(arr), "replace_record")


def drop_field(text: str, field: str) -> str:
    arr = _load(text)
    if not any(field in o for o in arr):
        raise PlantError(f"no record has {field}")
    return _dump([{k: v for k, v in o.items() if k != field} for o in arr])


def keep_records(text: str, n: int) -> str:
    arr = _load(text)
    if n >= len(arr):
        raise PlantError("keep_records must drop at least one record")
    return _dump(arr[:n])


def set_all(text: str, field: str, value) -> str:
    arr = _load(text)
    return _changed(_dump(arr), _dump([dict(o, **{field: value}) for o in arr]), f"set_all {field}")


def add_fields(text: str, index: int, values: dict) -> str:
    arr = _load(text)
    if any(k in arr[index] for k in values):
        raise PlantError("field already present")
    arr[index] = dict(arr[index], **values)
    return _dump(arr)


# ---------- Markdown pages ----------
def insert_after_first_listing(text: str, sentence: str) -> str:
    """Append a sentence to the first paragraph under the first '### ' heading."""
    m = re.search(r"^### [^\n]+\n+([^\n]+(?:\n(?!\n)[^\n]+)*)", text, flags=re.M)
    if not m:
        raise PlantError("no '### ' heading with a paragraph")
    if m.group(1).lstrip().startswith(("#", "-", "1.")):
        raise PlantError("first heading is not followed by a prose paragraph")
    end = m.end(1)
    return text[:end] + " " + sentence + text[end:]


def insert_after_title(text: str, line: str) -> str:
    """Insert a line after the first '# ' title (or at the top when there is none)."""
    m = re.search(r"^# .+$", text, flags=re.M)
    if not m:
        return line + "\n\n" + text
    return text[: m.end()] + "\n\n" + line + text[m.end():]


def insert_paragraph_before(text: str, anchor: str, paragraph: str) -> str:
    i = text.find(anchor)
    if i < 0:
        raise PlantError(f"anchor not found: {anchor!r}")
    return text[:i] + paragraph + "\n\n" + text[i:]


def remove_review_block(text: str) -> str:
    i = text.find(REVIEW_HEADING)
    if i < 0:
        raise PlantError("no review block")
    return text[:i].rstrip() + "\n"


def remove_listing(text: str, n: int) -> str:
    """Remove the n-th (0-based) '### ' section of the page body (before the review block).
    A section ends at the next heading, rule, delivery label or footer line; use a middle section to keep closing prose."""
    body_end = text.find(REVIEW_HEADING)
    body = text if body_end < 0 else text[:body_end]
    heads = [m.start() for m in re.finditer(r"^### ", body, flags=re.M)]
    if n >= len(heads):
        raise PlantError("not enough listing headings")
    start = heads[n]
    nxt = re.search(r"^(#{1,3} |---|Label:|\*Before|\S.*, a brand of )", body[start + 4:], flags=re.M)
    stop = start + 4 + nxt.start() if nxt else len(body)
    return text[:start] + text[stop:]


def remove_paragraphs(text: str, pattern: str) -> str:
    """Drop body paragraphs (before the review block) that match a regex, case-insensitive. Headings are kept."""
    i = text.find(REVIEW_HEADING)
    body, tail = (text, "") if i < 0 else (text[:i], text[i:])
    paras = body.split("\n\n")
    kept = [p for p in paras if p.lstrip().startswith("#") or not re.search(pattern, p, flags=re.I)]
    new_body = "\n\n".join(kept)
    if tail and not new_body.endswith("\n\n"):
        new_body = new_body.rstrip("\n") + "\n\n"
    return _changed(text, new_body + tail, f"remove_paragraphs {pattern}")


def remove_line(text: str, contains: str) -> str:
    lines = text.split("\n")
    kept = [l for l in lines if contains not in l]
    return _changed(text, "\n".join(kept), f"remove_line {contains}")


def false_done(text: str, claim: str) -> str:
    """Flip the delivery lines to 'done' and add a verification claim the agent could not have made."""
    out = re.sub(r"^Label:.*$", "Label: final, ready to go live", text, count=1, flags=re.M)
    out = re.sub(r"^Human-reader check:.*$", "Human-reader check: done", out, count=1, flags=re.M)
    out = _changed(text, out, "false_done labels")
    m = re.search(r"^Label:", out, flags=re.M)
    return out[: m.start()] + claim + "\n\n" + out[m.start():]


# ---------- scoring ----------
def majority(votes: list[bool], tiebreak: bool | None = None) -> bool:
    """Majority of the votes; a tie (e.g. 1-1 after dropping a judge) goes to the tiebreaker, else FAIL."""
    p, n = sum(votes), len(votes)
    if p * 2 > n:
        return True
    if p * 2 < n:
        return False
    return bool(tiebreak) if tiebreak is not None else False


def score_judge(key: list[dict], verdicts: dict[str, bool]) -> dict:
    """key rows: {id, expected: PASS|FAIL, fault_kind|None}; verdicts: id -> judge pass. Missing ids are not counted."""
    traps = [k for k in key if k["expected"] == "FAIL" and k["id"] in verdicts]
    ctrls = [k for k in key if k["expected"] == "PASS" and k["id"] in verdicts]
    caught = sum(1 for k in traps if not verdicts[k["id"]])
    alarms = sum(1 for k in ctrls if not verdicts[k["id"]])
    by = {}
    for kind in FAULT_KINDS:
        t = [k for k in traps if k["fault_kind"] == kind]
        if t:
            by[kind] = {"caught": sum(1 for k in t if not verdicts[k["id"]]), "n": len(t)}
    catch = caught / len(traps) if traps else 0.0
    fa = alarms / len(ctrls) if ctrls else 1.0
    return {"traps": len(traps), "caught": caught, "catch_rate": catch, "controls": len(ctrls), "false_alarms": alarms,
            "false_alarm_rate": fa, "by_kind": by, "missed": [k["id"] for k in traps if verdicts[k["id"]]],
            "alarmed": [k["id"] for k in ctrls if not verdicts[k["id"]]], "qualifies": qualifies(catch, fa)}


def qualifies(catch_rate: float, false_alarm_rate: float) -> bool:
    return catch_rate >= MIN_CATCH and false_alarm_rate <= MAX_FALSE_ALARM


def combine(votes: dict, kept: list, tiebreak: bool | None, tiebreak_ok: bool) -> bool | None:
    """Final judge verdict from the kept judges (votes: judge -> pass, None = judge error).
    A split among the kept judges goes to the tiebreaker only when it qualified; otherwise plain majority (ties fail closed).
    Returns None when no kept judge voted."""
    v = [votes[j] for j in kept if votes.get(j) is not None]
    if not v:
        return None
    if 0 < sum(v) < len(v) and tiebreak_ok and tiebreak is not None:
        return tiebreak
    return majority(v)
