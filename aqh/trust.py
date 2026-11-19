#!/usr/bin/env python3
"""aqh.trust - pass^3 trust gate for job families and skill evals (ported unchanged in logic).

Run as: aqh trust suite|trial|check|show|skillcheck ...  (or python -m aqh.trust ...)

RULE (replaces the old "last 3 runs" sliding window)
  A job family may fan out (parallel subagents, schedule, cloud/batch) only when
  ONE declared evaluation suite for that family has ALL 3 independently recorded
  runs for EVERY task in the suite: full Cartesian product len(tasks) x 3, every
  trial PASS, self-verified, with real evidence. Nothing less certifies.
  * The gate reads the LATEST declared suite for the family. Older suites never
    certify anything.
  * No sliding window: a later PASS can never push an earlier FAIL out. To rerun,
    declare a NEW eval id; it starts at 0/3 and must be filled completely.
  * An eval id is global. If the same eval id is declared for a second family
    (corrupted or imported store), both families are blocked: trials are keyed by
    eval id alone, so a cross-family collision would let one family's trials
    certify another.
  * Fail closed on: legacy rows, missing task ids, duplicate run ids, duplicate
    trials, underspecified suite/task manifest, self_verified not true, missing
    or placeholder evidence, any failed trial, malformed store lines, unknown
    tasks, out-of-order trials, cross-family eval id reuse.

SKILLS
  A skill is certified by exactly the same machinery: declare a suite with
  --scope skill (family = skill id) and fill every task x trial 1-3.
  `skillcheck` reads ONLY that. The old scalar `skill` row (kind=skill_eval,
  score vs threshold) stays readable and is still recorded for history, but it
  is read-only: a single scalar score is not pass^3 and can never certify or
  promote a skill, however high the score or however new the row.

STORAGE
  Append-only JSONL, default local/trust/ladder.jsonl (relative to the current folder).
  Override with --store PATH or TRUST_GATE_STORE (tests use a scratch file).

USAGE - explicit suites (the only path that can certify)
  trust_gate.py suite --eval-id E --family F --tasks a,b,c [--scope task|skill]
                    --worker MODEL --grader MODEL [--notes TEXT]
  trust_gate.py trial --eval-id E --task T --trial 1|2|3 --result PASS|FAIL
                    --evidence "what really happened" --self-verified [--run-id R]
  trust_gate.py check F [--json]      exit 0 trusted, 3 blocked
  trust_gate.py show F                full human report
  trust_gate.py skillcheck S          exit 0 only with a scope=skill pass^3 suite

USAGE - legacy, read-compatible only (can never certify a family or a skill)
  trust_gate.py record <job> PASS|FAIL "evidence" [--self-verified]
  trust_gate.py skill <id> <score> <threshold> <worker> <grader> "evidence"

Exit codes: 0 trusted / recorded, 2 usage or IO error, 3 blocked or rejected.
No model calls, no network, costs nothing.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

DEFAULT_STORE = os.environ.get("TRUST_GATE_STORE") or "local/trust/ladder.jsonl"
REQUIRED_TRIALS = 3
LEGACY_KINDS = {"run", "skill_eval"}
EVAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,79}$")

PLACEHOLDER_EVIDENCE = {
    "", "-", "--", "n/a", "na", "none", "null", "nil", "todo", "tbd", "pass",
    "passed", "ok", "okay", "done", "yes", "no", "true", "false", "looks right",
    "looks good", "tests pass", "test pass", "works", "it works", "verified",
    "self verified", "see above", "as above", "same as before", "n a",
}
GENERIC_EVIDENCE_RE = re.compile(
    r"^(?:tests?\s+pass(?:ed)?|looks?\s+(?:right|good|fine)|should\s+work|"
    r"all\s+good|no\s+errors?|works\s+fine)[.!]*$",
    re.IGNORECASE,
)


# ---------------------------------------------------------------- store I/O
def store_path(argv_store=None):
    return Path(argv_store or DEFAULT_STORE).expanduser()


def load_rows(path):
    """Return (rows, problems). problems non-empty means the store is untrusted."""
    rows, problems = [], []
    if not path.exists():
        return rows, problems
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return rows, [f"cannot read store {path}: {exc.__class__.__name__}"]
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            problems.append(f"store line {n}: invalid JSON (store is untrusted)")
            continue
        if not isinstance(obj, dict):
            problems.append(f"store line {n}: row is not a JSON object (store is untrusted)")
            continue
        obj["_line"] = n
        rows.append(obj)
    return rows, problems


def _count_lines(path):
    if not path.exists():
        return 0
    try:
        with path.open("rb") as f:
            return sum(1 for line in f if line.strip())
    except OSError:
        return 0


def append_row(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(row)
    row.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    with path.open("a", encoding="utf-8") as f:
        try:  # POSIX only; advisory lock keeps concurrent job runners honest
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass
        row["seq"] = _count_lines(path) + 1
        f.write(json.dumps(row, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())


# ---------------------------------------------------------------- validation
def _nonempty_str(value):
    return isinstance(value, str) and bool(value.strip())


def validate_suite(row):
    """Structural validation of a suite manifest. Any problem => fail closed."""
    p = []
    eval_id = row.get("eval_id")
    if not _nonempty_str(eval_id):
        p.append("manifest missing eval_id")
    elif not EVAL_ID_RE.match(eval_id.strip()):
        p.append("manifest eval_id must match [A-Za-z0-9][A-Za-z0-9._:-]{2,79}")
    if not _nonempty_str(row.get("family")):
        p.append("manifest missing family")
    scope = row.get("scope")
    if scope not in ("task", "skill"):
        p.append("manifest scope must be 'task' or 'skill'")
    worker, grader = row.get("worker"), row.get("grader")
    if not _nonempty_str(worker):
        p.append("manifest missing worker model")
    if not _nonempty_str(grader):
        p.append("manifest missing grader model")
    if scope == "skill" and _nonempty_str(worker) and _nonempty_str(grader):
        if worker.strip().lower() == grader.strip().lower():
            p.append("skill eval manifest: grader model must differ from worker model")
    if _nonempty_str(worker) and _nonempty_str(grader):
        # No model grades its own family's work (any scope); unknown families fail closed.
        try:
            try:
                from aqh import families
            except ImportError:  # run as a plain script: python aqh/trust.py
                sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
                from aqh import families
            families.require_cross(worker, grader)
        except Exception as e:  # SameFamily, UnknownModel, or the config missing
            p.append("cross-family rule: " + str(e))
    trials = row.get("trials", REQUIRED_TRIALS)
    if trials != REQUIRED_TRIALS:
        p.append(f"manifest must declare exactly {REQUIRED_TRIALS} trials (got {trials!r})")
    tasks = row.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        p.append("manifest must declare a non-empty task id list")
    else:
        seen = set()
        for task in tasks:
            if not _nonempty_str(task):
                p.append("manifest has an empty or non-string task id")
                continue
            key = task.strip()
            if key in seen:
                p.append(f"manifest lists task {key!r} twice")
            seen.add(key)
    return p


def evidence_ok(text):
    if not isinstance(text, str):
        return False
    value = text.strip()
    if len(value) < 12:
        return False
    if value.lower() in PLACEHOLDER_EVIDENCE:
        return False
    if GENERIC_EVIDENCE_RE.match(value):
        return False
    return True


def validate_trial(row, tasks):
    p = []
    task = row.get("task")
    if not _nonempty_str(task):
        p.append("trial row missing task id")
    elif task.strip() not in tasks:
        p.append(f"trial row references unknown task {task!r}")
    number = row.get("trial")
    if isinstance(number, bool) or not isinstance(number, int) or number not in (1, 2, 3):
        p.append(f"trial number must be 1, 2 or 3 (got {number!r})")
    if not _nonempty_str(row.get("run_id")):
        p.append("trial row missing run_id (independently recorded run id)")
    result = row.get("result")
    if result not in ("PASS", "FAIL"):
        p.append(f"trial result must be PASS or FAIL (got {result!r})")
    if row.get("self_verified") is not True:
        p.append("self_verified is not true (real self-verification required)")
    if not evidence_ok(row.get("evidence")):
        p.append("evidence missing, too short, placeholder or generic")
    return p


def eval_id_families(rows, eval_id):
    """Every family that declares this eval id -> row lines. Eval ids are global."""
    families = {}
    for row in rows:
        if row.get("kind") != "suite":
            continue
        if str(row.get("eval_id", "")).strip() != eval_id:
            continue
        family = str(row.get("family", "")).strip()
        families.setdefault(family, []).append(row.get("_line"))
    return families


# ---------------------------------------------------------------- evaluation
def evaluate(rows, family, store_problems=None):
    rep = {
        "family": (family or "").strip(),
        "trusted": False,
        "eval_id": None,
        "scope": None,
        "tasks": [],
        "expected": 0,
        "recorded": 0,
        "missing": [],
        "failing": [],
        "problems": [],
        "legacy_rows": 0,
        "older_eval_ids": [],
        "notes": [],
    }
    problems = rep["problems"]
    if store_problems:
        problems.extend(store_problems)
        return rep  # untrusted store: nothing can be certified
    fam = rep["family"]
    if not fam:
        problems.append("no family given")
        return rep

    suites = [r for r in rows
              if r.get("kind") == "suite" and str(r.get("family", "")).strip() == fam]
    legacy = [r for r in rows if r.get("kind") in LEGACY_KINDS
              and fam in (str(r.get("job", "")).strip(), str(r.get("skill", "")).strip())]
    rep["legacy_rows"] = len(legacy)

    if not suites:
        problems.append("no explicit evaluation suite declared for this family")
        if legacy:
            problems.append(
                f"{len(legacy)} legacy row(s) exist for this family, but legacy rows can "
                "never certify a family: declare a suite and record pass^3 trials")
        return rep

    ids = [str(s.get("eval_id", "")).strip() for s in suites]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        problems.append("duplicate suite declaration for eval id(s): " + ", ".join(duplicates))
        return rep

    latest = max(suites, key=lambda s: s.get("_line", 0))
    bad = validate_suite(latest)
    if bad:
        for item in bad:
            problems.append(f"suite {latest.get('eval_id')!r}: {item}")
        return rep

    eval_id = latest["eval_id"].strip()
    rep.update(eval_id=eval_id, scope=latest["scope"])

    # An eval id belongs to one family only. Imported/corrupted stores can hold
    # the same id under another family; trials are keyed by eval id alone, so
    # that would silently borrow another family's runs. Reject both sides.
    declared_for = eval_id_families(rows, eval_id)
    foreign = sorted(f for f in declared_for if f and f != fam)
    if foreign:
        problems.append(
            f"eval id {eval_id!r} is also declared for family(ies) "
            + ", ".join(repr(f) for f in foreign)
            + ": reusing one eval id across families is rejected (trials are keyed "
              "by eval id alone, so the runs cannot be attributed to one family)")
        return rep

    tasks = [t.strip() for t in latest["tasks"]]
    rep.update(tasks=tasks,
               expected=len(tasks) * REQUIRED_TRIALS,
               older_eval_ids=[i for i in ids if i != eval_id])
    declared_at = latest.get("_line", 0)

    trials = [r for r in rows if r.get("kind") == "trial" and str(r.get("eval_id", "")).strip() == eval_id]
    rep["recorded"] = len(trials)

    seen = {}
    run_ids = {}
    evidence_by_task = {}
    for row in trials:
        for item in validate_trial(row, tasks):
            if "unknown task" not in item and "trial number" not in item:
                problems.append(f"eval {eval_id} line {row.get('_line')}: {item}")
        # structural problems that also break keys
        task = str(row.get("task", "")).strip()
        number = row.get("trial")
        if row.get("_line", 0) < declared_at:
            problems.append(f"trial for {task!r} trial {number!r} recorded before its suite "
                            "declaration (out of order; store is untrusted)")
        if task and isinstance(number, int) and not isinstance(number, bool):
            key = (task, number)
            if key in seen:
                problems.append(f"duplicate trial: task {task!r} trial {number} recorded twice")
            seen[key] = row
        run_id = row.get("run_id")
        if _nonempty_str(run_id):
            run_ids.setdefault(run_id.strip(), []).append(row.get("_line"))
        if isinstance(row.get("evidence"), str):
            evidence_by_task.setdefault(task, []).append(row["evidence"].strip())
        if row.get("result") == "FAIL" and task and isinstance(number, int):
            rep["failing"].append({"task": task, "trial": number,
                                   "reason": str(row.get("evidence", ""))[:160]})

    for run_id, lines in run_ids.items():
        if len(lines) > 1:
            problems.append(f"duplicate run id {run_id!r} reused on lines "
                            f"{', '.join(str(x) for x in lines)}: runs are not independent")

    for task in tasks:
        for number in (1, 2, 3):
            if (task, number) not in seen:
                rep["missing"].append({"task": task, "trial": number})

    for task, values in evidence_by_task.items():
        if len(values) >= REQUIRED_TRIALS and len(set(values)) == 1:
            problems.append(f"task {task!r}: all {REQUIRED_TRIALS} trials share identical "
                            "evidence text, so they are not independent runs")

    # de-duplicate problem lines while keeping order (a single bad swap can repeat)
    deduped, seen_lines = [], set()
    for item in problems:
        if item not in seen_lines:
            seen_lines.add(item)
            deduped.append(item)
    rep["problems"] = deduped

    rep["trusted"] = (
        not rep["problems"]
        and not rep["missing"]
        and not rep["failing"]
        and rep["recorded"] == rep["expected"]
        and rep["expected"] > 0
    )
    if latest["scope"] == "skill" and rep["trusted"]:
        rep["notes"].append("skill manifest used a different grader model than worker")
    return rep


def format_report(rep):
    out = []
    head = "TRUSTED" if rep["trusted"] else "BLOCKED by trust gate"
    out.append(f'{head}: family "{rep["family"]}"')
    if rep["eval_id"]:
        out.append(f'  suite: {rep["eval_id"]} (scope {rep["scope"]}, '
                   f'{len(rep["tasks"])} task(s) x {REQUIRED_TRIALS} trials = {rep["expected"]})')
        out.append(f'  recorded: {rep["recorded"]}/{rep["expected"]}')
        if rep["older_eval_ids"]:
            out.append("  older suites ignored: " + ", ".join(rep["older_eval_ids"]))
    if rep["missing"]:
        out.append("  missing: " + ", ".join(f'{m["task"]}/trial{m["trial"]}' for m in rep["missing"]))
    if rep["failing"]:
        out.append("  failed trials: " + ", ".join(f'{f["task"]}/trial{f["trial"]}' for f in rep["failing"]))
    for item in rep["problems"]:
        out.append(f"  problem: {item}")
    if not rep["trusted"]:
        out.append("  fix: declare a NEW eval id (trust_gate.py suite ...) and record every "
                   "task x trial 1-3 as PASS with self-verification and real evidence")
    for note in rep["notes"]:
        out.append(f"  note: {note}")
    return "\n".join(out)


# ---------------------------------------------------------------- commands
def cmd_suite(args):
    opts = parse_opts(args)
    eval_id = (opts.get("eval-id") or [""])[0].strip()
    family = (opts.get("family") or [""])[0].strip()
    scope = (opts.get("scope") or ["task"])[0].strip()
    worker = (opts.get("worker") or [""])[0].strip()
    grader = (opts.get("grader") or [""])[0].strip()
    tasks = []
    for chunk in opts.get("tasks") or []:
        tasks.extend(t.strip() for t in chunk.split(",") if t.strip())
    tasks.extend(t.strip() for t in (opts.get("task") or []) if t.strip())

    row = {"kind": "suite", "eval_id": eval_id, "family": family, "scope": scope,
           "tasks": tasks, "worker": worker, "grader": grader,
           "trials": REQUIRED_TRIALS, "notes": (opts.get("notes") or [""])[0]}
    problems = validate_suite(row)
    if problems:
        print("REJECTED suite manifest (fail closed):")
        for item in problems:
            print(f"  - {item}")
        return 2

    path = store_path(opts.get("store", [None])[0])
    rows, store_problems = load_rows(path)
    if store_problems:
        print("REJECTED: existing store is untrusted, refusing to extend it:")
        for item in store_problems:
            print(f"  - {item}")
        return 2
    if any(r.get("kind") == "suite" and str(r.get("eval_id", "")).strip() == eval_id for r in rows):
        print(f"REJECTED: eval id {eval_id!r} is already declared. To rerun a suite declare a "
              "NEW eval id; an existing one is never reopened or overwritten.")
        return 2

    append_row(path, row)
    print(f"declared suite {eval_id} for family {family!r}: {len(tasks)} task(s) x "
          f"{REQUIRED_TRIALS} trials = {len(tasks) * REQUIRED_TRIALS} runs required")
    return 0


def cmd_trial(args):
    opts = parse_opts(args)
    eval_id = (opts.get("eval-id") or [""])[0].strip()
    task = (opts.get("task") or [""])[0].strip()
    number_raw = (opts.get("trial") or [""])[0].strip()
    result = (opts.get("result") or [""])[0].strip().upper()
    evidence = (opts.get("evidence") or [""])[0]
    self_verified = "self-verified" in opts
    run_id = (opts.get("run-id") or [""])[0].strip()

    path = store_path(opts.get("store", [None])[0])
    rows, store_problems = load_rows(path)
    if store_problems:
        print("REJECTED: existing store is untrusted, refusing to extend it:")
        for item in store_problems:
            print(f"  - {item}")
        return 2

    suites = [r for r in rows if r.get("kind") == "suite"
              and str(r.get("eval_id", "")).strip() == eval_id]
    if not eval_id or not suites:
        print(f"REJECTED: eval id {eval_id!r} is not declared. Declare the suite first "
              "(trust_gate.py suite ...); trials cannot create their own suite.")
        return 2
    # an eval id belongs to one family; trials are keyed by eval id alone, so a
    # cross-family reuse would silently borrow another family's runs.
    if len(eval_id_families(rows, eval_id)) > 1:
        print(f"REJECTED: eval id {eval_id!r} is declared for more than one family; "
              "store is untrusted and eval ids are global.")
        return 2
    if len(suites) > 1:
        print(f"REJECTED: eval id {eval_id!r} is declared more than once; store is untrusted.")
        return 2
    suite = suites[0]
    bad = validate_suite(suite)
    if bad:
        print(f"REJECTED: suite {eval_id!r} manifest is underspecified:")
        for item in bad:
            print(f"  - {item}")
        return 2

    tasks = [t.strip() for t in suite["tasks"]]
    if task not in tasks:
        print(f"REJECTED: task {task!r} is not in suite {eval_id!r} "
              f"(tasks: {', '.join(tasks)})")
        return 2
    if number_raw not in ("1", "2", "3"):
        print(f"REJECTED: trial must be 1, 2 or 3 (pass^3), got {number_raw!r}")
        return 2
    number = int(number_raw)
    if result not in ("PASS", "FAIL"):
        print(f"REJECTED: result must be PASS or FAIL, got {result!r}")
        return 2
    if not evidence.strip():
        print("REJECTED: evidence is required (what you actually did and saw).")
        return 2

    row = {"kind": "trial", "eval_id": eval_id, "task": task, "trial": number,
           "result": result, "evidence": evidence, "self_verified": self_verified,
           "run_id": run_id or f"{eval_id}:{task}:{number}:{time.time_ns()}"}
    problems = validate_trial(row, tasks)
    # a FAIL trial is allowed to be recorded with weaker evidence wording, but
    # every recorded run still needs a run id and honest self_verified value.
    blocking = [p for p in problems if "evidence missing" not in p]
    if blocking:
        print("REJECTED trial (fail closed):")
        for item in blocking:
            print(f"  - {item}")
        return 2

    for existing in rows:
        if existing.get("kind") != "trial":
            continue
        if str(existing.get("eval_id", "")).strip() != eval_id:
            continue
        if (str(existing.get("task", "")).strip() == task
                and existing.get("trial") == number):
            print(f"REJECTED: duplicate trial: task {task!r} trial {number} is already "
                  f"recorded for {eval_id!r}. Rerun with a new eval id.")
            return 2
        if str(existing.get("run_id", "")).strip() == row["run_id"]:
            print(f"REJECTED: duplicate run id {row['run_id']!r}: each run must be "
                  "independently recorded with its own id.")
            return 2

    append_row(path, row)
    state = "PASS" if result == "PASS" else "FAIL"
    print(f"recorded {state} {eval_id} task {task!r} trial {number} "
          f"(self_verified={self_verified})")
    return 0


def cmd_check(args, as_json=False):
    opts = parse_opts(args)
    family = " ".join(opts.get("_positional") or [])
    path = store_path(opts.get("store", [None])[0])
    rows, store_problems = load_rows(path)
    rep = evaluate(rows, family, store_problems)
    if as_json:
        print(json.dumps(rep, indent=2, sort_keys=True))
    else:
        print(format_report(rep))
    return 0 if rep["trusted"] else 3


def cmd_show(args):
    return cmd_check(args, as_json=False)


def cmd_record(args):
    opts = parse_opts(args)
    pos = opts.get("_positional") or []
    if len(pos) < 2:
        print(__doc__)
        return 2
    job, result = pos[0], pos[1].upper()
    evidence = pos[2] if len(pos) > 2 else ""
    path = store_path(opts.get("store", [None])[0])
    append_row(path, {"kind": "run", "job": job, "result": result, "evidence": evidence,
                      "self_verified": "self-verified" in opts, "legacy": True})
    print("recorded legacy run (cannot certify a family; use suite/trial for that)")
    return 0


def cmd_skill(args):
    opts = parse_opts(args)
    pos = opts.get("_positional") or []
    if len(pos) < 5:
        print(__doc__)
        return 2
    sid, score, threshold, worker, grader = pos[0], float(pos[1]), float(pos[2]), pos[3], pos[4]
    if worker.strip().lower() == grader.strip().lower():
        print("REJECTED: grader model must differ from worker model")
        return 3
    path = store_path(opts.get("store", [None])[0])
    append_row(path, {"kind": "skill_eval", "skill": sid, "score": score,
                      "threshold": threshold, "worker": worker, "grader": grader,
                      "evidence": pos[5] if len(pos) > 5 else "",
                      "pass": score >= threshold, "legacy": True})
    print("recorded legacy skill eval (read-only history; it never certifies a skill)")
    return 0


def cmd_skillcheck(args):
    """Admission for a skill: latest explicit scope=skill suite, pass^3, nothing less."""
    opts = parse_opts(args)
    pos = opts.get("_positional") or []
    if not pos:
        print(__doc__)
        return 2
    skill = pos[0].strip()
    path = store_path(opts.get("store", [None])[0])
    rows, store_problems = load_rows(path)
    if store_problems:
        print(f"BLOCKED skill {skill}: store is untrusted, so nothing can be certified")
        for item in store_problems:
            print(f"  problem: {item}")
        return 3

    rep = evaluate(rows, skill)
    if rep["trusted"] and rep["scope"] == "skill":
        print(f"TRUSTED skill {skill}: suite {rep['eval_id']} scope=skill, "
              f"{rep['recorded']}/{rep['expected']} trials, every task passed 3/3")
        return 0

    print(f"BLOCKED skill {skill}: needs an explicit scope=skill pass^3 suite")
    if rep["scope"] and rep["scope"] != "skill":
        print(f"  problem: latest suite {rep['eval_id']} is scope={rep['scope']}; "
              "only a scope=skill suite can certify a skill")
    for item in rep["problems"]:
        print(f"  problem: {item}")
    if rep["eval_id"]:
        print(f"  suite: {rep['eval_id']} recorded {rep['recorded']}/{rep['expected']}")
    if rep["missing"]:
        print("  missing: " + ", ".join(f'{m["task"]}/trial{m["trial"]}' for m in rep["missing"]))
    if rep["failing"]:
        print("  failed trials: "
              + ", ".join(f'{f["task"]}/trial{f["trial"]}' for f in rep["failing"]))
    legacy = [r for r in rows
              if r.get("kind") == "skill_eval" and str(r.get("skill", "")).strip() == skill]
    if legacy:
        print(f"  legacy: {len(legacy)} scalar skill_eval row(s) are read-only history; "
              "a scalar score is not pass^3 and never certifies")
    print("  fix: trust_gate.py suite --scope skill --family <skill> --tasks ... then "
          "record every task x trial 1-3 as PASS with real evidence")
    return 3


# ---------------------------------------------------------------- arg handling
def parse_opts(args):
    """Tiny tolerant parser: --key value, --flag, positionals. --store anywhere."""
    opts, i = {}, 0
    positional = []
    while i < len(args):
        token = args[i]
        if token.startswith("--"):
            key = token[2:]
            if "=" in key:
                key, value = key.split("=", 1)
                opts.setdefault(key, []).append(value)
                i += 1
                continue
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                opts.setdefault(key, []).append(args[i + 1])
                i += 2
                continue
            opts.setdefault(key, []).append("")
            i += 1
            continue
        positional.append(token)
        i += 1
    opts["_positional"] = positional
    return opts


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    as_json = "--json" in rest
    handlers = {
        "suite": cmd_suite,
        "trial": cmd_trial,
        "check": lambda a: cmd_check(a, as_json),
        "show": cmd_show,
        "record": cmd_record,
        "skill": cmd_skill,
        "skillcheck": cmd_skillcheck,
    }
    handler = handlers.get(cmd)
    if handler is None:
        print(f"unknown command {cmd!r}\n")
        print(__doc__)
        return 2
    try:
        return handler(rest)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc.__class__.__name__}: {exc} (fail closed)")
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
