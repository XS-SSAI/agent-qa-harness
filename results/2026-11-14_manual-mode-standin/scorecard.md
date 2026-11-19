# Scorecard

Run folder: 2026-11-14_manual-mode-standin. Mode: dry-run/manual-paste.

| Agent | city-page-denver | Passed |
|---|---|---|
| chatgpt-app | FAIL (20/22, judge 6.0) | 0/1 |
| claude-app | FAIL (21/22, judge 7.0) | 0/1 |
| copilot-app | PASS (22/22, judge 9.0) | 1/1 |

## Why each FAIL failed

- **chatgpt-app / city-page-denver**: [judge:mimo] judge_pass: Flags any listing whose vegan status looks doubtful: No flag for Sweetgreen or Veggie Grill chains not known as vegan; only vegetarian-category question raised.; [judge:mimo] judge_score: score 6.0 < 7.0
- **claude-app / city-page-denver**: [judge:deepseek-flash] judge_pass: Flags any listing whose vegan status looks doubtful: Sweetgreen is labeled vegan but not flagged despite being a chain not known as vegan.
