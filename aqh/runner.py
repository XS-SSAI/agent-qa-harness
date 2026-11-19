"""Run tasks through agents, score them, write results.jsonl + a scorecard (markdown + CSV)."""
from __future__ import annotations

import csv
import re
import json
import time
import traceback
from dataclasses import asdict
from pathlib import Path

from .core import Output, Task, Verdict

SCORING_VERSION = "aqh-scoring-v3"

# Scoring v2 verdicts: PASS, FAIL, ERROR. ERROR = the result says nothing about the agent's work
# (agent-side credit/quota/auth/missing-key failure, or a judge that did not run). ERROR rows are left out
# of pass rates and judge agreement and are flagged for a rerun/rescore. A failed deterministic check
# (gate, unconfirmed block, grounding) still makes the row FAIL, because no judge result can change it.
INFRA_ERROR = re.compile(
    r"requires more credits|insufficient (?:credit|funds|balance|quota)|exceed(?:s|ed)? your (?:available )?credits|"
    r"\bHTTP 40[123]\b|\b(?:401|402|403)\b.{0,40}(?:unauthori[sz]ed|forbidden|payment)|quota|rate.?limit|\b429\b|"
    r"usage limit|credit balance|out of credits|is not set|api key|unauthori[sz]ed|authenticat|not logged in|"
    r"please (?:log|sign) ?in|login required|spend cap|not found on PATH",
    re.I)


def classify(agent_error: str | None, v: Verdict) -> tuple[str, str]:
    """Return (verdict, error_reason). verdict is PASS, FAIL or ERROR."""
    if agent_error:
        if INFRA_ERROR.search(agent_error):
            return "ERROR", f"agent infrastructure: {agent_error[:200]}"
        return "FAIL", ""
    if v.passed:
        return "PASS", ""
    judge_errors = [c for c in v.checks if c.name == "judge_ran" and not c.passed]
    hard_fail = [c for c in v.checks if not c.passed and c.name not in ("judge_ran", "judge_pass", "judge_score", "judge_no_invented_facts", "judge_majority")]
    if any(r.startswith("qa error:") for r in v.reasons):
        return "ERROR", "qa layer crashed"
    if judge_errors and not hard_fail:
        return "ERROR", "judge did not run: " + judge_errors[0].detail[:200]
    return "FAIL", ""


def verdict_of(r: dict) -> str:
    """Verdict of a saved row; rows from scoring v1 have no 'verdict' field."""
    return r.get("verdict") or ("PASS" if r.get("pass") else "FAIL")


def run_one(agent, task: Task, qa, mode: str = "owner-run") -> dict:
    t0 = time.time()
    try:
        out = agent.run(task)
        err = None
    except Exception as e:  # noqa: BLE001
        out, err = Output(text="", meta={"agent": getattr(agent, "name", "?")}), f"{type(e).__name__}: {e}"
    if err:
        v = Verdict(False, [], [f"agent error: {err[:300]}"], {})
    else:
        try:
            v = qa.score(out, task)
        except Exception as e:  # noqa: BLE001
            v = Verdict(False, [], [f"qa error: {type(e).__name__}: {e}"[:300]], {"trace": traceback.format_exc()[-600:]})
    passed_checks = sum(1 for c in v.checks if c.passed)
    verdict, error_reason = classify(err, v)
    judge_layers = [(name, m) for name, m in v.meta.get("layers", {}).items() if "score" in m]
    judge = judge_layers[0][1].get("score") if judge_layers else None
    judge2 = judge_layers[1][1].get("score") if len(judge_layers) > 1 else None
    judge3 = judge_layers[2][1].get("score") if len(judge_layers) > 2 else None
    jp = [bool(m.get("pass")) for _, m in judge_layers]
    agree = jp[0] == jp[1] if len(jp) >= 2 else None
    agree13 = jp[0] == jp[2] if len(jp) >= 3 else None
    agree23 = jp[1] == jp[2] if len(jp) >= 3 else None
    majority = (sum(jp) * 2 > len(jp)) if len(jp) >= 3 else None
    return {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "mode": mode, "task": task.id, "family": task.family,
        "data_label": task.data_label, "heldout": bool(getattr(task, "heldout", False)), "agent": getattr(agent, "name", "?"), "model": out.meta.get("model"),
        "qa": qa.name, "scoring": SCORING_VERSION, "verdict": verdict, "error": error_reason, "rerun": verdict == "ERROR",
        "deliverable_source": out.meta.get("deliverable_source", "stdout"), "pass": v.passed, "checks_passed": passed_checks, "checks_total": len(v.checks),
        "judge_score": judge, "judge2_score": judge2, "judge3_score": judge3, "judge_agree": agree,
        "judge13_agree": agree13, "judge23_agree": agree23, "judge_majority_pass": majority, "judge_passes": jp,
        "judge_votes": v.meta.get("judge_votes"), "reasons": v.reasons,
        "agent_usd": out.meta.get("usd"),
        "qa_usd": round(sum(float(m.get("usd") or 0) for m in v.meta.get("layers", {}).values()), 6),
        "seconds": round(time.time() - t0, 1), "output": out.text, "checks": [asdict(c) for c in v.checks], "qa_layers": v.meta.get("layers", {}),
    }


