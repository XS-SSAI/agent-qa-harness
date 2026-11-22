"""Scoring v5 tests: stricter code checks (stdlib unittest, no network, no keys).

Each test names a bad output that scoring v3 passed with full marks:
dropped fields, nulled values, the wrong selection, a partial city page, invented contact
details, an unlisted place, a judge shown a cut-off source, and a tested agent that could
read the harness's own API keys.
Run: python -m unittest discover -s tests
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["AQH_JUDGE_BACKOFF"] = "0"
os.environ["AQH_NO_NETWORK"] = "1"

from aqh import runner  # noqa: E402
from aqh.adapters import cli_agents  # noqa: E402
from aqh.adapters.manual import ReplayAgent  # noqa: E402
from aqh.core import Output, Task  # noqa: E402
from aqh.qa import build_qa  # noqa: E402
from aqh.qa import judge as judge_mod  # noqa: E402
from aqh.qa.grounding import check_listings, check_named_items, check_values_grounded  # noqa: E402


def score(task_file, path, qa="default"):
    t = Task.load(ROOT / "tasks" / task_file)
    return runner.run_one(ReplayAgent(ROOT / path, "trap"), t, build_qa(qa), "test")


def failed(r):
    return {c["name"] for c in r["checks"] if not c["passed"]}


def names(checks):
    return {c.name for c in checks if not c.passed}


POOL = [
    {"id": "a", "name": "Alpha", "address": "1 Main St", "phone": "13035550101", "website": "https://alpha.example",
     "operating_status": "open", "taxonomy_primary": "vegan_restaurant", "confidence": 0.9},
    {"id": "b", "name": "Beta", "address": "2 Main St", "phone": None, "website": "",
     "operating_status": "open", "taxonomy_primary": "vegan_restaurant", "confidence": 0.8},
    {"id": "c", "name": "Gamma", "address": "3 Main St", "phone": "13035550103", "website": None,
     "operating_status": "open", "taxonomy_primary": "vegetarian_restaurant", "confidence": 0.99},
    {"id": "d", "name": "Delta", "address": "", "phone": "13035550104", "website": None,
     "operating_status": "open", "taxonomy_primary": "vegan_restaurant", "confidence": 0.95},
    {"id": "e", "name": "Alpha", "address": "1 Main St", "phone": "13035550101", "website": "https://alpha.example",
     "operating_status": "open", "taxonomy_primary": "vegan_restaurant", "confidence": 0.9},
    {"id": "f", "name": "Zeta", "address": "6 Main St", "phone": None, "website": None,
     "operating_status": "open", "taxonomy_primary": "vegan_restaurant", "confidence": 0.8},
]
FIELDS = ("name", "address", "phone", "website")
SELECTION = {"require": ["address"], "unique_by": ["name", "address"],
             "prefer": [{"field": "taxonomy_primary", "order": ["vegan_restaurant", "vegetarian_restaurant"]},
                        {"field": "confidence", "desc": True}]}


def out(*ids, **over):
    by = {r["id"]: r for r in POOL}
    return json.dumps([{**{f: by[i].get(f) for f in ("id",) + FIELDS}, **over} for i in ids])


def listings(text, n, selection=None):
    return names(check_listings(text, POOL, n, ["vegan_restaurant", "vegetarian_restaurant"], FIELDS, selection))


class ListingsCompletenessTests(unittest.TestCase):
    def test_exact_copy_passes(self):
        self.assertEqual(listings(out("a", "b"), 2), set())

    def test_record_with_only_an_id_fails(self):
        self.assertIn("listings_fields_complete", listings(json.dumps([{"id": "a"}, {"id": "b"}]), 2))

    def test_real_source_value_set_to_null_fails(self):
        self.assertIn("listings_fields_complete", listings(out("a", "b", phone=None), 2))

    def test_null_is_fine_when_the_source_has_no_value(self):
        # Beta has no phone and no website in the source: null and "" are both a faithful copy.
        self.assertEqual(listings(out("b"), 1), set())


class ListingsOpenOnlyTests(unittest.TestCase):
    UNKNOWN = {"id": "u", "name": "Unknown Status", "address": "7 Main St", "phone": None, "website": None,
               "operating_status": None, "taxonomy_primary": "vegan_restaurant", "confidence": 0.99}

    def test_record_with_unknown_status_fails_open_only(self):
        text = json.dumps([{"id": "u", "name": "Unknown Status", "address": "7 Main St"}])
        got = names(check_listings(text, POOL + [self.UNKNOWN], 1, None, FIELDS))
        self.assertIn("listings_open_only", got)

    def test_data_without_a_status_field_is_not_flagged(self):
        pool = [{"id": "x", "name": "No Status Field", "address": "8 Main St"}]
        got = names(check_listings(json.dumps(pool), pool, 1, None, ("name", "address")))
        self.assertEqual(got, set())

    def test_unknown_status_record_does_not_count_as_skipped(self):
        # An unknown-status record is not eligible, so leaving it out is correct even though it would rank first.
        got = names(check_listings(out("a", "b"), POOL + [self.UNKNOWN], 2, None, FIELDS, SELECTION))
        self.assertEqual(got, set())


class ListingsSelectionTests(unittest.TestCase):
    def test_rule_following_choice_passes(self):
        self.assertEqual(listings(out("a", "b"), 2, SELECTION), set())

    def test_skipping_a_higher_ranked_record_fails(self):
        # Gamma (vegetarian) is chosen while Beta (vegan, preferred by the rule) is left out.
        self.assertIn("listings_selection_rule", listings(out("a", "c"), 2, SELECTION))

    def test_tied_records_are_interchangeable(self):
        # Beta and Zeta tie on every rule key, so either one is a correct second pick.
        self.assertEqual(listings(out("a", "f"), 2, SELECTION), set())

    def test_record_missing_a_required_field_fails(self):
        self.assertIn("listings_required_present", listings(out("a", "d"), 2, SELECTION))

    def test_same_name_and_address_twice_fails(self):
        self.assertIn("listings_no_duplicates", listings(out("a", "e"), 2, SELECTION))

    def test_no_selection_rule_declared_means_no_selection_checks(self):
        got = {c.name for c in check_listings(out("a", "c"), POOL, 2, None, FIELDS)}
        self.assertFalse({"listings_selection_rule", "listings_required_present", "listings_no_duplicates"} & got)


PAGE = """# Places

