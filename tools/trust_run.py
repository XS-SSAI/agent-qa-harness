"""Run a pass^3 trust-ladder suite end to end and record it with aqh.trust.

python tools/trust_run.py --eval-id E --family F --scope task|skill --agent A --tasks t1,t2 --qa QA --grader G
Each trial is an independent agent run, scored by the QA layer; evidence = what the checks really saw."""
import argparse
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from aqh import trust  # noqa: E402
from aqh.adapters import get_agent  # noqa: E402
from aqh.core import Task  # noqa: E402
from aqh.qa import build_qa  # noqa: E402
from aqh.runner import run_one, save  # noqa: E402

ap = argparse.ArgumentParser()
for k in ("eval-id", "family", "agent", "tasks", "qa", "grader", "worker"):
    ap.add_argument("--" + k, required=k not in ("worker",))
ap.add_argument("--scope", default="task")
ap.add_argument("--store", default="local/trust/ladder.jsonl")
ap.add_argument("--out", default="results/trust")
a = ap.parse_args()
tasks = a.tasks.split(",")
worker = a.worker or a.agent
st = ["--store", a.store]
rc = trust.main(["suite", "--eval-id", a.eval_id, "--family", a.family, "--scope", a.scope, "--tasks", ",".join(tasks),
                 "--worker", worker, "--grader", a.grader, *st])
if rc:
    sys.exit(rc)
rows = []
for t in tasks:
    task = Task.load(f"tasks/{t}.json")
    for n in (1, 2, 3):
        r = run_one(get_agent(a.agent), task, build_qa(a.qa), f"dry-run/trust:{a.eval_id}")
        rows.append(r)
        h = hashlib.sha256((r["output"] or "").encode()).hexdigest()[:10]
        ev = (f"{time.strftime('%H:%M:%S')} {a.agent} ran {t} (trial {n}); output sha {h}, {len(r['output'] or '')} chars; "
              f"checks {r['checks_passed']}/{r['checks_total']}" + (f"; judge {r['judge_score']}" if r.get("judge_score") is not None else "")
              + ("" if r["pass"] else "; failed: " + "; ".join(r["reasons"])[:300]))
        trust.main(["trial", "--eval-id", a.eval_id, "--task", t, "--trial", str(n), "--result", "PASS" if r["pass"] else "FAIL",
                    "--evidence", ev, "--self-verified", "--run-id", f"{a.eval_id}:{t}:{n}:{h}:{time.time_ns()}", *st])
save(rows, Path(a.out))
cmd = "skillcheck" if a.scope == "skill" else "check"
sys.exit(trust.main([cmd, a.family, *st]))
