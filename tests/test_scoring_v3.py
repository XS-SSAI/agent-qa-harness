"""Scoring v3 tests (stdlib unittest, no network, no keys). Run: python -m unittest discover -s tests"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["AQH_JUDGE_BACKOFF"] = "0"
os.environ["AQH_NO_NETWORK"] = "1"

from aqh import runner  # noqa: E402
from aqh.adapters.llm_api import PRESETS  # noqa: E402
from aqh.core import Check, Output, Task, Verdict  # noqa: E402
from aqh.families import family as family_of  # noqa: E402
from aqh.qa import JudgeQA, build_qa  # noqa: E402
from aqh.qa import judge as judge_mod  # noqa: E402

TASK = ROOT / "tasks" / "city-page-denver.json"


class PassRuleTests(unittest.TestCase):
    """Fix 1: judge pass = score >= 7 AND no invented facts; the model's pass flag cannot contradict its score."""

    def test_pass_false_with_score_8_and_no_invented_is_pass(self):
        score, inv, mp, passed = judge_mod.decide({"pass": False, "score": 8, "invented_facts": []})
        self.assertTrue(passed); self.assertFalse(mp); self.assertEqual(inv, [])

    def test_score_7_is_pass_and_6_9_is_fail(self):
        self.assertTrue(judge_mod.decide({"score": 7, "invented_facts": []})[3])
        self.assertFalse(judge_mod.decide({"score": 6.9, "invented_facts": []})[3])

    def test_pass_true_with_low_score_is_fail(self):
        self.assertFalse(judge_mod.decide({"pass": True, "score": 5, "invented_facts": []})[3])

    def test_invented_fact_fails_even_at_9(self):
        score, inv, _, passed = judge_mod.decide({"pass": True, "score": 9, "invented_facts": ["Denver has 40 venues"]})
        self.assertFalse(passed); self.assertEqual(inv, ["Denver has 40 venues"])

    def test_none_strings_are_not_invented(self):
        self.assertTrue(judge_mod.decide({"score": 8, "invented_facts": ["none"]})[3])
        self.assertTrue(judge_mod.decide({"score": 8, "invented_facts": "None"})[3])

    def test_old_format_falls_back_to_failed_items(self):
        d = {"pass": False, "score": 8, "failed": [{"item": "facts", "why": "invented a 2024 award"}]}
        self.assertFalse(judge_mod.decide(d)[3])
        d = {"pass": False, "score": 8, "failed": [{"item": "tone", "why": "a bit long"}]}
        self.assertTrue(judge_mod.decide(d)[3])

    def test_bad_score_is_zero(self):
        self.assertFalse(judge_mod.decide({"score": "n/a", "invented_facts": []})[3])

    def test_judgeqa_uses_rule_not_model_flag(self):
        task = Task.load(TASK)
        out = Output(text="# page", meta={"agent": "codex", "model": "codex"})
        reply = ('{"pass": false, "score": 8, "invented_facts": [], "failed": [], "summary": "ok"}', {"model": "deepseek-flash", "usd": 0.001})
        with mock.patch.object(judge_mod, "chat", return_value=reply):
            v = JudgeQA("deepseek-flash").score(out, task)
        self.assertTrue(v.passed); self.assertTrue(v.meta["pass_overridden"]); self.assertFalse(v.meta["model_pass"])


class Judge3Tests(unittest.TestCase):
    """Fix 2: judge3 from a third family, majority of 3."""

    def test_gemini_preset_is_google_family(self):
        self.assertEqual(PRESETS["gemini-flash"]["family"], "google")
        self.assertEqual(family_of(PRESETS["gemini-flash"]["model"]), "google")

    def test_auto3_picks_gemini_for_all_tested_agents(self):
        for w in ("claude-code", "codex", "copilot-cli", "cursor", "grok", "opencode"):
            self.assertEqual(judge_mod.pick_judge(w, offset=2), "gemini-flash", w)
            self.assertEqual(judge_mod.pick_judge(w, offset=0), "mimo")
            self.assertEqual(judge_mod.pick_judge(w, offset=1), "deepseek-flash")

    def test_three_judge_families_differ(self):
        fams = {PRESETS[p]["family"] for p in ("mimo", "deepseek-flash", "gemini-flash")}
        self.assertEqual(len(fams), 3)

    def test_build_qa_judge3(self):
        qa = build_qa("default+judge+judge2+judge3")
        self.assertEqual([j.preset for j in qa.judges()], ["auto", "auto2", "auto3"])


