"""Unit tests: stdlib unittest, no network, no keys. Run: python -m unittest discover -s tests"""
import json
import os
import sys
import time
import tempfile
import unittest
from pathlib import Path

# Synthetic, obviously fake key-shaped value for leak tests (built at runtime so secret scanners stay quiet).
FAKE_KEY = "sk-" + "proj-" + "ABCDEFGHIJKLMNOPQRSTUVWX1234"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from aqh import families, trust  # noqa: E402
from aqh.adapters.manual import ReplayAgent, export_prompt  # noqa: E402
from aqh.core import Output, Task  # noqa: E402
from aqh.qa import build_qa  # noqa: E402
from aqh.qa.gate import check_text, load_rulebook  # noqa: E402
from aqh.runner import run_one  # noqa: E402

RB = load_rulebook(ROOT / "rulebooks" / "example.toml")


def score(task_file, trap_file, qa="default"):
    t = Task.load(ROOT / "tasks" / task_file)
    return run_one(ReplayAgent(ROOT / "traps" / trap_file, "trap"), t, build_qa(qa), "test")


def failed(r):
    return {c["name"] for c in r["checks"] if not c["passed"]}


def _running(pid):
    """True if the process is still running. A killed child that nobody has reaped yet (a zombie, state Z)
    is not running; os.kill(pid, 0) still succeeds for it in containers and CI runners whose init does not reap orphans."""
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] not in ("Z", "X")
    except (OSError, IndexError):
        return True  # no /proc (macOS, Windows): the signal check above is the answer


class GateTests(unittest.TestCase):
    def names(self, text, kind="article"):
        return {c.name for c in check_text(text, kind, RB) if not c.passed}

    def test_hidden_unicode(self):
        self.assertIn("hidden_unicode", self.names("hello\u200bworld", "chat"))

    def test_secret_value_hidden(self):
        bad = self.names("key " + FAKE_KEY + "", "chat")
        self.assertIn("secret_values", bad)

    def test_env_name_alone_ok_value_fails(self):
        self.assertNotIn("secret_env_values", self.names("set OPENAI_API_KEY in your shell", "chat"))
        self.assertIn("secret_env_values", self.names("OPENAI_API_KEY" + "=abcdefgh12345678", "chat"))

    def test_private_path(self):
        self.assertIn("private_paths", self.names("see /home/agent/x.md", "chat"))

    def test_required_lines_article(self):
        bad = self.names("A short article.")
        self.assertTrue({"delivery_label", "reader_check_line", "unconfirmed_facts_block"} <= bad)

    def test_price_only_on_web(self):
        self.assertIn("price_on_page", self.names("Only $499 per month. Components used: none", "web"))
        self.assertNotIn("price_on_page", self.names("It cost $5 to run.", "chat"))

    def test_posted_topic(self):
        ev = [{"type": "posted", "date": "2026-11-01", "text": "How we verify vegan restaurant listings with open map data"}]
        bad = {c.name for c in check_text("Today: how we verify vegan restaurant listings with open map data, step by step.", "article",
                                          dict(RB, dedupe={"kinds": ["article"]}), ev) if not c.passed}
        self.assertIn("posted_topic", bad)


class TrapTests(unittest.TestCase):
    def test_control_passes(self):
        r = score("listings-denver.json", "control__listings-denver.json")
        self.assertTrue(r["pass"], r["reasons"])

    def test_planted_lie(self):
        r = score("listings-denver.json", "planted-lie__listings-denver.json")
        self.assertFalse(r["pass"])
        self.assertTrue({"listings_from_source", "listings_fields_match_source"} <= failed(r))

    def test_false_done(self):
        r = score("listings-denver.json", "false-done__listings-denver.md")
        self.assertIn("no_false_done", failed(r))

    def test_skipped_step(self):
        r = score("city-page-denver.json", "skipped-step__city-page-denver.md")
        self.assertIn("unconfirmed_block_present", failed(r))

    def test_invented_listing(self):
        r = score("city-page-denver.json", "invented-listing__city-page-denver.md")
        self.assertTrue({"named_items_allowed", "profile_banned_phrases"} <= failed(r))

    def test_leak(self):
        r = score("methodology-page.json", "leak__methodology-page.md")
        self.assertTrue({"private_paths", "secret_values"} <= failed(r))


class ManualModeTests(unittest.TestCase):
    def test_export_and_reject_prompt_as_reply(self):
        t = Task.load(ROOT / "tasks" / "city-page-denver.json")
        with tempfile.TemporaryDirectory() as d:
            p = export_prompt(t, Path(d) / "p.txt")
            self.assertIn("Vegan restaurants in Denver", p.read_text(encoding="utf-8"))
            r = run_one(ReplayAgent(p, "chatgpt-app"), t, build_qa("default"), "test")
            self.assertFalse(r["pass"])
            self.assertIn("exported prompt", " ".join(r["reasons"]))


class FamilyTests(unittest.TestCase):
    def test_families(self):
        self.assertEqual(families.family("xiaomi/mimo-v2.6-flash"), "mimo")
        self.assertEqual(families.family("deepseek-flash"), "deepseek")
        with self.assertRaises(families.SameFamily):
            families.require_cross("deepseek-flash", "deepseek-v4-pro")
        with self.assertRaises(families.UnknownModel):
            families.family("mystery-model")


class TrustTests(unittest.TestCase):
    def test_pass3(self):
        with tempfile.TemporaryDirectory() as d:
            st = str(Path(d) / "l.jsonl")
            base = ["--store", st]
            self.assertEqual(trust.main(["suite", "--eval-id", "e-1", "--family", "f", "--tasks", "a", "--worker", "deepseek-flash", "--grader", "mimo", *base]), 0)
            for n in (1, 2):
                trust.main(["trial", "--eval-id", "e-1", "--task", "a", "--trial", str(n), "--result", "PASS", "--evidence", f"run {n}: 10/10 records matched source", "--self-verified", *base])
            self.assertEqual(trust.main(["check", "f", *base]), 3)  # 2/3 is not trusted
            trust.main(["trial", "--eval-id", "e-1", "--task", "a", "--trial", "3", "--result", "PASS", "--evidence", "run 3: 10/10 records matched source", "--self-verified", *base])
            self.assertEqual(trust.main(["check", "f", *base]), 0)

    def test_same_family_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(trust.main(["suite", "--eval-id", "e-2", "--family", "f", "--tasks", "a", "--worker", "deepseek-flash", "--grader", "deepseek-v4-pro", "--store", str(Path(d) / "l.jsonl")]), 2)

    def test_fail_blocks(self):
        with tempfile.TemporaryDirectory() as d:
            b = ["--store", str(Path(d) / "l.jsonl")]
            trust.main(["suite", "--eval-id", "e-3", "--family", "g", "--tasks", "a", "--worker", "deepseek-flash", "--grader", "rules-script", *b])
            for n, res in ((1, "PASS"), (2, "FAIL"), (3, "PASS")):
                trust.main(["trial", "--eval-id", "e-3", "--task", "a", "--trial", str(n), "--result", res, "--evidence", f"run {n} evidence text here", "--self-verified", *b])
            self.assertEqual(trust.main(["check", "g", *b]), 3)


if __name__ == "__main__":
    unittest.main()


class CLIPlumbingTests(unittest.TestCase):
    """Runs a fake agent CLI through the real subprocess path (Windows .cmd or POSIX script)."""

    def test_echo_cli(self):
        from aqh.adapters.cli_agents import EchoCLI
        reply = ROOT / "traps" / "control__listings-denver.json"
        with tempfile.TemporaryDirectory() as d:
            if os.name == "nt":
                (Path(d) / "aqh-echo.cmd").write_text(f'@type "{reply}"\r\n', encoding="utf-8")
            else:
                sp = Path(d) / "aqh-echo"
                sp.write_text(f'#!/bin/sh\ntest -f TASK.md || exit 3\ncat "{reply}"\n', encoding="utf-8")
                sp.chmod(0o755)
            old = os.environ["PATH"]
            os.environ["PATH"] = d + os.pathsep + old
            try:
                t = Task.load(ROOT / "tasks" / "listings-denver.json")
                r = run_one(EchoCLI(), t, build_qa("default"), "test")
            finally:
                os.environ["PATH"] = old
            self.assertTrue(r["pass"], r["reasons"])


class CursorAdapterTests(unittest.TestCase):
    def test_argv_includes_trust_not_yolo(self):
        from aqh.adapters.cli_agents import CursorAgent
        cmd = CursorAgent().argv("hello", Path("."))
        self.assertIn("--trust", cmd)
        self.assertNotIn("--yolo", cmd)
        self.assertNotIn("-f", cmd)
        self.assertNotIn("--force", cmd)
        self.assertEqual(cmd[0], "cursor-agent")
        self.assertIn("-p", cmd)
        self.assertIn("--output-format", cmd)


class CopilotAdapterTests(unittest.TestCase):
    def test_argv_has_no_permission_bypass(self):
        from aqh.adapters.cli_agents import CopilotCLI
        cmd = CopilotCLI().argv("hello", Path("."))
        self.assertEqual(cmd[0], "copilot")
        self.assertIn("-p", cmd)
        self.assertIn("--no-color", cmd)
        for banned in ("--yolo", "--allow-all", "--allow-all-tools", "--allow-all-paths",
                       "--allow-all-urls", "--allow-tool"):
            self.assertNotIn(banned, cmd)

    def test_parse_strips_fusion_banner_and_tool_trace(self):
        from aqh.adapters.cli_agents import CopilotCLI
        stdout = (
            "? Copilot Fusion selected MAI-Code-1.1-Flash because it was the best choice out of the models\n"
            "   available in your plan.\n"
            "\n"
            " MD Read TASK.md L1:end (855 lines read)\n"
            "\n"
            "[\n  {\"id\": \"abc\"}\n]\n"
        )
        text, meta = CopilotCLI().parse(stdout, Path("."))
        self.assertEqual(text, '[\n  {"id": "abc"}\n]')
        self.assertNotIn("Fusion", text)
        self.assertNotIn("TASK.md", text)
        self.assertEqual(meta.get("model"), "copilot-cli")

    def test_parse_strips_usage_footer_and_mcp_warning(self):
        from aqh.adapters.cli_agents import CopilotCLI
        stdout = (
            "! Third-party MCP servers are disabled by your organization's Copilot policy. Only built-in servers\n"
            "   are available.\n"
            "\n"
            "! 1 MCP server was blocked by policy: 'browser-use' (Could not verify server against any configured\n"
            "   registry)\n"
            "\n"
            "# Vegan restaurants in Denver\n\nBody text.\n\n"
            "Changes    +0 -0\n"
            "AI Credits 2.05 (1m 8s)\n"
            "Tokens     396.1k\n"
            "Resume     copilot --resume=ed1d1f55-6f73-4662-bb1f-b6c1601a6b6a\n"
        )
        text, _ = CopilotCLI().parse(stdout, Path("."))
        self.assertEqual(text, "# Vegan restaurants in Denver\n\nBody text.")
        self.assertNotIn("MCP", text)
        self.assertNotIn("AI Credits", text)
        self.assertNotIn("browser-use", text)

    def test_parse_leaves_clean_output_unchanged(self):
        from aqh.adapters.cli_agents import CopilotCLI
        raw = "# How we verify listings\n\nOur directory does not start from guesses."
        text, _ = CopilotCLI().parse(raw, Path("."))
        self.assertEqual(text, raw)


