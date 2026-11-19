"""Scoring v4: known-answer trap set (plant functions, judge scoring rule) and Jev classifier-judge decisions."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aqh import jevjudge as J
from aqh import trapset as T

LIST = json.dumps([{"id": "a", "name": "A", "phone": "1", "check_before_publish": "Confirm hours on the site today."},
                   {"id": "b", "name": "B", "phone": "2", "check_before_publish": "Confirm menu on the site today."}])
PAGE = ("# Title\n\nIntro paragraph here.\n\n### Place One\n\nPlace One is at 1 Main St.\n\n### Place Two\n\nPlace Two is at 2 Main St.\n\n"
        "Featured placements are always disclosed.\n\nExample Directory, a brand of Example Media LLC.\n\n"
        "Label: not ready (draft awaiting editor checks)\n\nHuman-reader check: pending\n\n"
        "## Unconfirmed facts and first-hand input\n\n### Claims I could not source-check\n- x\n\n### First-hand input needed\n1. y\n")


KEY = [{"id": "t1", "expected": "FAIL", "fault_kind": "invented"}, {"id": "t2", "expected": "FAIL", "fault_kind": "skipped"},
           {"id": "c1", "expected": "PASS", "fault_kind": None}, {"id": "c2", "expected": "PASS", "fault_kind": None}]


class TrapSetV4Tests(unittest.TestCase):
    def test_json_plants_change_exactly_what_they_say(self):
        assert json.loads(T.set_fields(LIST, 0, {"phone": "9"}))[0]["phone"] == "9"
        assert json.loads(T.replace_record(LIST, 1, {"id": "z", "name": "Invented"}))[1] == {"id": "z", "name": "Invented", "phone": "2",
                                                                                               "check_before_publish": "Confirm menu on the site today."}
        assert all("check_before_publish" not in o for o in json.loads(T.drop_field(LIST, "check_before_publish")))
        assert len(json.loads(T.keep_records(LIST, 1))) == 1
        assert {o["check_before_publish"] for o in json.loads(T.set_all(LIST, "check_before_publish", "done"))} == {"done"}
        assert json.loads(T.add_fields(LIST, 0, {"price": "$1"}))[0]["price"] == "$1"


    def test_json_plants_refuse_no_ops(self):
        with self.assertRaises(T.PlantError):
            T.set_fields(LIST, 0, {"phone": "1"})
        with self.assertRaises(T.PlantError):
            T.keep_records(LIST, 2)
        with self.assertRaises(T.PlantError):
            T.drop_field(LIST, "price")
        with self.assertRaises(T.PlantError):
            T.add_fields(LIST, 0, {"phone": "3"})
        with self.assertRaises(T.PlantError):
            T.set_all(json.dumps([{"x": 1}]), "x", 1)


    def test_insert_after_first_listing_stays_in_the_first_listing_paragraph(self):
        out = T.insert_after_first_listing(PAGE, "Open daily 11-10.")
        assert "Place One is at 1 Main St. Open daily 11-10.\n\n### Place Two" in out
        assert out.count("Open daily") == 1
        with self.assertRaises(T.PlantError):
            T.insert_after_first_listing("# T\n\nno headings\n", "x")
        with self.assertRaises(T.PlantError):  # the first ### heading is followed by a list, not prose
            T.insert_after_first_listing("# T\n\n### Claims\n- a\n", "x")


    def test_markdown_plants(self):
        assert T.REVIEW_HEADING not in T.remove_review_block(PAGE)
        no1 = T.remove_listing(PAGE, 0)  # a middle section stops at the next heading
        assert "### Place One" not in no1 and "Place One is" not in no1 and "### Place Two" in no1
        assert "Featured" not in T.remove_paragraphs(PAGE, "featur").split(T.REVIEW_HEADING)[0]
        assert "### Place One" in T.remove_paragraphs(PAGE, "place one")  # headings are kept
        assert "Example Directory, a brand" not in T.remove_line(PAGE, "Example Directory, a brand")
        fd = T.false_done(PAGE, "All verified.")
        assert "Label: final, ready to go live" in fd and "Human-reader check: done" in fd and "All verified.\n\nLabel:" in fd
        assert T.insert_after_title(PAGE, "By Jane").startswith("# Title\n\nBy Jane")
        assert T.insert_paragraph_before(PAGE, "Label:", "Price $1.").count("Price $1.\n\nLabel:") == 1
        with self.assertRaises(T.PlantError):
            T.insert_paragraph_before(PAGE, "nope", "x")
        with self.assertRaises(T.PlantError):
            T.remove_review_block("# no block\n")
        with self.assertRaises(T.PlantError):
            T.remove_paragraphs(PAGE, "zzz")




    def test_score_judge_counts_catches_false_alarms_and_kinds(self):
        s = T.score_judge(KEY, {"t1": False, "t2": True, "c1": True, "c2": False})
        assert (s["caught"], s["traps"], s["false_alarms"], s["controls"]) == (1, 2, 1, 2)
        assert s["catch_rate"] == 0.5 and s["false_alarm_rate"] == 0.5 and not s["qualifies"]
        assert s["by_kind"] == {"invented": {"caught": 1, "n": 1}, "skipped": {"caught": 0, "n": 1}}
        assert s["missed"] == ["t2"] and s["alarmed"] == ["c2"]
        assert T.score_judge(KEY, {"t1": False, "t2": False, "c1": True, "c2": True})["qualifies"]


    def test_score_judge_ignores_items_the_judge_did_not_grade(self):
        s = T.score_judge(KEY, {"t1": False, "c1": True})
        assert (s["traps"], s["controls"]) == (1, 1)


    def test_qualify_bar_is_inclusive(self):
        assert T.qualifies(0.90, 0.10) and not T.qualifies(0.89, 0.0) and not T.qualifies(1.0, 0.11)


    def test_majority_and_tiebreak(self):
        assert T.majority([True, True, False]) and not T.majority([True, False, False])
        assert T.majority([True, False], tiebreak=True) and not T.majority([True, False], tiebreak=False)
        assert not T.majority([True, False])  # tie with no tiebreaker fails closed


    def test_jev_questions_and_decision(self):
        q = J.questions(["A", "B"])
        assert list(q) == ["r1", "r2", "no_invented"] and all(v["type"] == "noul" for v in q.values())
        assert "TASK:\nm" in J.state("m", ["A"], "o") and J.state("m", ["A"], "o").endswith("OUTPUT:\no")
        ok, failed = J.decide({"r1": {"noul": 0.9}, "r2": {"noul": 0.5}, "no_invented": {"noul": 0.7}}, expected=list(q))
        assert ok and failed == []
        ok, failed = J.decide({"r1": {"noul": 0.49}, "no_invented": {"noul": 0.9}}, expected=list(q))
        assert not ok and failed == ["r1", "r2"]
        assert J.decide({}) == (False, ["no answers"])
        assert J.prob({"score": "x"}) == 0.0 and J.prob(0.3) == 0.3



class CombineAndControlsTests(unittest.TestCase):
    def test_combine_uses_tiebreak_only_on_splits_and_only_when_qualified(self):
        v = {"a": True, "b": True, "c": False}
        self.assertFalse(T.combine(v, ["a", "b", "c"], False, True))   # split -> tiebreaker decides
        self.assertTrue(T.combine(v, ["a", "b", "c"], False, False))   # tiebreaker not qualified -> majority
        self.assertTrue(T.combine({"a": True, "b": True, "c": True}, ["a", "b", "c"], False, True))  # unanimous -> no tiebreak
        self.assertFalse(T.combine({"a": True, "b": False}, ["a", "b"], None, True))  # tie, no tiebreak answer -> fail closed
        self.assertTrue(T.combine({"a": True, "b": None, "c": True}, ["a", "b", "c"], False, True))  # error vote ignored
        self.assertIsNone(T.combine({"a": None}, ["a"], True, True))
        self.assertTrue(T.combine(v, ["a", "b"], False, True))  # dropped judge c is not counted

    def test_listings_control_verifier(self):
        from aqh import controls as C
        src = {r["id"]: r for r in json.loads((C.REPO / C.SPEC["listings-wedding-denver"]["src"]).read_text())}
        good = [dict({f: src[i].get(f) for f in C.SPEC["listings-wedding-denver"]["fields"]}, check_before_publish="Confirm the venue still hosts weddings on its own site.")
                for i in C.expected_ids("listings-wedding-denver")]
        self.assertEqual(C.verify("listings-wedding-denver", json.dumps(good)), (True, []))
        bad = [dict(o) for o in good]; bad[0]["price"] = "$1"
        self.assertIn("extra fields ['price']", C.verify("listings-wedding-denver", json.dumps(bad))[1])
        bad = [dict(o) for o in good]; bad[1]["name"] = "Changed"
        self.assertFalse(C.verify("listings-wedding-denver", json.dumps(bad))[0])
        self.assertEqual(C.verify("listings-wedding-denver", "Here you go: []"), (False, ["not pure JSON"]))
        self.assertIn("count 3 != 10", C.verify("listings-wedding-denver", json.dumps(good[:3]))[1])
        self.assertEqual(len(C.expected_ids("listings-denver")), 10)
        self.assertEqual(len(set(C.expected_ids("listings-wedding-denver"))), 10)


if __name__ == "__main__":
    unittest.main()
