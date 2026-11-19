"""Judge calibration (scoring v2): run before final runs; a misgrading judge aborts the run.

For each task type in calibration/cases.json there is one known-good answer and one known-bad answer.
Every judge layer in the --qa spec must PASS the good one and FAIL the bad one. A judge that cannot run
(after retries) also aborts: an unverified judge must not grade a final run.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .core import Output, Task
from .qa import build_qa
from .qa.judge import JudgeQA

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "calibration" / "cases.json"


def judge_layers(qa_spec: str) -> list[JudgeQA]:
    return [l for l in build_qa(qa_spec or "default+judge").layers if isinstance(l, JudgeQA)]


def run_calibration(qa_spec: str, cases_path: Path = CASES) -> dict:
    from .runner import SCORING_VERSION
    doc = json.loads(Path(cases_path).read_text(encoding="utf-8"))
    judges = judge_layers(qa_spec)
    results, ok = [], bool(judges)
    for case in doc["cases"]:
        task = Task.load(ROOT / case["task"])
        for kind in ("good", "bad"):
            text = (ROOT / case[kind]).read_text(encoding="utf-8")
            out = Output(text=text, meta={"agent": "calibration", "model": "claude-code"})  # any non-judge family; fixtures came from Codex and Claude Code
            for j in judges:
                v = j.score(out, task)
                errored = any(c.name in ("judge_ran", "judge2_available", "cross_family", "judge_input") and not c.passed for c in v.checks)
                expected = kind == "good"
                correct = (not errored) and v.passed == expected
                ok = ok and correct
                results.append({"type": case["type"], "task": task.id, "answer": kind, "judge": j.name,
                                "judge_model": v.meta.get("judge_model"), "score": v.meta.get("score"),
                                "graded": "ERROR" if errored else ("PASS" if v.passed else "FAIL"),
                                "expected": "PASS" if expected else "FAIL", "correct": correct,
                                "usd": v.meta.get("usd"), "reasons": v.reasons[:3]})
    return {"scoring": SCORING_VERSION, "qa": qa_spec, "judges": [j.name for j in judges], "passed": ok,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "results": results,
            "note": "" if judges else "no judge layer in the qa spec: nothing to calibrate"}


def ensure_calibrated(qa_spec: str, outdir: Path, runner=run_calibration) -> dict:
    """Reuse a passing calibration.json in outdir for the same scoring version and judges; else run it."""
    from .runner import SCORING_VERSION
    outdir = Path(outdir)
    dest = outdir / "calibration.json"
    names = [j.name for j in judge_layers(qa_spec)]
    if dest.exists():
        try:
            prev = json.loads(dest.read_text(encoding="utf-8"))
            if prev.get("passed") and prev.get("scoring") == SCORING_VERSION and prev.get("judges") == names:
                prev["reused"] = True
                return prev
        except json.JSONDecodeError:
            pass
    res = runner(qa_spec)
    outdir.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return res


def summary_lines(res: dict) -> list[str]:
    lines = [f"calibration: {'PASSED' if res['passed'] else 'FAILED'} ({', '.join(res['judges']) or 'no judges'})"]
    for r in res["results"]:
        mark = "ok " if r["correct"] else "BAD"
        lines.append(f"  {mark} {r['judge']:13} {r['type']:17} {r['answer']:4} expected {r['expected']}, graded {r['graded']} (score {r['score']})")
    return lines