SECRET_SHAPE = [
    re.compile(r"\bsk-(?:ant-|proj-|or-)?[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\bxai-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
REVIEW_LINES, REVIEW_CHARS = 40, 1200


def _sample(text: str) -> str:
    raw = text or "(no output)"
    for pat in SECRET_SHAPE:
        raw = pat.sub("[hidden]", raw)
    lines = raw.splitlines()
    cut = False
    if len(lines) > REVIEW_LINES:
        lines, cut = lines[:REVIEW_LINES], True
    body = "\n".join(lines)
    if len(body) > REVIEW_CHARS:
        head = body[:REVIEW_CHARS]
        body, cut = (head.rsplit("\n", 1)[0] if "\n" in head else head), True
    if cut:
        body += "\n… (truncated; see the full file)"
    return body


def write_review(outdir: Path, latest: dict, agents: list[str], tasks: list[str]) -> Path:
    """Short per-agent samples next to the scorecard, for a human read of the actual output."""
    md = ["# Output review", "",
          "Short samples of each agent's deliverable, to read next to the scorecard. "
          "The full text is in `outputs/`. Secret-shaped strings are hidden.", "",
          f"Scoring: {SCORING_VERSION}. Verdicts are PASS, FAIL or ERROR. ERROR means the row says nothing about the "
          "agent's work (credit/quota/auth/missing-key failure on the agent side, or a judge that did not run after "
          "retries); it is left out of pass rates and judge agreement and must be rerun or rescored. When an agent's "
          "stdout was only narration, the deliverable file it saved in its workdir is scored and marked "
          "'scored from file:NAME'.", ""]
    for a in agents:
        md += [f"## {a}", ""]
        for tname in tasks:
            r = latest.get((a, tname))
            if not r:
                continue
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{a}__{tname}")
            held = " (held-out)" if r.get("heldout") else ""
            bits = [verdict_of(r)]
            if r.get("deliverable_source", "stdout") != "stdout":
                bits.append(f"scored from {r['deliverable_source']}")
            if r.get("judge_score") is not None:
                bits.append(f"judge {r['judge_score']}")
            md += [f"### {tname}{held} — {', '.join(bits)}", "",
                   f"Full output: `outputs/{safe}.md`", "",
                   "```", _sample(r.get("output") or ""), "```", ""]
    dest = outdir / "REVIEW.md"
    dest.write_text("\n".join(md) + "\n", encoding="utf-8")
    return dest



def save(rows: list[dict], outdir: Path) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    with (outdir / "results.jsonl").open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    for r in rows:
        (outdir / "outputs").mkdir(exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{r['agent']}__{r['task']}")
        (outdir / "outputs" / f"{safe}.md").write_text(r["output"] or "(no output)", encoding="utf-8")
    return scorecard(outdir)


def scorecard(outdir: Path) -> Path:
    rows = [json.loads(l) for l in (outdir / "results.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    latest = {}
    for r in rows:
        latest[(r["agent"], r["task"])] = r
    agents = sorted({a for a, _ in latest})
    tasks = sorted({t for _, t in latest})
    md = ["# Scorecard", "", f"Run folder: {outdir.name}. Mode: {', '.join(sorted({r['mode'] for r in rows}))}.", "",
          f"Scoring: {SCORING_VERSION}. Passed = PASS / (PASS + FAIL); ERROR rows are left out and listed under 'Rerun needed'.", "",
          "| Agent | " + " | ".join(tasks) + " | Passed | ERROR |", "|---|" + "---|" * (len(tasks) + 2)]
    for a in agents:
        cells, n, n_err = [], 0, 0
        for t in tasks:
            r = latest.get((a, t))
            if not r:
                cells.append("-")
                continue
            vd = verdict_of(r)
            n += vd == "PASS"
            n_err += vd == "ERROR"
            bits = []
            if r.get("judge_score") is not None:
                bits.append(f"judge {r['judge_score']}")
            if r.get("judge2_score") is not None:
                bits.append(f"judge2 {r['judge2_score']}")
            if r.get("judge_agree") is not None:
                bits.append("agree" if r["judge_agree"] else "disagree")
            extra = (", " + ", ".join(bits)) if bits else ""
            cells.append(f"{vd} ({r['checks_passed']}/{r['checks_total']}{extra})")
        scored = len([t for t in tasks if (a, t) in latest]) - n_err
        md.append(f"| {a} | " + " | ".join(cells) + f" | {n}/{scored} | {n_err} |")
    md += ["", "## Why each FAIL failed", ""]
    for (a, t), r in sorted(latest.items()):
        if verdict_of(r) == "FAIL":
            md.append(f"- **{a} / {t}**: " + "; ".join(r["reasons"])[:600])
    errs = [(k, r) for k, r in sorted(latest.items()) if verdict_of(r) == "ERROR"]
    if errs:
        md += ["", "## Rerun needed (ERROR)", ""]
        for (a, t), r in errs:
            md.append(f"- **{a} / {t}**: {r.get('error') or '; '.join(r['reasons'])[:300]}")
    agree_rows = [r for r in latest.values() if r.get("judge2_score") is not None and r.get("judge_score") is not None and verdict_of(r) != "ERROR"]
    if agree_rows:
        n_ag = sum(1 for r in agree_rows if r.get("judge_agree"))
        md += ["", "## Judge agreement", "",
               f"{n_ag}/{len(agree_rows)} tasks: both judges reached the same pass/fail verdict.", ""]
        for (a, t), r in sorted(latest.items()):
            if r not in agree_rows:
                continue
            delta = abs(float(r["judge_score"]) - float(r["judge2_score"])) if r.get("judge_score") is not None else ""
            md.append(f"- **{a} / {t}**: judge {r.get('judge_score')}, judge2 {r.get('judge2_score')}, "
                      f"{'agree' if r.get('judge_agree') else 'disagree'}" + (f", score delta {delta}" if delta != "" else ""))
    held = [tname for tname in tasks if any(latest.get((a, tname), {}).get("heldout") for a in agents)]
    if held:
        md += ["", "## Held-out tasks", "",
               "These tasks are frozen for final scoring and were included because this run used --include-heldout: "
               + ", ".join(held) + "."]
    (outdir / "scorecard.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    write_review(outdir, latest, agents, tasks)
    with (outdir / "scorecard.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["agent", "task", "data_label", "mode", "verdict", "checks_passed", "checks_total", "judge_score", "judge2_score", "judge_agree", "agent_usd", "qa_usd", "seconds", "reasons"])
        for (a, t), r in sorted(latest.items()):
            w.writerow([a, t, r["data_label"], r["mode"], verdict_of(r), r["checks_passed"], r["checks_total"],
                        r.get("judge_score"), r.get("judge2_score"), r.get("judge_agree"), r.get("agent_usd"), r.get("qa_usd"), r["seconds"], " | ".join(r["reasons"])[:800]])
    return outdir / "scorecard.md"
