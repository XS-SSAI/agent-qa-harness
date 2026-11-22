"""Cross-model judge and web fact-check (model-based QA layers).

JudgeQA:     a model from a DIFFERENT family scores the output against a rubric (JSON verdict).
FactCheckQA: Perplexity sonar checks each factual claim against the web; any 'false' claim fails.
Both refuse to grade work from their own model family.
"""
from __future__ import annotations

import json
import os
import time

from ..adapters.llm_api import PRESETS, chat, parse_json
from ..core import Check, Output, Task, Verdict
from ..families import require_cross

JUDGE_SYS = ("You are a strict QA reviewer. Score the OUTPUT against the TASK and the RUBRIC. Do not rewrite it. "
             "Return ONLY JSON: {\"score\": 0-10, \"invented_facts\": [\"each fact in the OUTPUT that is not supported by the TASK "
             "material or common knowledge, max 20 words each\"], \"failed\": [{\"item\": \"...\", \"why\": \"max 20 words\"}], "
             "\"pass\": true|false, \"summary\": \"max 30 words\"}. Score 7 or more only if every must-have rubric item is met; "
             "a failed must-have item, meta commentary or placeholders must bring the score below 7. "
             "invented_facts is an empty list when nothing is invented.")

FACT_SYS = ("You are a fact-checker with web search. For each CLAIM, check it against current reliable sources. "
            "Return ONLY JSON: {\"claims\": [{\"claim\": \"...\", \"verdict\": \"true\"|\"false\"|\"unverifiable\", "
            "\"source\": \"url\", \"why\": \"max 20 words\"}]}.")


def _worker_family(output: Output) -> str:
    return str(output.meta.get("model") or output.meta.get("agent") or "unknown")


AUTO_ORDER = ["mimo", "deepseek-flash", "gemini-flash", "sonar"]
AUTO_OFFSETS = {"auto": 0, "auto2": 1, "auto3": 2}

# Scoring v2: a judge that returns no text, bad JSON or an HTTP/network error is retried up to
# JUDGE_RETRIES more times. Missing keys and the spend cap are not retried (they cannot heal).
# judge2 (DeepSeek Flash) gets more output room because it ran out of tokens (finish_reason=length).
JUDGE_RETRIES = 2
JUDGE_MAX_TOKENS = 6000
JUDGE2_MAX_TOKENS = 16000  # also used by judge3 (Gemini thinks before it answers)
NO_RETRY = ("is not set", "spend cap")
# Scoring v5: the judge gets the whole task material and the whole output, or it does not grade at all.
# Scoring v3 cut both at 30,000 characters without saying so; on a larger source (listings-houston is 45,672)
# the judge then graded against a partial source and could call real records invented. Past this limit the
# row is an ERROR (rerun with a smaller task or a larger limit), never a grade on text the judge did not see.
JUDGE_MAX_INPUT_CHARS = 200_000


def _backoff(attempt: int) -> None:
    base = float(os.environ.get("AQH_JUDGE_BACKOFF", "3"))
    if base > 0:
        time.sleep(base * attempt)


def judge_call(preset: str, system: str, user: str, max_tokens: int, tag: str, retries: int = JUDGE_RETRIES) -> tuple[dict, dict, int]:
    """Call a judge and parse its JSON verdict, retrying empty/HTTP/JSON failures. Returns (verdict, meta, attempts)."""
    last = None
    for attempt in range(retries + 1):
        try:
            raw, meta = chat(preset, system, user, max_tokens=max_tokens, temperature=0, json_mode=True, tag=tag)
            d = parse_json(raw)
            if not isinstance(d, dict) or ("pass" not in d and "score" not in d):
                raise RuntimeError(f"{preset} returned JSON without pass/score")
            return d, meta, attempt + 1
        except Exception as e:  # noqa: BLE001
            last = e
            if any(x in str(e) for x in NO_RETRY) or attempt == retries:
                break
            _backoff(attempt + 1)
    raise RuntimeError(f"{str(last)[:180]} (after {attempt + 1} attempt{'s' if attempt else ''})")


def pick_judge(worker: str, order=AUTO_ORDER, offset: int = 0) -> str:
    """Nth judge preset (0-based) whose family differs from the worker's (cross-family rule)."""
    found = []
    for p in order:
        try:
            require_cross(worker, PRESETS[p]["model"])
            found.append(p)
        except ValueError:
            continue
    if len(found) <= offset:
        raise ValueError(f"no cross-family judge available for {worker!r} at offset {offset}")
    return found[offset]


