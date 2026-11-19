# Scorecard

Run folder: 2026-11-14_dryrun-suite-r2. Mode: dry-run.

| Agent | city-page-denver | listings-denver | methodology-page | Passed |
|---|---|---|---|---|
| deepseek-flash | FAIL (21/22, judge 7.0) | PASS (14/14, judge 9.0) | PASS (21/21) | 2/3 |
| mimo | FAIL (21/22, judge 7.0) | PASS (14/14, judge 10.0) | PASS (21/21) | 2/3 |
| nanobot | PASS (22/22, judge 9.0) | PASS (14/14, judge 10.0) | PASS (21/21) | 3/3 |

## Why each FAIL failed

- **deepseek-flash / city-page-denver**: [judge:auto] judge_pass: Flags any listing whose vegan status looks doubtful (for example a chain not known as vegan): Sweetgreen, a chain not known as vegan, is listed as vegan_restaurant but never flagged for verification.
- **mimo / city-page-denver**: [judge:auto] judge_pass: Flags doubtful vegan status (e.g., non-vegan chain): Sweetgreen is not singled out as a chain whose vegan status needs checking.; Intro accuracy: Says each entry gives a website, but Mora Pizza has no website supplied.
