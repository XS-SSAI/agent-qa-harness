Here is the draft (saved to drafts/how-we-verify-listings.md):

How we verify listings
By Editorial Team

Every listing in this directory starts as a candidate, not a recommendation. This page explains where candidates come from, what we check before a listing is published, and how featured placements are disclosed.

Where candidates come from

Candidate listings come from the Overture Maps Foundation places data, release 2026-10-21.0 (overturemaps.org). We filter that release to rows that look like vegan and vegan-friendly restaurants, cafes, bakeries and stores in the US. Each row is a starting point for editorial checking, not a verified listing.

The licence

Overture data is published under open licences. Most of the rows we use are CDLA-Permissive-2.0. Rows that Overture sourced from Foursquare are Apache-2.0. Every row keeps its sources field, which records the dataset and the licence that applies to it, so the licence behind any listing can be traced back to the row it came from.

What we check on the business's own site

A row in a map dataset does not tell us whether a place is vegan today. Before a listing is published, a member of the editorial team opens the business's own website and checks:

- Vegan status. Whether the business describes itself as fully vegan, or as vegan-friendly with vegan options. We record which one, in the business's own terms.
- Menu. Whether the menu on the site supports that status, and which items are vegan.
- Hours. Whether the hours on the site match the hours we intend to show.

We do not publish candidate data as fact on its own. If the business's own site does not confirm something, we leave it out of the listing rather than filling the gap.

Each published listing shows the date it was last checked. When we re-check a site, that date changes.

Featured placements

Featured placements are not live yet. When they are, they will be paid placements, and they will be labeled as featured wherever they appear. The label is a disclosure, not an endorsement and not a verification: every listing, featured or not, goes through the checks above.

If a listing is wrong or out of date, we re-check the business's site and correct the entry and its check date.

Label: not ready (draft awaiting editor checks)
Human-reader check: pending

## Unconfirmed facts and first-hand input

### Claims I could not source-check
- "they will be paid placements" — the profile says monetization is "clearly labeled featured listings" and is planned, not live, but does not state that featured listings are sold for money or what the price model is. Needs owner confirmation of the commercial model and the exact public wording ("paid", "sponsored", or "featured partner").
- "labeled as featured wherever they appear" — the profile requires disclosure but does not fix the label text or say whether the disclosure sits on the listing card, the detail page, or both. Needs the approved label copy and placement.
- "If a listing is wrong or out of date, we re-check the business's site and correct the entry and its check date" — a process claim; the profile has no documented correction/reporting workflow or response commitment. Needs confirmation that this is how corrections are actually handled, and whether a contact channel may be named.
- "We filter that release to rows that look like vegan and vegan-friendly restaurants, cafes, bakeries and stores in the US" — the US scope and the vegan_*.json filtering are documented, but the actual filter criteria (tags used, whether "vegan-friendly" rows are included only with menu evidence) are not in the supplied files. Needs the filter definition from tools/make_reference.py or the query used.
- Release "2026-10-21.0" is taken verbatim from ATTRIBUTION.md; I could not confirm it is the release currently loaded in production. Needs confirmation that this is the live release, since the date will date the page.

### First-hand input needed
1. Is the featured-placement label exactly "Featured", and does the paid disclosure appear on the listing itself or only on this page?
2. Is there a live corrections route (email address or form) that this page should point owners to, or should the closing line stay channel-free for now?
3. Do you want the page to state the specific Overture release number publicly, or keep it to "current Overture Maps places data" so the page does not go stale at each release?