class JudgeQA:
    """judge:auto picks the first cross-family judge; judge:<preset> forces one (fails closed on same family)."""

    def __init__(self, preset: str = "auto", min_score: float = 7.0):
        self.preset, self.min_score, self.name = preset, min_score, f"judge:{preset}"

    def score(self, output: Output, task: Task) -> Verdict:
        worker = _worker_family(output)
        if not output.text.strip():
            return Verdict(False, [Check("judge_input", False, "empty output; judge not called")], ["judge_input: empty output; judge not called"], {"layer": self.name})
        preset = self.preset
        if preset in AUTO_OFFSETS:
            offset = AUTO_OFFSETS[preset]
            try:
                if output.meta.get("mode") == "manual-paste":
                    preset = pick_judge(worker, offset=offset) if offset else "mimo"
                else:
                    preset = pick_judge(worker, offset=offset)
            except ValueError:
                if offset == 0:
                    preset = "mimo"  # unknown worker family: any judge is cross-family
                else:
                    return Verdict(False, [Check("judge2_available", False, f"no judge #{offset + 1} cross-family to {worker!r}")],
                                   [f"judge2_available: no judge #{offset + 1} cross-family to {worker!r}"], {"layer": self.name})
        try:
            require_cross(worker, PRESETS[preset]["model"])
        except ValueError as e:
            if output.meta.get("mode") != "manual-paste":
                return Verdict(False, [Check("cross_family", False, str(e))], [f"cross_family: {e}"], {"layer": self.name})
        material = task.material()
        too_long = [f"{what} is {len(x):,} characters" for what, x in (("the task material", material), ("the output", output.text))
                    if len(x) > JUDGE_MAX_INPUT_CHARS]
        if too_long:
            msg = (f"{' and '.join(too_long)}, over the {JUDGE_MAX_INPUT_CHARS:,} judge limit; judge not called "
                   "(it would grade text it cannot see in full)")
            return Verdict(False, [Check("judge_ran", False, msg)], [f"judge_ran: {msg}"], {"layer": self.name, "judge_error": True})
        rubric = "\n".join(f"- {r}" for r in task.expect.get("rubric", ["Complete, on-task, no invented facts."]))
        user = f"TASK:\n{material}\n\nRUBRIC:\n{rubric}\n\nOUTPUT:\n{output.text}"
        max_tokens = JUDGE_MAX_TOKENS if preset.startswith("mimo") else JUDGE2_MAX_TOKENS
        try:
            d, meta, attempts = judge_call(preset, JUDGE_SYS, user, max_tokens, f"judge:{task.id}")
        except Exception as e:  # noqa: BLE001
            # judge_ran failing makes the whole row an ERROR (not FAIL) in scoring v2: flagged for rescoring.
            return Verdict(False, [Check("judge_ran", False, str(e)[:240])], [f"judge_ran: {str(e)[:240]}"], {"layer": self.name, "judge_error": True})
        score, invented, model_pass, passed = decide(d, self.min_score)
        fails = "; ".join(f"{x.get('item')}: {x.get('why')}" for x in d.get("failed", []) if isinstance(x, dict))[:400]
        cs = [Check("judge_score", score >= self.min_score, f"score {score} < {self.min_score}" + (f" ({fails})" if fails else "")),
              Check("judge_no_invented_facts", not invented, "invented: " + "; ".join(invented)[:300])]
        return Verdict.from_checks(cs, layer=self.name, score=score, judge_model=meta["model"], usd=meta["usd"], summary=d.get("summary"),
                                   attempts=attempts, invented_facts=invented, model_pass=model_pass,
                                   pass_overridden=model_pass is not None and model_pass != passed)


INVENTED_HINT = ("invent", "fabricat", "made up", "made-up", "hallucinat", "unsupported fact", "not in the source", "unverified fact")


def decide(d: dict, min_score: float = 7.0) -> tuple[float, list[str], bool | None, bool]:
    """Scoring v3 judge rule, enforced in code: pass = score >= min_score AND no invented facts.

    The model's own pass flag is kept for the record only (model_pass); it can no longer contradict its score.
    invented_facts comes from the judge's explicit list; older-format replies without that field fall back to
    failed items whose text names an invented/fabricated fact.
    """
    try:
        score = float(d.get("score", 0) or 0)
    except (TypeError, ValueError):
        score = 0.0
    inv = d.get("invented_facts")
    if isinstance(inv, list):
        invented = [str(x).strip() for x in inv if str(x).strip() and str(x).strip().lower() not in ("none", "n/a", "-")]
    elif isinstance(inv, str):
        invented = [inv.strip()] if inv.strip() and inv.strip().lower() not in ("none", "n/a", "-", "[]") else []
    else:
        invented = [f"{x.get('item')}: {x.get('why')}" for x in d.get("failed", []) if isinstance(x, dict)
                    and any(h in f"{x.get('item')} {x.get('why')}".lower() for h in INVENTED_HINT)]
    mp = d.get("pass")
    model_pass = mp if isinstance(mp, bool) else None
    return score, invented, model_pass, score >= min_score and not invented


class FactCheckQA:
    name = "factcheck:sonar"

    def __init__(self, max_claims: int = 8):
        self.max_claims = max_claims

    def claims(self, output: Output, task: Task) -> list[str]:
        if task.expect.get("claims"):
            return task.expect["claims"]
        raw, _ = chat("deepseek-flash" if "deepseek" not in _worker_family(output) else "mimo",
                      "Extract checkable factual claims about the outside world (not opinions, not instructions). "
                      "Return ONLY JSON {\"claims\": [\"...\"]}, at most %d." % self.max_claims,
                      output.text[:20000], max_tokens=6000, temperature=0, json_mode=True, tag=f"claims:{task.id}")
        return parse_json(raw).get("claims", [])[: self.max_claims]

    def score(self, output: Output, task: Task) -> Verdict:
        try:
            cl = self.claims(output, task)
            raw, meta = chat("sonar", FACT_SYS, "CLAIMS:\n" + json.dumps(cl, ensure_ascii=False), max_tokens=3000, temperature=0, tag=f"fact:{task.id}")
            res = parse_json(raw).get("claims", [])
        except Exception as e:  # noqa: BLE001
            return Verdict(False, [Check("factcheck_ran", False, str(e)[:200])], [f"factcheck_ran: {str(e)[:200]}"], {"layer": self.name})
        false = [r for r in res if str(r.get("verdict")).lower() == "false"]
        cs = [Check("claims_checked", bool(res), "no claims came back from the fact-checker"),
              Check("no_false_claims", not false, "; ".join(f"{r.get('claim')} ({r.get('why')})" for r in false)[:500])]
        return Verdict.from_checks(cs, layer=self.name, claims=res, usd=meta["usd"], sources=meta.get("citations", [])[:6])
