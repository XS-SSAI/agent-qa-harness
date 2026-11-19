"""No model grades its own family's work. Unknown model names fail closed."""
from __future__ import annotations

import json
import re
from pathlib import Path

CFG = json.loads((Path(__file__).with_name("families.json")).read_text(encoding="utf-8"))["families"]
NEUTRAL = {"openrouter", "models", "nanobot", "v4", "pro", "flash", "mini", "latest", "api", "cli", "app"}


class SameFamily(ValueError):
    pass


class UnknownModel(ValueError):
    pass


def family(model: str) -> str:
    toks = [t for t in re.split(r"[/\s:_.\-]+", str(model or "").lower()) if t and t not in NEUTRAL and not t.isdigit()]
    found = {fam for t in toks for fam, pre in CFG.items() for p in pre if t.startswith(p)}
    if not found:
        raise UnknownModel(f"unknown model family for {model!r} (add it to families.json)")
    if len(found) > 1:
        raise UnknownModel(f"ambiguous model name {model!r}: {sorted(found)}")
    return found.pop()


def require_cross(worker: str, grader: str) -> bool:
    w, g = family(worker), family(grader)
    if g == "deterministic":
        return True
    if w == g:
        raise SameFamily(f"grader {grader!r} is the same family ({g}) as worker {worker!r}")
    return True
