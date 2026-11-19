"""Append-only spend ledger with a hard cap. No keys are ever written here."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

LEDGER = Path(os.environ.get("AQH_LEDGER", "local/spend.jsonl"))
CAP_USD = float(os.environ.get("AQH_CAP_USD", "5.0"))


class SpendCapReached(RuntimeError):
    pass


def total(path: Path | None = None) -> float:
    p = path or LEDGER
    if not p.exists():
        return 0.0
    s = 0.0
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            s += float(json.loads(line).get("usd", 0))
        except (ValueError, json.JSONDecodeError):
            continue
    return s


def guard(path: Path | None = None) -> None:
    if total(path) >= CAP_USD:
        raise SpendCapReached(f"spend cap ${CAP_USD:.2f} reached ({total(path):.4f})")


def book(model: str, usd: float, tag: str = "", path: Path | None = None, **extra) -> None:
    p = path or LEDGER
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "model": model, "usd": round(float(usd or 0), 6), "tag": tag, **extra}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def by_model(path: Path | None = None) -> dict[str, float]:
    p = path or LEDGER
    out: dict[str, float] = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[r.get("model", "?")] = out.get(r.get("model", "?"), 0.0) + float(r.get("usd", 0))
    return out
