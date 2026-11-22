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
| ids-only | records that carry only an id, every other field left out | grounding: listings_fields_complete |
| nulled-fields | real phone numbers and websites set to null | grounding: listings_fields_complete |
| wrong-selection | 10 real, open, in-category records, but the lowest-ranked ones under the task's rule | grounding: listings_selection_rule |
| partial-list | a city page with 3 of the 10 verified listings | grounding: named_items_complete |
| invented-facts | a phone number that is not in the data, plus opening hours, a rating and a price | grounding: values_grounded_phone; gate: invented_opening_hours, invented_rating, invented_price |
| unlisted-place | a place added as a bold line instead of a `###` heading | grounding: named_items_no_unlisted_blocks |
