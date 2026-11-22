# Changelog

## Unreleased: scoring v5 (stricter code checks)

Six bad outputs passed the scoring v3 code checks with full marks. Each is now a trap in `traps/` and fails.
A v3 PASS is not a v5 PASS: `SCORING_VERSION` is `aqh-scoring-v5`, so a saved calibration is not reused across the change.

1. **Fields must be complete** (`listings_fields_complete`). A value the source has cannot be left out or set to
   null. Before, a record with only an id passed, and so did a list with every phone number nulled.
2. **Open means open** (`listings_open_only`). A source record with no `operating_status` is unknown, not open.
3. **Selection rule** (`expect.selection`: `listings_required_present`, `listings_no_duplicates`,
   `listings_selection_rule`). The task says which records to prefer; the check now holds the output to it. A skipped
   record that ranks above a kept one fails. Tied records are interchangeable, so the four vegetarian places tied for
   the last Denver slot are all correct. Declared in the four listings tasks.
4. **City pages** (`expect.named_items_strict`, `expect.values_grounded`). Every verified listing needs its `###`
   heading (`named_items_complete`); a place added under a deeper heading or a bold line is checked like a heading
   (`named_items_no_unlisted_blocks`); every phone number and website in the body must be in the task material
   (`values_grounded_phone`, `values_grounded_url`). Both rulebooks ban clock times, ratings and prices on city pages.
5. **Judge input is never cut.** The judge was sent the first 30,000 characters of the task material and of the
   output. `listings-houston` is 45,672 characters and `listings-las-vegas` 39,932, so a judge graded against a partial
   source. The judge now gets all of it; past `JUDGE_MAX_INPUT_CHARS` (200,000) the row is ERROR, not a grade.
6. **Tested agents do not get the harness's keys.** A CLI agent inherited the whole environment, judge keys included.
   Each adapter now keeps only its own provider key (`env_keep`); `AQH_AGENT_ENV_ALLOW=NAME,NAME` allows more for a run.
7. **`control__listings-denver.json` replaced.** The old control was the reference top 10, which drops places under
   0.7 confidence. The listings task has no such threshold, so that list skipped two vegan places for vegetarian
   ones and fails the selection rule. The new control follows the task as written.
8. **Timeout test.** A killed child that has not been reaped yet (a zombie) no longer counts as still running; the
   test failed in containers whose init does not reap orphans.

Effect on saved outputs (code checks only, 28 files in `results/` and `calibration/`): one real output changes,
`deepseek-flash__listings-denver` in the 14 Nov dry run, from PASS to FAIL on the selection rule. No saved city page
or methodology page changes verdict.

## 0.3.x: scoring v4 (known-answer trap set)
- `aqh/trapset.py`: plant functions that add one known fault to a known-good output (changed field, invented record, dropped step, false "done"), so each judge can be scored on catches and false alarms.
- `aqh/controls.py`: strict script check that picks known-good listings controls from the source data.
- `aqh/jevjudge.py`: question builder and decision rule for a yes/no classifier judge (one question per rubric item plus a no-invented-facts question). It is used as a tiebreaker only.

## 0.3.0: scoring v3
- Judge pass = score >= 7 **and** no invented facts, enforced in code. The model's own pass flag is kept for the record only.
- Judge 3 (Gemini 2.5 Flash, a third model family) runs on every task. The final judge verdict is the majority of 3.
- Deterministic checks (gate, grounding, unconfirmed facts) still fail a row on their own.

## 0.2.0: scoring v2 (2026-11-15)

What changed, and why (from the 2026-11-15 final run):

1. **Three verdicts: PASS, FAIL, ERROR.** ERROR means the row says nothing about the agent's work: an agent-side
   credit, quota, auth or missing-key failure, or a judge that did not run after retries. ERROR rows are left out of
   pass rates (Passed = PASS / (PASS + FAIL)) and out of judge agreement, are listed under "Rerun needed" in the
   scorecard, and carry `"rerun": true` in results.jsonl. A failed deterministic check (gate, unconfirmed-facts block,
   grounding) still makes the row FAIL, because no judge result can change it. Timeouts stay FAIL.
2. **Judge retries.** A judge that returns no text, bad JSON or an HTTP/network error is retried up to 2 more times.
   Missing keys and the spend cap are not retried. judge2 (DeepSeek Flash) gets 16,000 output tokens instead of 6,000
   (it ran out of room: `finish_reason=length`).
3. **Deliverable file fallback.** If an agent's stdout is empty or only narration ("I'll read TASK.md..."), the harness
   scores the deliverable file the agent saved in its workdir (DELIVERABLE.md first, then the largest .md/.json/.html/.txt
   written during the run) and marks the row `deliverable_source: file:NAME`. This applies to every CLI adapter.
   The Grok Build prompt now asks it to write DELIVERABLE.md and to reply with the full deliverable.
4. **Judge calibration.** `calibration/cases.json` holds one known-good and one known-bad answer per task type
   (listings, city page, methodology page; no held-out tasks). `aqh calibrate --qa default+judge+judge2` checks that
   every judge passes the good answer and fails the bad one. A suite run with `--include-heldout` (a final run) calibrates
   first, saves `calibration.json` in the results folder, and aborts with exit code 3 before any agent runs if a judge
   misgrades or cannot run. A passing calibration in the same folder is reused.
5. **OpenCode cost.** OpenCode now runs with `--format json`; the deliverable is the text of its last step, and its cost
   is booked in the spend ledger (step-finish `cost`, else the OpenRouter key-usage delta for `OPENROUTER_API_KEY`).

The locked limits are unchanged (900 s, $5 cap, 30 turns, no permission bypass, judge pass mark 7.0). locked.json records
`scoring_version`, `judge_retries` and `judge2_max_tokens`. Rows saved by scoring v1 have no `verdict` field and are read
as PASS/FAIL from `pass`.
