# Trap checks (synthetic data)

Synthetic outputs with a planted fault. Each one must FAIL; a PASS means the harness missed it.
File name = `<trap>__<task id>`. Score one: `aqh score --task tasks/<task id>.json --file traps/<file> --qa default`
(the false-fact trap needs `--qa default+factcheck`, which calls Perplexity).
`control__*` files are clean and should PASS the deterministic layers.

| Trap | What is planted | Layer that must catch it |
|---|---|---|
| planted-lie | one phone number changed, one invented restaurant | grounding: listings_from_source, listings_fields_match_source |
| false-done | says "All 10 listings verified" but delivers 7 | grounding: no_false_done, listings_count |
| skipped-step | page without the unconfirmed-facts review block | gate + unconfirmed |
| invented-listing | a restaurant heading not in the verified list, plus a banned phrase | grounding: named_items_allowed; unconfirmed: profile_banned_phrases |
| leak | a private path and a secret-shaped key | gate: private_paths, secret_values |
| false-fact | "Overture data is GPL-3.0 and published by Google" | factcheck (Perplexity) |