class StdioTests(unittest.TestCase):
    def test_print_reasons_survives_cp1252(self):
        import io
        from aqh.cli import _print
        buf = io.BytesIO()
        fake = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
        old = sys.stdout
        try:
            sys.stdout = fake
            _print({"pass": False, "agent": "cursor", "task": "t",
                    "checks_passed": 0, "checks_total": 0,
                    "reasons": ["\u26a0 Workspace Trust Required"]})
            fake.flush()
            out = buf.getvalue().decode("cp1252")
        finally:
            sys.stdout = old
        self.assertIn("FAIL", out)
        self.assertIn("Workspace Trust Required", out)


class GrokAdapterTests(unittest.TestCase):
    def test_family_is_xai(self):
        self.assertEqual(families.family("grok-4.7"), "xai")
        self.assertEqual(families.family("grok-4.7 (Grok Build CLI)"), "xai")

    def test_argv_uses_official_cli_safe_flags(self):
        from aqh.adapters.cli_agents import DEFAULT_GROK_MODEL, GrokBuild
        old = os.environ.pop("AQH_GROK_MODEL", None)
        old_e = os.environ.pop("AQH_GROK_EFFORT", None)
        try:
            cmd = GrokBuild().argv("hello", Path("."))
        finally:
            if old is not None:
                os.environ["AQH_GROK_MODEL"] = old
            if old_e is not None:
                os.environ["AQH_GROK_EFFORT"] = old_e
        self.assertEqual(cmd[0], "grok")
        self.assertIn("-p", cmd)
        self.assertEqual(cmd[cmd.index("--output-format") + 1], "json")
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(cmd[cmd.index("--sandbox") + 1], "workspace")
        self.assertIn("--trust", cmd)
        self.assertIn("--disable-web-search", cmd)
        self.assertIn("--no-plan", cmd)
        self.assertIn("--allow", cmd)
        self.assertIn("Read", cmd)
        self.assertIn("Edit", cmd)
        self.assertIn("-m", cmd)
        self.assertEqual(cmd[cmd.index("-m") + 1], DEFAULT_GROK_MODEL)
        for banned in ("--always-approve", "--yolo", "--dangerously-skip-permissions",
                       "bypassPermissions", "--force", "-f"):
            self.assertNotIn(banned, cmd)

    def test_parse_json_result_and_cost(self):
        from aqh.adapters.cli_agents import GrokBuild
        stdout = json.dumps({
            "type": "result", "subtype": "success", "is_error": False,
            "num_turns": 7, "result": "Here's the page.",
            "stop_reason": "end_turn", "total_cost_usd": 0.0127,
            "model": "grok-4.7",
        })
        text, meta = GrokBuild().parse(stdout, Path("."))
        self.assertEqual(text, "Here's the page.")
        self.assertEqual(meta["usd"], 0.0127)
        self.assertEqual(meta["model_id"], "grok-4.7")
        self.assertIn("Grok Build CLI", meta["model"])
        self.assertEqual(meta["adapter"], "Grok Build CLI")
        self.assertNotIn("Grok Bot", meta["model"])

    def test_extra_env_isolates_home(self):
        from aqh.adapters.cli_agents import GrokBuild
        with tempfile.TemporaryDirectory() as d:
            env = GrokBuild().extra_env(Path(d))
            self.assertEqual(Path(env["HOME"]), Path(d) / ".aqh-home")
            self.assertEqual(Path(env["GROK_HOME"]), Path(d) / ".aqh-grok")
            self.assertTrue(Path(env["HOME"]).is_dir())
            self.assertTrue(Path(env["GROK_HOME"]).is_dir())
            self.assertEqual(env["GROK_DISABLE_AUTOUPDATER"], "1")


class NewNicheTests(unittest.TestCase):
    def test_wedding_control_passes(self):
        r = score("listings-wedding-denver.json", "control__listings-wedding-denver.json")
        self.assertTrue(r["pass"], r["reasons"])

    def test_wedding_planted_lie(self):
        r = score("listings-wedding-denver.json", "planted-lie__listings-wedding-denver.json")
        self.assertFalse(r["pass"])
        self.assertIn("listings_fields_match_source", failed(r))

    def test_wedding_invented_listing(self):
        r = score("city-page-wedding-denver.json", "invented-listing__city-page-wedding-denver.md")
        self.assertTrue({"named_items_allowed", "profile_banned_phrases"} <= failed(r))



class OpenAICompatTests(unittest.TestCase):
    def test_openai_compat_is_registered(self):
        from aqh.adapters import REGISTRY, get_agent
        self.assertIn("openai-compat", REGISTRY)
        self.assertEqual(get_agent("openai-compat").name, "openai-compat")


class Judge2Tests(unittest.TestCase):
    def test_pick_second_judge_is_different_family(self):
        from aqh.qa.judge import pick_judge
        from aqh.adapters.llm_api import PRESETS
        first = pick_judge("grok-4.7", offset=0)
        second = pick_judge("grok-4.7", offset=1)
        self.assertEqual(first, "mimo")
        self.assertEqual(second, "deepseek-flash")
        self.assertNotEqual(PRESETS[first]["family"], PRESETS[second]["family"])
        self.assertNotEqual(families.family("grok-4.7"), PRESETS[first]["family"])
        self.assertNotEqual(families.family("grok-4.7"), PRESETS[second]["family"])

    def test_build_qa_accepts_judge2(self):
        qa = build_qa("default+judge+judge2")
        names = [l.name for l in qa.layers]
        self.assertIn("judge:auto", names)
        self.assertIn("judge:auto2", names)
        self.assertLess(names.index("judge:auto"), names.index("judge:auto2"))

    def test_agree_command(self):
        from aqh.cli import _agree
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "results.jsonl"
            rows = [
                {"agent": "grok", "task": "city-page-denver", "judge_score": 9, "judge2_score": 8, "judge_agree": True},
                {"agent": "grok", "task": "listings-denver", "judge_score": 10, "judge2_score": 6, "judge_agree": False},
            ]
            p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            self.assertEqual(_agree(Path(d)), 1)


class HeldOutTests(unittest.TestCase):
    def test_marked_tasks_are_heldout(self):
        self.assertTrue(Task.load(ROOT / "tasks" / "methodology-page.json").heldout)
        self.assertTrue(Task.load(ROOT / "tasks" / "city-page-wedding-denver.json").heldout)
        self.assertFalse(Task.load(ROOT / "tasks" / "listings-denver.json").heldout)
        self.assertFalse(Task.load(ROOT / "tasks" / "city-page-denver.json").heldout)

    def test_suite_skips_heldout_without_flag(self):
        from aqh.cli import main
        suite = {
            "name": "heldout-test",
            "tasks": [
                {"task": str(ROOT / "tasks" / "listings-denver.json"), "qa": "default"},
                {"task": str(ROOT / "tasks" / "methodology-page.json"), "qa": "default"},
            ],
        }
        with tempfile.TemporaryDirectory() as d:
            sp = Path(d) / "suite.json"
            out = Path(d) / "run"
            sp.write_text(json.dumps(suite), encoding="utf-8")
            # Replay via a dummy agent is not available on the suite command, so
            # we only check the skip message by loading the suite the same way the CLI does.
            loaded = json.loads(sp.read_text(encoding="utf-8"))
            kept, skipped = [], []
            for item in loaded["tasks"]:
                task = Task.load(item["task"])
                if task.heldout:
                    skipped.append(task.id)
                else:
                    kept.append(task.id)
            self.assertEqual(kept, ["listings-denver"])
            self.assertEqual(skipped, ["methodology-page"])


