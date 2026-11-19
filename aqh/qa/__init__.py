"""QA layer registry. `--qa default` = gate + unconfirmed-facts (article tasks) + grounding/honesty.
Add model layers with '+': default+judge (auto cross-family), default+judge:mimo,
default+judge2 (second cheap cross-family judge, for agreement), default+judge+judge2+judge3
(scoring v3: three cross-family judges, majority vote), default+factcheck."""
from __future__ import annotations

from ..core import Check, Output, Task, Verdict
from .gate import GateQA
from .grounding import GroundingQA
from .judge import FactCheckQA, JudgeQA
from .profile import UnconfirmedQA


JUDGE_CHECKS = ("judge_ran", "judge_pass", "judge_score", "judge_no_invented_facts", "judge_majority")


class StackQA:
    """Runs the QA layers in order. Scoring v3: with 3 or more judge layers, the judges vote and the final judge
    verdict is the majority (judge_majority check); a single judge no longer fails the row on its own. A judge that
    did not run still makes the row ERROR (rescore), and deterministic layers (gate, grounding, unconfirmed) still
    fail the row by themselves. With 1 or 2 judges, every judge must pass (scoring v2 behaviour)."""

    def __init__(self, layers):
        self.layers = layers
        self.name = "+".join(l.name for l in layers)

    def judges(self):
        return [l for l in self.layers if isinstance(l, JudgeQA)]

    def score(self, output: Output, task: Task) -> Verdict:
        checks, reasons, meta = [], [], {"layers": {}}
        majority = len(self.judges()) >= 3
        votes = []
        for layer in self.layers:
            if isinstance(layer, UnconfirmedQA) and task.kind != "article":
                continue
            v = layer.score(output, task)
            checks += v.checks
            is_judge = isinstance(layer, JudgeQA)
            errored = any(c.name in ("judge_ran", "judge_input", "judge2_available", "cross_family") and not c.passed for c in v.checks)
            if is_judge and majority and not errored:
                votes.append(v.passed)  # a judge's own pass/fail is a vote, not a row failure
            else:
                reasons += [f"[{layer.name}] {r}" for r in v.reasons]
            meta["layers"][layer.name] = {"pass": v.passed, **{k: v.meta[k] for k in ("score", "usd", "summary", "judge_model", "claims", "judge_error", "attempts",
                                                                                     "invented_facts", "model_pass", "pass_overridden") if k in v.meta}}
        if majority:
            n_pass, n = sum(votes), len(self.judges())
            ok = n_pass * 2 > n
            checks.append(Check("judge_majority", ok, f"{n_pass}/{n} judges pass"))
            meta["judge_votes"] = f"{n_pass}/{n}"
            missing = n - len(votes)  # judges that did not run: their judge_ran reason already makes the row ERROR
            if not ok and (n_pass + missing) * 2 <= n:
                reasons.append(f"[judge-majority] judge_majority: only {n_pass}/{n} judges pass")
        return Verdict(passed=not reasons, checks=checks, reasons=reasons, meta=meta)


def build_qa(spec: str = "default", rulebook: str | None = None, events: str | None = None) -> StackQA:
    layers = []
    for part in (spec or "default").split("+"):
        part = part.strip()
        if part == "default":
            layers += [GateQA(rulebook, events), UnconfirmedQA(), GroundingQA()]
        elif part == "gate":
            layers.append(GateQA(rulebook, events))
        elif part == "unconfirmed":
            layers.append(UnconfirmedQA())
        elif part == "grounding":
            layers.append(GroundingQA())
        elif part == "judge3" or part.startswith("judge3:"):
            layers.append(JudgeQA(part.split(":", 1)[1] if ":" in part else "auto3"))
        elif part == "judge2" or part.startswith("judge2:"):
            layers.append(JudgeQA(part.split(":", 1)[1] if ":" in part else "auto2"))
        elif part.startswith("judge"):
            layers.append(JudgeQA(part.split(":", 1)[1] if ":" in part else "auto"))
        elif part == "factcheck":
            layers.append(FactCheckQA())
        else:
            raise SystemExit(f"unknown QA layer {part!r}")
    return StackQA(layers)
