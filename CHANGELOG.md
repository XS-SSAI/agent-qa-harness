# Changelog

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