class _FakeJudge(JudgeQA):
    def __init__(self, preset, result):
        super().__init__(preset); self.result = result

    def score(self, output, task):
        if self.result == "error":
            return Verdict(False, [Check("judge_ran", False, "gemini-flash HTTP 500")], ["judge_ran: gemini-flash HTTP 500"], {"layer": self.name, "judge_error": True})
        ok = self.result == "pass"
        cs = [Check("judge_score", ok, ""), Check("judge_no_invented_facts", True, "")]
        return Verdict.from_checks(cs, layer=self.name, score=8 if ok else 4, usd=0.0)


class _Agent:
    name = "codex"

    def run(self, task):
        return Output(text="# Page\nbody", meta={"agent": "codex", "model": "codex"})


def _row(results):
    from aqh.qa import StackQA
    qa = StackQA([_FakeJudge(p, r) for p, r in zip(("auto", "auto2", "auto3"), results)])
    return runner.run_one(_Agent(), Task.load(TASK), qa)


class MajorityTests(unittest.TestCase):
    def test_two_of_three_pass_is_pass(self):
        r = _row(["pass", "fail", "pass"])
        self.assertEqual(r["verdict"], "PASS"); self.assertEqual(r["judge_votes"], "2/3")
        self.assertFalse(r["judge_agree"]); self.assertTrue(r["judge13_agree"]); self.assertFalse(r["judge23_agree"])
        self.assertTrue(r["judge_majority_pass"]); self.assertEqual(r["judge3_score"], 8)

    def test_one_of_three_is_fail(self):
        r = _row(["fail", "fail", "pass"])
        self.assertEqual(r["verdict"], "FAIL"); self.assertFalse(r["judge_majority_pass"])

    def test_all_pass_and_all_fail(self):
        self.assertEqual(_row(["pass"] * 3)["verdict"], "PASS")
        self.assertEqual(_row(["fail"] * 3)["verdict"], "FAIL")

    def test_judge_error_that_could_flip_is_error(self):
        self.assertEqual(_row(["pass", "fail", "error"])["verdict"], "ERROR")

    def test_judge_error_with_decided_majority_is_still_error_for_rescore(self):
        self.assertEqual(_row(["pass", "pass", "error"])["verdict"], "ERROR")

    def test_two_judges_keep_v2_rule(self):
        from aqh.qa import StackQA
        qa = StackQA([_FakeJudge("auto", "pass"), _FakeJudge("auto2", "fail")])
        r = runner.run_one(_Agent(), Task.load(TASK), qa)
        self.assertEqual(r["verdict"], "FAIL"); self.assertIsNone(r["judge3_score"])

    def test_hard_check_still_fails_row(self):
        from aqh.qa import StackQA

        class Gate:
            name = "gate"
            def score(self, o, t):
                return Verdict(False, [Check("gate", False, "box path")], ["gate: box path"], {})
        qa = StackQA([Gate()] + [_FakeJudge(p, "pass") for p in ("auto", "auto2", "auto3")])
        r = runner.run_one(_Agent(), Task.load(TASK), qa)
        self.assertEqual(r["verdict"], "FAIL")


class TokenCountTests(unittest.TestCase):
    def test_thinking_tokens_billed(self):
        from aqh.adapters import llm_api
        import io, json as _j
        body = {"choices": [{"message": {"content": "{\"score\": 8}"}}], "usage": {"prompt_tokens": 1000, "completion_tokens": 10, "total_tokens": 1510}}

        class R(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": "test"}), mock.patch.object(llm_api.urllib.request, "urlopen", return_value=R(_j.dumps(body).encode())), \
                mock.patch.object(llm_api.spend, "guard"), mock.patch.object(llm_api.spend, "book"):
            _, meta = llm_api.chat("gemini-flash", "s", "u")
        self.assertEqual(meta["tokens_out"], 510)
        self.assertAlmostEqual(meta["usd"], (1000 * 0.30 + 510 * 2.50) / 1e6, places=6)


if __name__ == "__main__":
    unittest.main()
