"""aqh - agent QA harness command line.

  aqh agents                                   list agents and how each plugs in
  aqh run --agent X --task tasks/T.json [--qa default+judge:mimo] [--dry-run]
  aqh suite --agents a,b,c [--suite suites/real-work-v1.json] [--qa ...]
  aqh manual export --task T.json [--out prompt.txt]
  aqh manual score --task T.json --agent chatgpt-app --reply reply.txt [--qa ...]
  aqh score --task T.json --file output.md [--qa ...]     score any saved output
  aqh gate --kind article draft.md [--rulebook R.toml]
  aqh trust suite|trial|check|show|skillcheck ...           pass^3 trust ladder
  aqh spend                                    spend per model (local ledger)
  aqh agree --run results/DIR                  two-judge agreement from a saved run
  aqh review --run results/DIR                 rebuild REVIEW.md from a saved run
  aqh calibrate --qa default+judge+judge2 [--out DIR]   judge calibration (known-good/known-bad answers)

Scoring v2: verdicts are PASS, FAIL or ERROR (rerun needed). A suite run with --include-heldout (a final
run) first calibrates its judges and aborts with exit code 3 if any judge misgrades.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import spend, locked
from .adapters import KIND, REGISTRY, get_agent
from .adapters.manual import APP_NOTES, ReplayAgent, export_prompt
from .core import Task
from .qa import build_qa
from .runner import run_one, save


def _outdir(a) -> Path:
    return Path(a.out or f"results/{time.strftime('%Y-%m-%d_%H%M')}")


def _configure_stdio() -> None:
    """Write UTF-8 to the console even on Windows cp1252; never depend on PYTHONUTF8."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _emit(text: str) -> None:
    """Print a line without crashing if the console encoding cannot represent a character (e.g. ⚠)."""
    out = sys.stdout
    try:
        out.write(text + "\n")
        out.flush()
    except UnicodeEncodeError:
        data = (text + "\n").encode(getattr(out, "encoding", None) or "utf-8", errors="replace")
        buf = getattr(out, "buffer", None)
        if buf is not None:
            buf.write(data)
            buf.flush()
        else:
            out.write(data.decode(getattr(out, "encoding", None) or "utf-8", errors="replace"))
            out.flush()


def _print(r: dict) -> None:
    _emit(f"{'PASS' if r['pass'] else 'FAIL'}  agent={r['agent']}  task={r['task']}  checks {r['checks_passed']}/{r['checks_total']}"
          + (f"  judge={r['judge_score']}" if r.get("judge_score") is not None else ""))
    for x in r["reasons"]:
        _emit("   - " + x[:300])



def _git_rev() -> str:
    import subprocess
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _agree(run_dir: Path) -> int:
    src = run_dir / "results.jsonl" if run_dir.is_dir() else run_dir
    if not src.is_file():
        print(f"no results.jsonl in {run_dir}")
        return 2
    rows = [json.loads(l) for l in src.read_text(encoding="utf-8").splitlines() if l.strip()]
    latest = {}
    for r in rows:
        latest[(r.get("agent"), r.get("task"))] = r
    from .runner import verdict_of
    errors = [r for r in latest.values() if verdict_of(r) == "ERROR"]
    paired = [r for r in latest.values() if r.get("judge2_score") is not None and r.get("judge_score") is not None
              and verdict_of(r) != "ERROR"]
    if not paired:
        print("no rows with a second judge score; rerun or rescore with --qa default+judge+judge2")
        print("example: python -m aqh score --agent grok --task tasks/city-page-denver.json --file results/RUN/outputs/grok__city-page-denver.md --qa default+judge+judge2 --out results/RUN-agree")
        return 2
    n_ag = sum(1 for r in paired if r.get("judge_agree"))
    print(f"{n_ag}/{len(paired)} tasks: both judges reached the same pass/fail verdict.")
    if errors:
        print(f"({len(errors)} ERROR row(s) left out: rerun or rescore them)")
    for r in sorted(paired, key=lambda x: (x.get("agent") or "", x.get("task") or "")):
        d = ""
        if r.get("judge_score") is not None and r.get("judge2_score") is not None:
            d = f", score delta {abs(float(r['judge_score']) - float(r['judge2_score']))}"
        print(f"  {r.get('agent')} / {r.get('task')}: judge {r.get('judge_score')}, judge2 {r.get('judge2_score')}, "
              f"{'agree' if r.get('judge_agree') else 'disagree'}{d}")
    return 0 if n_ag == len(paired) else 1



def _review(run_dir: Path) -> int:
    from .runner import scorecard
    src = run_dir / "results.jsonl" if run_dir.is_dir() else run_dir
    if not src.is_file():
        print(f"no results.jsonl in {run_dir}")
        return 2
    outdir = src.parent
    path = scorecard(outdir)
    print("scorecard:", path)
    print("review:", outdir / "REVIEW.md")
    return 0


