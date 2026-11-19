# Scoring v3 rescore, 15 Nov 2026 (aggregate summary)

Five CLI agents each ran a 9-task suite twice; the saved outputs were then rescored with scoring v3 (no agent reruns).
Six of the nine tasks are in this repo (vegan and wedding directories). The other three used a private service-offer
data set that is not published, so the raw outputs are not included here; only these totals are.

90 rows (5 agents x 9 tasks x 2 runs), 0 ERROR rows. Calibration passed 18 of 18 for all three judges before rescoring.

## PASS / scored, per agent

| Agent | Run 1 | Run 2 | Same verdict in both runs |
|---|---|---|---|
| Cursor CLI | 8/9 | 7/9 | 8/9 |
| Claude Code | 7/9 | 6/9 | 6/9 |
| Codex CLI | 6/9 | 6/9 | 7/9 |
| GitHub Copilot CLI | 4/9 | 7/9 | 4/9 |
| Grok Build CLI | 3/9 | 8/9 | 4/9 |

Run-to-run consistency (same agent and task, run 1 vs run 2): 29/45 = 64%.

## Judge agreement (same pass/fail verdict, both runs)

| Pair | Agreement |
|---|---|
| MiMo vs DeepSeek Flash | 67% (60/90) |
| MiMo vs Gemini 2.5 Flash | 71% (64/90) |
| DeepSeek Flash vs Gemini 2.5 Flash | 64% (58/90) |
| Majority of 3 vs MiMo | 87% (78/90) |
| Majority of 3 vs DeepSeek Flash | 80% (72/90) |
| Majority of 3 vs Gemini 2.5 Flash | 84% (76/90) |

All three judges agreed on 46 of 90 rows (51%). Identical outputs judged twice (15 rows) got the same final verdict 14 times.

## What this means
- No single pair of judges reached the 80% agreement bar, so the judges are not yet validated. The majority verdict is
  steadier than any one judge, but agreement between judges is not proof they are right.
- The large swings for Copilot and Grok come mostly from the agents writing different outputs in each run, not from
  the judges.
- Next step: a set of human-labelled reference verdicts to measure each judge against.

Judge spend for the rescore: $1.29.
