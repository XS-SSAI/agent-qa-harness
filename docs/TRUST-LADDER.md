# Trust ladder and skill evals (pass^3)

Do not fan a task out to many parallel, cloud or scheduled agents until one agent has proven it.

1. **One agent, watched.** Run the task once and read every step.
2. **Self-verification that drives the real thing.** Check the result by using it: parse the JSON and compare every field to the
   source, load the page, run the script on real input. "Tests pass" or "looks right" is not verification.
3. **Repeat unwatched, pass^3.** Every task in a declared suite passes all 3 independent runs with no human fix.
4. **Only then fan out**, with a spend cap per run and per day. Never auto-publish or auto-send.

## The gate (`aqh trust`, stdlib, no model calls)
```
aqh trust suite --eval-id E --family F --tasks a,b --scope task|skill --worker MODEL --grader MODEL
aqh trust trial --eval-id E --task a --trial 1 --result PASS --evidence "what really happened" --self-verified
aqh trust check F        # exit 0 trusted, 3 blocked
aqh trust skillcheck S   # skills: only a scope=skill pass^3 suite admits them
```
Rules it enforces: full tasks x 3 product or nothing; no sliding window (one FAIL blocks; rerun under a NEW eval id);
the latest suite is the only one that counts; eval ids are global; placeholder evidence ("ok", "tests pass") is rejected;
identical evidence across trials is rejected; duplicate run ids, out-of-order rows and malformed lines fail closed;
the grader must be a different model family from the worker (`aqh/families.json`; unknown names fail closed).
`tools/trust_run.py` runs a whole suite end to end and records each trial with evidence from the QA checks.

## Skill evals
Write a 5-10 item rubric and 2-3 realistic tasks (one tricky). Run each 3 times with a fresh agent that is not told it is
being tested. Grade with a different model family; deterministic items are checked by script. Record as a `--scope skill` suite.

## Repeated corrections become hard checks
If the same correction is given twice, turn it into an automatic check (a rulebook rule, a grounding check or a test),
not just a note. Log what mistake it stops and where it runs.