def main(argv=None) -> int:
    _configure_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "trust":
        from . import trust
        return trust.main(argv[1:])
    if argv and argv[0] == "gate":
        from .qa.gate import main as gmain
        return gmain(argv[1:])
    ap = argparse.ArgumentParser(prog="aqh", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("agents"); sub.add_parser("spend")
    ag = sub.add_parser("agree")
    ag.add_argument("--run", required=True, help="results folder with results.jsonl")
    cb = sub.add_parser("calibrate")
    cb.add_argument("--qa", default="default+judge+judge2"); cb.add_argument("--out")
    rv = sub.add_parser("review")
    rv.add_argument("--run", required=True, help="results folder with results.jsonl")
    for name in ("run", "score"):
        p = sub.add_parser(name)
        p.add_argument("--agent", default="manual"); p.add_argument("--task", required=True)
        p.add_argument("--file"); p.add_argument("--qa", default="default"); p.add_argument("--rulebook")
        p.add_argument("--out"); p.add_argument("--dry-run", action="store_true", help="label the run as a harness dry run")
    s = sub.add_parser("suite")
    s.add_argument("--agents", required=True); s.add_argument("--suite", default="suites/real-work-v1.json")
    s.add_argument("--qa"); s.add_argument("--rulebook"); s.add_argument("--out"); s.add_argument("--dry-run", action="store_true")
    s.add_argument("--include-heldout", action="store_true", help="also score frozen held-out tasks (final runs only)")
    m = sub.add_parser("manual")
    m.add_argument("action", choices=["export", "score"]); m.add_argument("--task", required=True)
    m.add_argument("--agent", default="manual"); m.add_argument("--reply"); m.add_argument("--out")
    m.add_argument("--qa", default="default"); m.add_argument("--rulebook"); m.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "agents":
        print(f"{'agent':16} {'plugs in via':22} notes")
        for n in REGISTRY:
            print(f"{n:16} {KIND.get(n, '?'):22} {((REGISTRY[n].__doc__ or 'agent').strip().splitlines() or ['agent'])[0][:70] if isinstance(REGISTRY[n], type) else 'model API (cheap baseline or owner key)'}")
        for n, note in APP_NOTES.items():
            print(f"{n:16} {'manual paste':22} {note}")
        return 0
    if a.cmd == "spend":
        for k, v in spend.by_model().items():
            print(f"{k:40} ${v:.4f}")
        print(f"{'TOTAL':40} ${spend.total():.4f} (cap ${spend.CAP_USD:.2f})")
        return 0
    if a.cmd == "agree":
        return _agree(Path(a.run))
    if a.cmd == "review":
        return _review(Path(a.run))
    if a.cmd == "calibrate":
        from .calibrate import ensure_calibrated, run_calibration, summary_lines
        res = ensure_calibrated(a.qa, Path(a.out)) if a.out else run_calibration(a.qa)
        for line in summary_lines(res):
            _emit(line)
        return 0 if res["passed"] else 3
    mode = "dry-run" if getattr(a, "dry_run", False) else "owner-run"
    if a.cmd == "manual":
        task = Task.load(a.task)
        if a.action == "export":
            out = export_prompt(task, a.out or f"prompts/{task.id}.txt")
            print(f"wrote {out}. Paste it into the app, save the reply, then run:\n  aqh manual score --task {a.task} --agent {a.agent} --reply reply.txt")
            return 0
        if not a.reply:
            print("--reply FILE is required"); return 2
        r = run_one(ReplayAgent(a.reply, a.agent), task, build_qa(a.qa, a.rulebook), mode + "/manual-paste")
        _print(r); print("scorecard:", save([r], _outdir(a))); return 0 if r["pass"] else 1
    if a.cmd in ("run", "score"):
        task = Task.load(a.task)
        agent = ReplayAgent(a.file, a.agent) if a.cmd == "score" else get_agent(a.agent)
        outdir = _outdir(a)
        locked.snapshot(outdir, task=a.task, agents=[a.agent], mode=mode, git=_git_rev(), cmd=a.cmd)
        r = run_one(agent, task, build_qa(a.qa, a.rulebook), mode)
        _print(r); print("scorecard:", save([r], outdir)); print("review:", outdir / "REVIEW.md"); return 0 if r["pass"] else 1
    if a.cmd == "suite":
        suite = json.loads(Path(a.suite).read_text(encoding="utf-8"))
        base = Path(a.suite).parent
        outdir = _outdir(a)
        agents = [x.strip() for x in a.agents.split(",") if x.strip()]
        locked.snapshot(outdir, suite=str(Path(a.suite).as_posix()), agents=agents,
                        include_heldout=bool(getattr(a, "include_heldout", False)),
                        mode=mode, git=_git_rev())
        if getattr(a, "include_heldout", False):
            from .calibrate import ensure_calibrated, judge_layers, summary_lines
            qa_spec = a.qa or suite.get("qa") or "default+judge"
            if judge_layers(qa_spec):
                cal = ensure_calibrated(qa_spec, outdir)
                for line in summary_lines(cal):
                    _emit(line)
                if not cal["passed"]:
                    _emit("ABORT: judge calibration failed; no agent was run. See calibration.json.")
                    return 3
        rows = []
        skipped = []
        for name in agents:
            agent = get_agent(name)
            for t in suite["tasks"]:
                task = Task.load(base / t["task"])
                if (task.heldout or t.get("heldout")) and not getattr(a, "include_heldout", False):
                    skipped.append(task.id)
                    _emit(f"SKIP  held-out task={task.id}  (pass --include-heldout to score it in a final run)")
                    continue
                rb = a.rulebook or t.get("rulebook") or suite.get("rulebook")
                rb_path = str(base / rb) if rb and not Path(rb).is_absolute() else rb
                r = run_one(agent, task, build_qa(a.qa or t.get("qa", suite.get("qa", "default")), rb_path), mode)
                _print(r); rows.append(r)
        if skipped:
            _emit("held-out skipped: " + ", ".join(dict.fromkeys(skipped)))
        print("scorecard:", save(rows, outdir))
        print("review:", outdir / "REVIEW.md")
        print("run-config:", outdir / "run-config.json")
        return 0 if rows and all(r["pass"] for r in rows) else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