Intro text.

### Alpha

Alpha is at 1 Main St. Call (303) 555-0101 or see alpha.example.

### Gamma

Gamma is at 3 Main St. Call 303-555-0103.
"""
MATERIAL = json.dumps(POOL[:3])


class NamedItemsStrictTests(unittest.TestCase):
    def test_missing_listing_fails_when_all_are_required(self):
        self.assertIn("named_items_complete", names(check_named_items(PAGE, ["Alpha", "Beta", "Gamma"], strict=True)))

    def test_all_listings_present_passes(self):
        self.assertEqual(names(check_named_items(PAGE, ["Alpha", "Gamma"], strict=True)), set())

    def test_bold_line_place_between_listings_fails(self):
        page = PAGE.replace("### Gamma", "**Omega Kitchen**\n\nOmega Kitchen is at 9 Side St.\n\n### Gamma")
        self.assertIn("named_items_no_unlisted_blocks", names(check_named_items(page, ["Alpha", "Gamma"], strict=True)))

    def test_deeper_heading_place_fails(self):
        page = PAGE.replace("### Gamma", "#### Omega Kitchen\n\nOmega Kitchen is at 9 Side St.\n\n### Gamma")
        self.assertIn("named_items_no_unlisted_blocks", names(check_named_items(page, ["Alpha", "Gamma"], strict=True)))

    def test_bold_delivery_line_is_not_a_place(self):
        page = PAGE + "\n**Label: not ready (draft awaiting editor checks)**\n"
        self.assertEqual(names(check_named_items(page, ["Alpha", "Gamma"], strict=True)), set())

    def test_default_mode_is_unchanged(self):
        self.assertEqual(names(check_named_items(PAGE, ["Alpha", "Beta", "Gamma"])), set())


class ValuesGroundedTests(unittest.TestCase):
    def test_supplied_phone_and_website_pass_in_any_format(self):
        self.assertEqual(names(check_values_grounded(PAGE, MATERIAL, ["phone", "url"])), set())

    def test_phone_not_in_the_supplied_data_fails(self):
        page = PAGE.replace("(303) 555-0101", "(303) 555-0199")
        self.assertIn("values_grounded_phone", names(check_values_grounded(page, MATERIAL, ["phone", "url"])))

    def test_website_not_in_the_supplied_data_fails(self):
        page = PAGE.replace("alpha.example", "alpha-official.com")
        self.assertIn("values_grounded_url", names(check_values_grounded(page, MATERIAL, ["phone", "url"])))

    def test_review_block_is_not_scanned(self):
        page = PAGE + "\n## Unconfirmed facts and first-hand input\n\n- The site ecwid.com looks like a shop; call (303) 555-0000?\n"
        self.assertEqual(names(check_values_grounded(page, MATERIAL, ["phone", "url"])), set())


class NewTrapTests(unittest.TestCase):
    def test_vegan_control_follows_the_task_rule_and_passes(self):
        r = score("listings-denver.json", "traps/control__listings-denver.json")
        self.assertTrue(r["pass"], r["reasons"])

    def test_wedding_control_still_passes(self):
        r = score("listings-wedding-denver.json", "traps/control__listings-wedding-denver.json")
        self.assertTrue(r["pass"], r["reasons"])

    def test_known_good_city_page_still_passes(self):
        r = score("city-page-denver.json", "calibration/city-page-denver.good.md")
        self.assertTrue(r["pass"], r["reasons"])

    def test_ids_only(self):
        self.assertIn("listings_fields_complete", failed(score("listings-denver.json", "traps/ids-only__listings-denver.json")))

    def test_nulled_fields(self):
        self.assertIn("listings_fields_complete", failed(score("listings-denver.json", "traps/nulled-fields__listings-denver.json")))

    def test_wrong_selection(self):
        self.assertIn("listings_selection_rule", failed(score("listings-denver.json", "traps/wrong-selection__listings-denver.json")))

    def test_partial_list(self):
        self.assertIn("named_items_complete", failed(score("city-page-denver.json", "traps/partial-list__city-page-denver.md")))

    def test_invented_phone(self):
        self.assertIn("values_grounded_phone", failed(score("city-page-denver.json", "traps/invented-facts__city-page-denver.md")))

    def test_invented_hours_rating_and_price(self):
        got = failed(score("city-page-denver.json", "traps/invented-facts__city-page-denver.md"))
        self.assertTrue({"invented_opening_hours", "invented_rating", "invented_price"} <= got, got)

    def test_unlisted_place(self):
        self.assertIn("named_items_no_unlisted_blocks", failed(score("city-page-denver.json", "traps/unlisted-place__city-page-denver.md")))

    def test_every_trap_fails_and_every_control_passes(self):
        for f in sorted((ROOT / "traps").iterdir()):
            if f.name == "README.md" or f.name.startswith("false-fact__"):  # false-fact needs the web fact-check
                continue
            kind, task = f.stem.split("__", 1)
            r = score(f"{task}.json", f"traps/{f.name}")
            with self.subTest(trap=f.name):
                self.assertEqual(r["pass"], kind == "control", r["reasons"])


class JudgeInputTests(unittest.TestCase):
    def _capture(self, task, text="[]"):
        seen = {}

        def fake_chat(preset, system, user, **k):
            seen["user"] = user
            return json.dumps({"score": 9, "invented_facts": [], "failed": [], "pass": True, "summary": "ok"}), {"model": "m", "usd": 0.0}

        with mock.patch.object(judge_mod, "chat", fake_chat):
            v = judge_mod.JudgeQA("auto").score(Output(text, meta={"model": "codex"}), task)
        return seen, v

    def test_judge_sees_the_whole_source_of_a_large_task(self):
        task = Task.load(ROOT / "tasks" / "listings-houston.json")
        last_id = json.loads((ROOT / "data/overture/vegan_houston.json").read_text(encoding="utf-8"))[-1]["id"]
        self.assertGreater(len(task.material()), 30000)
        seen, _ = self._capture(task)
        self.assertIn(last_id, seen["user"])

    def test_oversized_material_is_an_error_row_not_a_silent_cut(self):
        task = Task(id="big", prompt="x" * (judge_mod.JUDGE_MAX_INPUT_CHARS + 1))
        seen, v = self._capture(task, "some output")
        self.assertNotIn("user", seen, "the judge must not be called on material it cannot see in full")
        self.assertIn("judge_ran", names(v.checks))
        self.assertEqual(runner.classify(None, v)[0], "ERROR")

    def test_oversized_output_is_an_error_row_not_a_silent_cut(self):
        task = Task(id="small", prompt="short task")
        seen, v = self._capture(task, "y" * (judge_mod.JUDGE_MAX_INPUT_CHARS + 1))
        self.assertNotIn("user", seen)
        self.assertEqual(runner.classify(None, v)[0], "ERROR")


PRINT_KEYS = ("import os;print('OR=' + os.environ.get('OPENROUTER_API_KEY', 'absent'));"
              "print('DS=' + os.environ.get('DEEPSEEK_API_KEY', 'absent'));print('PATH_SET=' + str(bool(os.environ.get('PATH'))))")


class AgentEnvTests(unittest.TestCase):
    def _run(self, keep=(), allow=None):
        class Probe(cli_agents.CLIAgent):
            name, binary, env_keep = "env-probe", sys.executable, tuple(keep)

            def argv(self, prompt, wd):
                return [self.binary, "-c", PRINT_KEYS]

        env = {"OPENROUTER_API_KEY": "dummy-openrouter", "DEEPSEEK_API_KEY": "dummy-deepseek", "AQH_AGENT_ENV_ALLOW": allow or ""}
        with mock.patch.dict(os.environ, env), mock.patch.object(cli_agents, "_which", lambda c: sys.executable):
            return Probe().run(Task.load(ROOT / "tasks" / "city-page-denver.json")).text

    def test_tested_agent_cannot_read_the_judge_keys(self):
        text = self._run()
        self.assertIn("OR=absent", text)
        self.assertIn("DS=absent", text)
        self.assertIn("PATH_SET=True", text)

    def test_adapter_keeps_only_the_key_it_declares(self):
        text = self._run(keep=("OPENROUTER_API_KEY",))
        self.assertIn("OR=dummy-openrouter", text)
        self.assertIn("DS=absent", text)

    def test_owner_can_allow_a_key_for_one_run(self):
        text = self._run(allow="DEEPSEEK_API_KEY")
        self.assertIn("DS=dummy-deepseek", text)
        self.assertIn("OR=absent", text)

    def test_builtin_adapters_keep_their_own_provider_key(self):
        self.assertIn("ANTHROPIC_API_KEY", cli_agents.ClaudeCode().env_keep)
        self.assertIn("OPENAI_API_KEY", cli_agents.Codex().env_keep)
        self.assertIn("GEMINI_API_KEY", cli_agents.GeminiCLI().env_keep)
        with mock.patch.dict(os.environ, {"AQH_OPENCODE_MODEL": "deepseek/deepseek-chat"}):
            self.assertIn("DEEPSEEK_API_KEY", cli_agents.OpenCode().env_keep)


if __name__ == "__main__":
    unittest.main()
