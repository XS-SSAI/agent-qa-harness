"""Deterministic publish gate, driven by a rulebook file (TOML, stdlib tomllib).

Ported from a private production gate and made generic: every owner-specific rule
(names, brands, banned shorthands, prices, competitors) now lives in a rulebook, not in code.
The built-in checks that stay in code are universal: hidden unicode, secret-shaped values,
and the posted-topic overlap test.

CLI:  python -m aqh.qa.gate --kind article --rulebook rulebooks/example.toml draft.md
exit 0 PASS, 1 FAIL, 2 usage/read error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

from ..core import Check, Output, Task, Verdict

HIDDEN_UNICODE = re.compile(
    "[\u200B\u200C\u2060\uFEFF\u180E\u200E\u200F\u202A-\u202E\u2066-\u2069\U000E0001\U000E0020-\U000E007F]"
)
SECRET = [
    ("api_key", re.compile(r"\bsk-(?:ant-|proj-|or-)?[A-Za-z0-9_\-]{20,}")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("slack_token", re.compile(r"\bxox[abeprs]-[A-Za-z0-9\-]{10,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
]
DEFAULT_RULEBOOK = Path(__file__).resolve().parents[2] / "rulebooks" / "example.toml"

STOP = set("""about after already around article been before being check draft every first from have into just must need
post posted posts ready rules that their them then this those time used using with your year years""".split())


def load_rulebook(path: str | Path | None) -> dict:
    p = Path(path) if path else DEFAULT_RULEBOOK
    if tomllib is None:
        raise RuntimeError("Python 3.11+ is required (tomllib)")
    with p.open("rb") as f:
        rb = tomllib.load(f)
    rb["_path"] = str(p)
    return rb


def load_events(path: str | Path | None) -> list[dict]:
    if not path or not Path(path).is_file():
        return []
    out = []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return out


def _phrases(text: str) -> set[str]:
    toks = [w for w in re.findall(r"[a-z0-9%]{3,}", text.lower()) if w not in STOP and not w.isdigit()]
    ph = set()
    for n in (3, 4):
        for i in range(len(toks) - n + 1):
            ph.add(" ".join(toks[i:i + n]))
    return ph


def posted_topic_hits(text: str, events: list[dict]) -> list[str]:
    """A draft that repeats a topic already marked 'posted' fails (3-4 word overlaps, >=2 hits)."""
    d = _phrases(text)
    out = []
    for ev in events:
        if ev.get("type") != "posted":
            continue
        hits = [p for p in _phrases(ev.get("text", "")) if p in d]
        if len(hits) >= 2:
            out.append(f"repeats a posted topic ({ev.get('date', '')}): {', '.join(sorted(hits)[:3])}")
    return out


def _applies(rule: dict, kind: str) -> bool:
    kinds = rule.get("kinds", ["*"])
    return "*" in kinds or kind in kinds


def check_text(text: str, kind: str, rulebook: dict, events: list[dict] | None = None, label: str = "draft") -> list[Check]:
    checks: list[Check] = []

    def add(name, ok, detail=""):
        checks.append(Check(name, ok, detail))

    add("hidden_unicode", not HIDDEN_UNICODE.search(text), "zero-width, bidi or tag character found; strip it")
    leaks = [n for n, pat in SECRET if pat.search(text)]
    add("secret_values", not leaks, f"secret-shaped value ({', '.join(leaks)}); value hidden")

    env_names = rulebook.get("secrets", {}).get("env_names", [])
    if env_names:
        alt = "|".join(map(re.escape, env_names))
        pat = re.compile(r"\b(?:" + alt + r")\s*[:=]\s*['\"]?(?!\[|<|\$|\*{3}|hidden)[^\s'\"]{8,}")
        add("secret_env_values", not pat.search(text), "an env var is printed with a value; value hidden")

    prefixes = rulebook.get("paths", {}).get("banned_prefixes", [])
    if prefixes:
        alt = "|".join(re.escape(p.rstrip("/")) for p in prefixes)
        pat = re.compile(r"(?<![A-Za-z0-9_])(?:" + alt + r")(?:[/\\][^\s`\"'<>)\]},;]*)?")
        found = sorted({m.group(0).rstrip(".,;:!?") for m in pat.finditer(text)})
        add("private_paths", not found, "private path(s): " + ", ".join(found[:5]))

    for i, rule in enumerate(rulebook.get("banned", [])):
        if not _applies(rule, kind):
            continue
        if rule.get("label_contains") and not re.search(rule["label_contains"], label, re.I):
            continue
        pat = re.compile(rule["pattern"], 0 if rule.get("case_sensitive") else re.I)
        m = pat.search(text)
        add(rule.get("name", f"banned_{i}"), not m, rule.get("message", "banned pattern") + (f' ("{m.group(0)[:40]}")' if m else ""))

    for i, rule in enumerate(rulebook.get("required", [])):
        if not _applies(rule, kind):
            continue
        ok = re.search(rule["pattern"], text, re.I | re.M) is not None
        add(rule.get("name", f"required_{i}"), ok, rule.get("message", f"missing {rule['pattern']}"))

    if events and kind in rulebook.get("dedupe", {}).get("kinds", []):
        hits = posted_topic_hits(text, events)
        add("posted_topic", not hits, "; ".join(hits))
    return checks


class GateQA:
    """QA layer wrapper: score(output, task) -> Verdict."""

    name = "gate"

    def __init__(self, rulebook: str | Path | None = None, events: str | Path | None = None):
        self.rulebook = load_rulebook(rulebook)
        self.events = load_events(events or self.rulebook.get("dedupe", {}).get("events_file"))

    def score(self, output: Output, task: Task) -> Verdict:
        cs = check_text(output.text, task.kind, self.rulebook, self.events, label=task.id)
        return Verdict.from_checks(cs, layer=self.name, rulebook=Path(self.rulebook["_path"]).name)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Gate a draft against a rulebook")
    ap.add_argument("draft", help="file, or - for stdin")
    ap.add_argument("--kind", required=True)
    ap.add_argument("--rulebook", default=None)
    ap.add_argument("--events", default=None)
    ap.add_argument("--label", default="draft")
    a = ap.parse_args(argv)
    try:
        text = sys.stdin.read() if a.draft == "-" else Path(a.draft).read_text(encoding="utf-8")
        rb = load_rulebook(a.rulebook)
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    cs = check_text(text, a.kind, rb, load_events(a.events), a.label)
    bad = [c for c in cs if not c.passed]
    print("FAIL" if bad else "PASS")
    for c in bad:
        print(f"- {c.name}: {c.detail}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
