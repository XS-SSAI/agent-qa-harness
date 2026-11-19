"""Site profile + unconfirmed-facts loop (ported from an SEO pipeline, made generic).

1. Before writing, the agent gets the site profile first (load_profile_context), with the
   instruction that unknown facts stay unknown.
2. Every draft must end with the review block:

   ## Unconfirmed facts and first-hand input
   ### Claims I could not source-check
   - ...   (or exactly: "None. Every claim in this draft was checked against the site profile or a cited source.")
   ### First-hand input needed
   1. ...  (1 to 3 specific prompts)

3. UnconfirmedQA checks the block is present, complete, placed after the body, and that the
   body does not break the profile's banned phrases.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..core import Check, Output, Task, Verdict

HEADING = re.compile(r"(?im)^#{1,3}\s*Unconfirmed facts and first-hand input\s*$")
CLAIMS_H = re.compile(r"(?im)^#{2,4}\s*Claims I could not source-check\s*$")
INPUT_H = re.compile(r"(?im)^#{2,4}\s*First-hand input needed\s*$")
NONE_LINE = "None. Every claim in this draft was checked against the site profile or a cited source."
GENERIC_Q = re.compile(r"(?i)\b(any (?:other )?thoughts|anything else|any feedback|let me know)\b")

WRITER_INSTRUCTIONS = """Before you write:
1. Read the SITE PROFILE below first and obey it. If a fact is not in the profile or in the supplied data, do not put it in the page body. Unknown stays unknown; never invent it.
2. Write the page. Leave out what you do not have instead of announcing gaps in the public copy.
3. After the page, output this review block exactly, with these headings (it is for review only, never published):

## Unconfirmed facts and first-hand input

### Claims I could not source-check
- <each claim you could not check against the profile or the supplied data, and what is still needed>
If there are none, write exactly: """ + NONE_LINE + """

### First-hand input needed
1. <a specific question for the editor; 1 to 3 questions, no generic "any thoughts?">
"""


def load_profile_context(profile_path: str | Path | None) -> str:
    if not profile_path:
        return "=== SITE PROFILE ===\nMISSING. Do not invent a profile. List the gap in the Unconfirmed facts block.\n"
    p = Path(profile_path)
    if not p.is_file():
        return "=== SITE PROFILE ===\nMISSING. Do not invent a profile. List the gap in the Unconfirmed facts block.\n"
    return "=== SITE PROFILE (obey; unknown = unknown) ===\n" + p.read_text(encoding="utf-8")[:16000]


def profile_banned(profile_text: str) -> list[str]:
    """Lines under a '## Banned phrases' heading, one '- phrase' per line."""
    m = re.search(r"(?ims)^##\s*Banned phrases\s*$(.*?)(?=^##\s|\Z)", profile_text)
    if not m:
        return []
    return [l.strip()[2:].strip().strip('"') for l in m.group(1).splitlines() if l.strip().startswith("- ")]


def check_block(text: str) -> list[Check]:
    cs = []
    h = HEADING.search(text)
    cs.append(Check("unconfirmed_block_present", bool(h), "missing '## Unconfirmed facts and first-hand input' block"))
    if not h:
        return cs
    body, block = text[: h.start()], text[h.end():]
    cs.append(Check("block_after_body", len(body.strip()) >= 200, "the page body before the block is missing or too short"))
    c, i = CLAIMS_H.search(block), INPUT_H.search(block)
    cs.append(Check("claims_section", bool(c), "missing '### Claims I could not source-check'"))
    cs.append(Check("input_section", bool(i), "missing '### First-hand input needed'"))
    if c and i and c.start() < i.start():
        claims = block[c.end(): i.start()].strip()
        ok = bool(re.search(r"(?m)^\s*[-*]\s+\S", claims)) or NONE_LINE in claims
        cs.append(Check("claims_filled", ok, "claims section is empty (list claims, or write the exact None line)"))
        qs = re.findall(r"(?m)^\s*\d+[.)]\s+(.+)$", block[i.end():])
        cs.append(Check("input_prompts_1_to_3", 1 <= len(qs) <= 3, f"needs 1-3 numbered prompts, found {len(qs)}"))
        gen = [q for q in qs if GENERIC_Q.search(q) or len(q.split()) < 5]
        cs.append(Check("input_prompts_specific", not gen, "generic or too-short prompt: " + "; ".join(g[:60] for g in gen)))
    return cs


class UnconfirmedQA:
    name = "unconfirmed"

    def score(self, output: Output, task: Task) -> Verdict:
        cs = check_block(output.text)
        prof = task.inputs.get("profile")
        if prof:
            base = Path(task.inputs.get("_base", "."))
            pp = Path(prof) if Path(prof).is_absolute() else base / prof
            if pp.is_file():
                h = HEADING.search(output.text)
                body = output.text[: h.start()] if h else output.text
                hits = [b for b in profile_banned(pp.read_text(encoding="utf-8")) if b and b.lower() in body.lower()]
                cs.append(Check("profile_banned_phrases", not hits, "body uses phrases the profile bans: " + ", ".join(hits)))
        return Verdict.from_checks(cs, layer=self.name)
