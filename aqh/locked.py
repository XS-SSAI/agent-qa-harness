"""Locked run settings: the same time limit, budget and flags for every agent.

Copy `run-config.json` into each results folder so a scorecard can be replayed
with the exact limits that were in force. Env vars may tighten a one-off run
(AQH_CAP_USD, AQH_TIMEOUT) but they are recorded next to the locked defaults.
"""
from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path

PATH = Path(__file__).with_name("locked.json")


def load() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))


def timeout_seconds() -> int:
    locked = int(load()["timeout_seconds"])
    raw = os.environ.get("AQH_TIMEOUT")
    return int(raw) if raw else locked


def cap_usd() -> float:
    locked = float(load()["cap_usd"])
    raw = os.environ.get("AQH_CAP_USD")
    return float(raw) if raw else locked


def max_turns() -> int:
    locked = int(load()["max_turns"])
    raw = os.environ.get("AQH_MAX_TURNS")
    return int(raw) if raw else locked


def snapshot(outdir: Path, **runtime) -> Path:
    """Write run-config.json beside the scorecard. Paths in runtime should be relative."""
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    doc = {
        "locked": load(),
        "runtime": {
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "timeout_seconds": timeout_seconds(),
            "cap_usd": cap_usd(),
            "max_turns": max_turns(),
            "platform": platform.platform(),
            **{k: v for k, v in runtime.items() if v is not None},
        },
    }
    dest = outdir / "run-config.json"
    dest.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest
