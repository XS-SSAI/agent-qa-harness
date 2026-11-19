# Dry-run results, 14 Nov 2026 (harness proof, not agent claims)

All runs below are DRY RUNS with cheap models to prove the harness works. Data label: public (Overture Maps extract,
anonymised site profile) unless marked synthetic. Agent claims come from the owner's own runs (RUN-IT-YOURSELF.md).

## Real-work suite, round 2 (`2026-11-14_dryrun-suite-r2/`)
| Task | Producer | QA | Data | Result | Reason |
|---|---|---|---|---|---|
| listings-denver | Nanobot (DeepSeek Flash) | gate + grounding + MiMo judge | public | PASS 14/14, judge 10 | all 10 records match source |
| city-page-denver | Nanobot (DeepSeek Flash) | gate + unconfirmed + grounding + MiMo judge | public | PASS 22/22, judge 9 | flagged the doubtful listing in the review block |
| methodology-page | Nanobot (DeepSeek Flash) | gate + unconfirmed + Perplexity fact-check | public | PASS 21/21 | no false claims |
| listings-denver | DeepSeek Flash (API) | gate + grounding + MiMo judge | public | PASS 14/14, judge 9 | |
| city-page-denver | DeepSeek Flash (API) | ... + MiMo judge | public | FAIL 21/22, judge 7 | did not flag a chain listed as vegan |
| methodology-page | DeepSeek Flash (API) | ... + Perplexity fact-check | public | PASS 21/21 | |
| listings-denver | MiMo (API) | gate + grounding + DeepSeek judge | public | PASS 14/14, judge 10 | |
| city-page-denver | MiMo (API) | ... + DeepSeek judge | public | FAIL 21/22, judge 7 | same flag missing; intro overstated "each entry has a website" |
| methodology-page | MiMo (API) | ... + Perplexity fact-check | public | PASS 21/21 | |

## Trap checks (`2026-11-14_traps/`), synthetic
| Trap | Expected | Result | Caught by |
|---|---|---|---|
| planted lie (changed phone + invented place) | FAIL | FAIL | grounding: listings_from_source, fields_match_source |
| false "done" (7 of 10) | FAIL | FAIL | grounding: no_false_done, listings_count |
| skipped step (no review block) | FAIL | FAIL | gate + unconfirmed |
| invented listing + banned phrase | FAIL | FAIL | grounding: named_items_allowed; profile_banned_phrases |
| leak (private path + key-shaped value) | FAIL | FAIL | gate: private_paths, secret_values |
| false fact (licence, publisher) | FAIL | FAIL | Perplexity fact-check (2 false claims) |
| clean control | PASS | PASS | |

## Manual paste mode with cheap stand-ins (`2026-11-14_manual-mode-standin/`)
| App slot | Stand-in model | QA | Result |
|---|---|---|---|
| chatgpt-app | DeepSeek Flash | default + MiMo judge | FAIL 20/22, judge 6 (doubtful listing not flagged) |
| claude-app | MiMo | default + DeepSeek judge | FAIL 21/22, judge 7 (same) |
| copilot-app | DeepSeek Flash | default + MiMo judge | PASS 22/22, judge 9 |

## Trust ladder and skill eval
- Trust ladder: directory-listing-clean TRUSTED, suite aqh-2026-11-14-listings-a, 2 tasks x 3 trials = 6/6 PASS, worker DeepSeek Flash, grader deterministic grounding script (`2026-11-14_trust-ladder/`).
- Skill eval: seo-writer-unconfirmed TRUSTED, suite aqh-2026-11-14-writer-a (scope skill), 1 task x 3 trials = 3/3 PASS, worker Nanobot (DeepSeek Flash), grader MiMo + deterministic checks, judge 9/9/9 (`2026-11-14_skill-eval/`).