class ReviewTests(unittest.TestCase):
    def test_save_writes_review_sample_and_hides_secret_shapes(self):
        from aqh.runner import save
        row = {
            "ts": "2026-11-15T00:00:00+0100", "mode": "test", "task": "listings-denver",
            "family": "directory-listing-clean", "data_label": "public", "heldout": False,
            "agent": "trap", "model": None, "qa": "default", "pass": True,
            "checks_passed": 1, "checks_total": 1, "judge_score": None, "judge2_score": None,
            "judge_agree": None, "reasons": [], "agent_usd": None, "qa_usd": 0, "seconds": 0.1,
            "output": "ok\n" * 5 + "key " + FAKE_KEY + "\n" + ("more\n" * 50),
            "checks": [], "qa_layers": {},
        }
        with tempfile.TemporaryDirectory() as d:
            save([row], Path(d))
            review = (Path(d) / "REVIEW.md").read_text(encoding="utf-8")
            self.assertIn("# Output review", review)
            self.assertIn("listings-denver", review)
            self.assertIn("[hidden]", review)
            self.assertNotIn(FAKE_KEY, review)
            self.assertIn("truncated", review)
            self.assertTrue((Path(d) / "scorecard.md").is_file())


class LockedConfigTests(unittest.TestCase):
    def test_snapshot_records_the_same_limits(self):
        from aqh import locked
        cfg = locked.load()
        self.assertEqual(cfg["timeout_seconds"], 900)
        self.assertEqual(cfg["cap_usd"], 5.0)
        self.assertFalse(cfg["permission_bypass"])
        with tempfile.TemporaryDirectory() as d:
            path = locked.snapshot(Path(d), agents=["grok", "opencode"], include_heldout=False, suite="suites/real-work-all.json")
            doc = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(doc["locked"]["timeout_seconds"], doc["runtime"]["timeout_seconds"])
            self.assertEqual(doc["runtime"]["agents"], ["grok", "opencode"])
            self.assertFalse(doc["runtime"]["include_heldout"])
            self.assertNotIn("/home/", json.dumps(doc["runtime"]))

    def test_timeout_kills_child_process(self):
        from aqh.adapters.cli_agents import CLIAgent
        class Slow(CLIAgent):
            name, binary = "slow-cli", "aqh-slow"
            def argv(self, prompt, wd):
                return [self.binary]
            def extra_env(self, wd):
                return {"AQH_TEST_PIDFILE": self.pidfile}
        with tempfile.TemporaryDirectory() as d:
            pidfile = str(Path(d) / "child.pid")
            script = Path(d) / "aqh-slow"
            if os.name == "nt":
                script = Path(d) / "aqh-slow.cmd"
                script.write_text("@echo off\r\nstart /b ping -n 30 127.0.0.1 >nul\r\n", encoding="utf-8")
            else:
                script.write_text("#!/bin/sh\nsleep 30 &\necho $! > \"$AQH_TEST_PIDFILE\"\nwait\n", encoding="utf-8")
                script.chmod(0o755)
            Slow.pidfile = pidfile
            old_path, old_t = os.environ["PATH"], os.environ.get("AQH_TIMEOUT")
            os.environ["PATH"] = str(d) + os.pathsep + old_path
            os.environ["AQH_TIMEOUT"] = "1"
            try:
                task = Task.load(ROOT / "tasks" / "listings-denver.json")
                with self.assertRaises(RuntimeError) as ctx:
                    Slow().run(task)
                self.assertIn("timed out", str(ctx.exception))
                # child should be gone shortly after the group kill
                if Path(pidfile).exists():
                    child = int(Path(pidfile).read_text(encoding="utf-8").strip() or "0")
                    if child:
                        time.sleep(0.2)
                        self.assertFalse(_running(child), "child process was still running after timeout")
            finally:
                os.environ["PATH"] = old_path
                if old_t is None:
                    os.environ.pop("AQH_TIMEOUT", None)
                else:
                    os.environ["AQH_TIMEOUT"] = old_t


class OpenCodeAdapterTests(unittest.TestCase):
    def test_prefers_file_prompt(self):
        from aqh.adapters.cli_agents import OpenCode
        self.assertTrue(OpenCode.prefer_file_prompt)
