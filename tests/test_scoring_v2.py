"""Scoring v2 tests (stdlib unittest, no network, no keys). Run: python -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["AQH_JUDGE_BACKOFF"] = "0"
os.environ["AQH_NO_NETWORK"] = "1"

from aqh import runner  # noqa: E402
from aqh.core import Check, Output, Task, Verdict  # noqa: E402
from aqh.qa import judge as judge_mod  # noqa: E402

TASK = ROOT / "tasks" / "city-page-denver.json"


class _Agent:
    def __init__(self, exc=None, text="# Page\nbody", name="fake"):
        self.exc, self.text, self.name = exc, text, name

    def run(self, task):
        if self.exc:
            raise self.exc
        return Output(text=self.text, meta={"agent": self.name, "model": "codex"})


class _QA:
    name = "fake-qa"

    def __init__(self, v):
        self.v = v

    def score(self, out, task):
        return self.v


def _judge_v(name, passed, score=None, error=False):
    if error:
        return Check("judge_ran", False, "deepseek-flash returned no text")
    return Check(name, passed, "")


class ErrorVerdictTests(unittest.TestCase):
    """Fix 1: ERROR verdict, separate from FAIL."""

    def setUp(self):
        self.task = Task.load(TASK)

    def test_credit_error_is_error(self):
        r = runner.run_one(_Agent(RuntimeError("opencode exited 1: Error: This request requires more credits, or fewer max_tokens")), self.task, _QA(None))
        self.assertEqual(r["verdict"], "ERROR"); self.assertTrue(r["rerun"]); self.assertFalse(r["pass"])

    def test_missing_key_and_quota_and_auth_are_error(self):
        for msg in ("env var XAI_API_KEY is not set", "You have reached your usage limit", "HTTP 401 Unauthorized", "quota exceeded"):
            r = runner.run_one(_Agent(RuntimeError(msg)), self.task, _QA(None))
            self.assertEqual(r["verdict"], "ERROR", msg)

    def test_timeout_is_fail_not_error(self):
        r = runner.run_one(_Agent(RuntimeError("opencode timed out after 900s and was stopped")), self.task, _QA(None))
        self.assertEqual(r["verdict"], "FAIL")

    def test_judge_not_run_is_error(self):
        v = Verdict(False, [Check("gate_ok", True), Check("judge_ran", False, "mimo HTTP 402")], ["[judge:auto] judge_ran: mimo HTTP 402"], {"layers": {}})
        r = runner.run_one(_Agent(), self.task, _QA(v))
        self.assertEqual(r["verdict"], "ERROR")

    def test_hard_check_fail_stays_fail_even_if_judge_errored(self):
        v = Verdict(False, [Check("delivery_label", False, "missing"), Check("judge_ran", False, "x")], ["a", "b"], {"layers": {}})
        self.assertEqual(runner.run_one(_Agent(), self.task, _QA(v))["verdict"], "FAIL")

    def test_judge_fail_is_fail(self):
        v = Verdict(False, [Check("judge_pass", False, "invented"), Check("judge_score", False, "4<7")], ["x"], {"layers": {}})
        self.assertEqual(runner.run_one(_Agent(), self.task, _QA(v))["verdict"], "FAIL")

    def test_scorecard_and_agree_exclude_error(self):
        from aqh.cli import _agree
        rows = [
            {"agent": "a", "task": "t1", "verdict": "PASS", "pass": True, "judge_score": 9, "judge2_score": 9, "judge_agree": True},
            {"agent": "a", "task": "t2", "verdict": "FAIL", "pass": False, "judge_score": 4, "judge2_score": 5, "judge_agree": True},
            {"agent": "a", "task": "t3", "verdict": "ERROR", "pass": False, "judge_score": 9, "judge2_score": None, "judge_agree": None, "error": "judge did not run"},
            {"agent": "a", "task": "t4", "verdict": "ERROR", "pass": False, "judge_score": 9, "judge2_score": 3, "judge_agree": False},
        ]
        base = {"data_label": "public", "mode": "owner-run", "checks_passed": 1, "checks_total": 1, "reasons": ["r"], "seconds": 1, "output": "x"}
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "results.jsonl"
            p.write_text("".join(json.dumps({**base, **r}) + "\n" for r in rows), encoding="utf-8")
            md = runner.scorecard(Path(d)).read_text(encoding="utf-8")
            self.assertIn("| 1/2 | 2 |", md)              # pass rate leaves ERROR out
            self.assertIn("Rerun needed (ERROR)", md)
            self.assertIn("2/2 tasks: both judges", md)   # t4 disagreement is excluded (ERROR)
            self.assertEqual(_agree(Path(d)), 0)

    def test_v1_rows_still_read(self):
        self.assertEqual(runner.verdict_of({"pass": True}), "PASS")
        self.assertEqual(runner.verdict_of({"pass": False}), "FAIL")


class JudgeRetryTests(unittest.TestCase):
    """Fix 2: judge retry (up to 2) and more output room for judge2."""

    def _task(self):
        return Task.load(TASK)

    def test_retries_empty_then_succeeds(self):
        calls = []

        def fake_chat(preset, system, user, max_tokens=0, **k):
            calls.append(max_tokens)
            if len(calls) < 3:
                raise RuntimeError(f"{preset} returned no text (finish_reason=length); raise max_tokens")
            return '{"pass": true, "score": 9, "failed": [], "summary": "ok"}', {"model": "m", "usd": 0.001}

        with mock.patch.object(judge_mod, "chat", fake_chat):
            v = judge_mod.JudgeQA("auto2").score(Output("# Page\ntext", meta={"model": "codex"}), self._task())
        self.assertTrue(v.passed); self.assertEqual(len(calls), 3); self.assertEqual(v.meta["attempts"], 3)
        self.assertEqual(calls[0], judge_mod.JUDGE2_MAX_TOKENS)
        self.assertGreater(judge_mod.JUDGE2_MAX_TOKENS, judge_mod.JUDGE_MAX_TOKENS)

    def test_gives_up_after_two_retries_as_judge_ran(self):
        n = []

        def fake_chat(*a, **k):
            n.append(1)
            raise RuntimeError("mimo HTTP 502: bad gateway")

        with mock.patch.object(judge_mod, "chat", fake_chat):
            v = judge_mod.JudgeQA("auto").score(Output("# Page\ntext", meta={"model": "codex"}), self._task())
        self.assertEqual(len(n), 3)
        self.assertEqual(v.checks[0].name, "judge_ran"); self.assertTrue(v.meta.get("judge_error"))

    def test_bad_json_is_retried(self):
        seq = ["not json at all", '{"pass": false, "score": 3, "failed": [], "summary": "bad"}']

        def fake_chat(*a, **k):
            return seq.pop(0), {"model": "m", "usd": 0.0}

        with mock.patch.object(judge_mod, "chat", fake_chat):
            v = judge_mod.JudgeQA("auto").score(Output("# Page\ntext", meta={"model": "codex"}), self._task())
        self.assertFalse(v.passed); self.assertEqual(v.meta["attempts"], 2)

    def test_missing_key_not_retried(self):
        n = []

        def fake_chat(*a, **k):
            n.append(1)
            raise RuntimeError("env var DEEPSEEK_API_KEY is not set (needed for deepseek-flash)")

        with mock.patch.object(judge_mod, "chat", fake_chat):
            judge_mod.JudgeQA("auto2").score(Output("# Page\ntext", meta={"model": "codex"}), self._task())
        self.assertEqual(len(n), 1)


class DeliverableFallbackTests(unittest.TestCase):
    """Fix 3: score the saved deliverable file when stdout is only narration (any adapter)."""

    def test_detects_narration(self):
        from aqh.adapters.cli_agents import deliverable_present
        self.assertFalse(deliverable_present("I'll read the task file and follow its instructions exactly."))
        self.assertFalse(deliverable_present(""))
        self.assertTrue(deliverable_present("# How we verify listings\n\nBody"))
        self.assertTrue(deliverable_present('[{"id": "x"}]'))

    def test_picks_deliverable_md_over_scratch(self):
        from aqh.adapters.cli_agents import find_deliverable_file
        with tempfile.TemporaryDirectory() as d:
            wd = Path(d); t0 = time.time()
            (wd / "TASK.md").write_text("task " * 500, encoding="utf-8")
            (wd / ".aqh-grok").mkdir(); (wd / ".aqh-grok" / "README.md").write_text("doc " * 900, encoding="utf-8")
            (wd / "draft_count.txt").write_text("word " * 300, encoding="utf-8")
            (wd / "DELIVERABLE.md").write_text("# Page\n" + "real " * 200, encoding="utf-8")
            name, body = find_deliverable_file(wd, t0)
            self.assertEqual(name, "DELIVERABLE.md"); self.assertTrue(body.startswith("# Page"))

    def test_falls_back_to_largest_written_file(self):
        from aqh.adapters.cli_agents import find_deliverable_file
        with tempfile.TemporaryDirectory() as d:
            wd = Path(d)
            (wd / "TASK.md").write_text("task " * 500, encoding="utf-8")
            (wd / "draft-count.txt").write_text("How we verify listings " * 80, encoding="utf-8")
            self.assertEqual(find_deliverable_file(wd, 0)[0], "draft-count.txt")
            (wd / "draft-count.txt").unlink()
            self.assertIsNone(find_deliverable_file(wd, 0))

    def test_run_uses_file_when_stdout_is_narration(self):
        """End to end through CLIAgent.run with a tiny python 'agent' that writes DELIVERABLE.md and prints narration."""
        from aqh.adapters import cli_agents
        script = ("import pathlib;pathlib.Path('DELIVERABLE.md').write_text('# Vegan restaurants in Denver\\n' + 'text ' * 200);"
                  "print(\"I'll read TASK.md and follow its instructions exactly.\")")

        class Narrator(cli_agents.CLIAgent):
            name, binary = "narrator", sys.executable

            def argv(self, prompt, wd):
                return [self.binary, "-c", script]

        with mock.patch.object(cli_agents, "_which", lambda c: sys.executable):
            out = Narrator().run(Task.load(TASK))
        self.assertTrue(out.text.startswith("# Vegan restaurants in Denver"))
        self.assertEqual(out.meta["deliverable_source"], "file:DELIVERABLE.md")

    def test_grok_prompt_asks_for_deliverable_file(self):
        from aqh.adapters.cli_agents import GrokBuild, FILE_PROMPT
        self.assertIn("DELIVERABLE.md", GrokBuild.file_prompt)
        self.assertTrue(GrokBuild.prefer_file_prompt)
        self.assertIn("final message must be the deliverable", GrokBuild.file_prompt)
        self.assertNotIn("--yolo", " ".join(GrokBuild().argv(FILE_PROMPT, Path("."))))


class CalibrationTests(unittest.TestCase):
    """Fix 4: judge calibration with known-good/known-bad answers; misgrade aborts final runs."""

    def test_cases_cover_three_task_types_with_files(self):
        doc = json.loads((ROOT / "calibration" / "cases.json").read_text(encoding="utf-8"))
        self.assertEqual({c["type"] for c in doc["cases"]}, {"listings", "city-page", "methodology-page"})
        for c in doc["cases"]:
            self.assertTrue((ROOT / c["good"]).is_file()); self.assertTrue((ROOT / c["bad"]).is_file())
            self.assertFalse(json.loads((ROOT / c["task"]).read_text(encoding="utf-8")).get("heldout"), "calibration must not use held-out tasks")

    def _fake_score(self, misgrade_bad=False):
        def score(self_j, out, task):
            bad = "As an AI language model" in out.text or "Green Leaf" in out.text or "[INSERT DATE]" in out.text
            passed = (not bad) or misgrade_bad
            return Verdict(passed, [Check("judge_pass", passed, "")], [] if passed else ["judge_pass: x"], {"score": 9 if passed else 2, "usd": 0})
        return score

    def test_calibration_passes_when_judges_grade_right(self):
        from aqh import calibrate
        with mock.patch.object(judge_mod.JudgeQA, "score", self._fake_score()):
            res = calibrate.run_calibration("default+judge+judge2")
        self.assertTrue(res["passed"]); self.assertEqual(len(res["results"]), 12)

    def test_calibration_fails_on_misgrade_and_suite_aborts(self):
        from aqh import calibrate, cli
        with mock.patch.object(judge_mod.JudgeQA, "score", self._fake_score(misgrade_bad=True)):
            res = calibrate.run_calibration("default+judge")
            self.assertFalse(res["passed"])
            with tempfile.TemporaryDirectory() as d:
                ran = []
                with mock.patch.object(cli, "get_agent", lambda n: ran.append(n)):
                    code = cli.main(["suite", "--agents", "echo-cli", "--suite", "suites/real-work-all.json",
                                     "--qa", "default+judge", "--include-heldout", "--out", d])
                self.assertEqual(code, 3); self.assertEqual(ran, [])
                self.assertFalse(json.loads((Path(d) / "calibration.json").read_text(encoding="utf-8"))["passed"])

    def test_judge_error_counts_as_misgrade(self):
        from aqh import calibrate

        def score(self_j, out, task):
            return Verdict(False, [Check("judge_ran", False, "HTTP 500")], ["judge_ran: HTTP 500"], {})
        with mock.patch.object(judge_mod.JudgeQA, "score", score):
            self.assertFalse(calibrate.run_calibration("default+judge")["passed"])

    def test_passing_calibration_is_reused(self):
        from aqh import calibrate
        n = []

        def fake_run(spec):
            n.append(1)
            return {"scoring": runner.SCORING_VERSION, "judges": ["judge:auto"], "passed": True, "results": []}
        with tempfile.TemporaryDirectory() as d:
            calibrate.ensure_calibrated("default+judge", Path(d), runner=fake_run)
            res = calibrate.ensure_calibrated("default+judge", Path(d), runner=fake_run)
        self.assertEqual(len(n), 1); self.assertTrue(res.get("reused"))


class OpenCodeCostTests(unittest.TestCase):
    """Fix 5: OpenCode records its OpenRouter cost in the ledger."""

    EVENTS = "\n".join(json.dumps(e) for e in [
        {"type": "step_start", "part": {"type": "step-start"}},
        {"type": "text", "part": {"type": "text", "text": "I'll read TASK.md."}},
        {"type": "step_finish", "part": {"type": "step-finish", "cost": 0.0021}},
        {"type": "step_start", "part": {"type": "step-start"}},
        {"type": "text", "part": {"type": "text", "text": "# Page\n"}},
        {"type": "text", "part": {"type": "text", "text": "Body text."}},
        {"type": "step_finish", "part": {"type": "step-finish", "cost": 0.0009, "modelID": "openrouter/x"}},
    ])

    def test_json_format_flag_and_last_step_text_and_cost(self):
        from aqh.adapters.cli_agents import OpenCode
        self.assertIn("--format", OpenCode().argv("p", Path("."))); self.assertNotIn("--auto", OpenCode().argv("p", Path(".")))
        text, meta = OpenCode().parse(self.EVENTS, Path("."))
        self.assertEqual(text, "# Page\nBody text.")
        self.assertAlmostEqual(meta["usd"], 0.003)

    def test_error_event_surfaces_credit_message(self):
        from aqh.adapters.cli_agents import parse_opencode_json
        text, meta = parse_opencode_json(json.dumps({"type": "error", "error": {"message": "This request requires more credits"}}))
        self.assertEqual(text, ""); self.assertIn("requires more credits", meta["error"])

    def test_plain_stdout_still_works(self):
        from aqh.adapters.cli_agents import parse_opencode_json
        self.assertEqual(parse_opencode_json("# Page\nplain")[0], "# Page\nplain")

    def test_cost_booked_in_ledger(self):
        from aqh import spend
        from aqh.adapters import cli_agents
        events = self.EVENTS.replace('"', '\\"').replace("\n", "\\n")

        class FakeOC(cli_agents.OpenCode):
            binary = sys.executable

            def argv(self, prompt, wd):
                return [self.binary, "-c", f"import sys;sys.stdout.write(\"{events}\")"]

        with tempfile.TemporaryDirectory() as d:
            led = Path(d) / "ledger.jsonl"
            with mock.patch.object(spend, "LEDGER", led), mock.patch.object(cli_agents, "_which", lambda c: sys.executable):
                out = FakeOC().run(Task.load(TASK))
            rows = [json.loads(l) for l in led.read_text(encoding="utf-8").splitlines()]
        self.assertAlmostEqual(out.meta["usd"], 0.003)
        self.assertEqual(out.meta["usd_source"], "opencode step_finish cost")
        self.assertAlmostEqual(sum(r["usd"] for r in rows), 0.003)

    def test_key_usage_delta_fallback(self):
        from aqh.adapters import cli_agents
        vals = iter([1.50, 1.62])
        with mock.patch.object(cli_agents, "openrouter_key_usage", lambda: next(vals)):
            oc = cli_agents.OpenCode(); st = oc.before_run(Path(".")); meta = {}
            oc.after_run(st, meta)
        self.assertAlmostEqual(meta["usd"], 0.12); self.assertIn("delta", meta["usd_source"])


class VersionTests(unittest.TestCase):
    def test_scoring_version_recorded(self):
        from aqh import locked, __version__
        cfg = locked.load()
        self.assertEqual(cfg["scoring_version"], runner.SCORING_VERSION)
        self.assertEqual(cfg["timeout_seconds"], 900); self.assertEqual(cfg["cap_usd"], 5.0)
        self.assertEqual(cfg["max_turns"], 30); self.assertFalse(cfg["permission_bypass"])
        self.assertEqual(cfg["judge_min_score"], 7.0); self.assertEqual(__version__, "0.3.0")


if __name__ == "__main__":
    unittest.main()
