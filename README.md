# agent-qa-harness

An open-source test harness for builders: plug in your own AI agent, run it on real tasks, and see whether it actually
did the work and can prove it. Each agent gets the same real tasks and the same limits. The output is scored by code
checks against the source data (receipts), by planted faults the checks must catch (traps), and by model judges from a
different model family than the agent (judges). An agent counts as reliable only after it passes every task 3 times
in a row (pass^3), and even then only for the tasks it was tested on.

The code checks are built to catch invented listings, edited fields, skipped steps, false "done" claims and leaked
secrets or private paths; each has a planted-fault test in `traps/`. The judges add a second opinion on quality and invented facts (see Limits).

Python 3.11+, standard library only, no dependencies. Apache-2.0.

## Quick start (no keys, no cost, about 2 minutes)

```bash
git clone https://github.com/XS-SSAI/agent-qa-harness.git
cd agent-qa-harness
python3 -m unittest discover -s tests          # expect "Ran 101 tests" and "OK"

# Score a clean saved output: should PASS
python3 -m aqh score --task tasks/listings-denver.json --file traps/control__listings-denver.json --qa default --out results/quickstart-clean

# Score a copy with one phone number changed and one invented restaurant: should FAIL and say why
python3 -m aqh score --task tasks/listings-denver.json --file traps/planted-lie__listings-denver.json --qa default --out results/quickstart-trap
```

On Windows, use `py` instead of `python3` in every command. `--qa default` runs only the code checks, so nothing
leaves your machine. Each command prints PASS or FAIL with the failed checks, and writes `scorecard.md` into its `--out` folder (the
harness creates it). If you score into the same folder more than once, the scorecard shows only the latest result for each agent and task.

## Run a real agent

```bash
python3 -m aqh agents                                            # what can plug in
python3 -m aqh suite --agents claude-code --out results/my-run   # the vegan suite (2 tasks in a normal run)
python3 -m aqh suite --agents codex --out results/my-run         # same folder = one shared scorecard
```

Each CLI agent uses its own login or subscription. A normal run uses one judge, so it needs one API key for a low-cost
model, set as an environment variable: `OPENROUTER_API_KEY` (MiMo), or `DEEPSEEK_API_KEY` when the agent is itself a
MiMo model. `+judge2` and `+judge3` add `DEEPSEEK_API_KEY` and `GEMINI_API_KEY`; `+factcheck` needs
`PERPLEXITY_API_KEY` plus `DEEPSEEK_API_KEY` (to extract the claims). The vegan suite's third task (`methodology-page`) is held out and only runs with
`--include-heldout`. A run costs a few cents in judge API calls. For a step-by-step guide, including chat apps you copy and paste into, see
[RUN-IT-YOURSELF.md](RUN-IT-YOURSELF.md).

## Plug in your own agent

Three ways, from least to most work:

1. **Chat app or anything you can paste into.** `python3 -m aqh manual export --task T --out prompt.txt`, paste the
   prompt, save the reply, then
   `python3 -m aqh manual score --task T --agent my-app --reply reply.md --qa default+judge --out results/my-run`.
2. **Any OpenAI-compatible API.** Set `AQH_BASE_URL`, `AQH_MODEL` and `AQH_KEY_ENV` (the *name* of the env var that holds
   your key), then run, for example,
   `python3 -m aqh run --agent openai-compat --task tasks/listings-denver.json --qa default+judge --out results/my-run`
   (or `--agents openai-compat` with `aqh suite`).
3. **A CLI agent.** Add one small class to `aqh/adapters/cli_agents.py` and one line to the registry in
   `aqh/adapters/__init__.py`:

```python
class MyAgent(CLIAgent):
    """My agent: `myagent -p` non-interactive."""
    name, binary = "my-agent", "myagent"

    def argv(self, prompt, wd):
        return [self.binary, "-p", prompt]
```

The harness runs it in a fresh temp folder, kills it at the time limit, and scores stdout. If stdout is only narration,
it scores the file the agent saved (`DELIVERABLE.md` first). Never add permission-bypass flags; the harness does not.

The two contracts, if you want to go further:

```python
class Agent:                 # aqh/core.py
    name: str
    def run(self, task: Task) -> Output: ...                    # Output(text, artifacts, meta)

class QALayer:
    name: str
    def score(self, output: Output, task: Task) -> Verdict: ...  # Verdict(passed, checks[], reasons)
```

To test your own work instead of the sample tasks, copy a file in `tasks/`, point it at your own data, site profile
(`profiles/`) and rules (`rulebooks/example.toml`).

## What the scores mean

A scorecard cell reads like `PASS (22/22, judge 9.0)`: verdict, checks passed out of checks run, and the judge score.

- **PASS**: every code check passed and the judges passed it.
- **FAIL**: at least one check failed. A failed code check (gate, grounding, review block) fails the row whatever the
  judges say. Timeouts are FAIL. Under the table, every FAIL names the check and the reason.
- **ERROR**: the row says nothing about the agent (quota, auth, missing key, or a judge that did not run after retries).
  ERROR rows are left out of pass rates and listed under "Rerun needed".
- **Judge score**: 0 to 10. A judge passes a row only if the score is 7 or more **and** it found no invented facts. With
  three judges, the final judge verdict is the majority.
- **Trust ladder**: `TRUSTED` means every task in the suite passed all 3 runs. One failure means `BLOCKED`; rerun under a
  new eval id. See [docs/TRUST-LADDER.md](docs/TRUST-LADDER.md).

## QA layers (`--qa`)

- `default` = **gate** (rulebook-driven: required lines, banned phrases, private paths, secret-shaped values, hidden
  unicode, repeated topics) + **unconfirmed** (site-profile-first writing and a required "Unconfirmed facts and
  first-hand input" review block on article tasks) + **grounding** (every listing and field must match the source data;
  named items must be in the verified list; a "done" claim must match what was delivered).
- `+judge`: a model judge from a different family than the agent. `+judge2`, `+judge3`: more judges, each from another
  family. `+factcheck`: Perplexity checks each factual claim on the web.

`traps/` holds synthetic outputs, each with one kind of planted fault (invented listing, changed field, false "done", skipped
review block, leaked path and key, false fact). Each must FAIL; a PASS means the harness missed it. The false-fact trap
needs `+factcheck`. The `control__*` files are clean and should PASS.

## Tasks

Two niches, three task types each, on public Overture Maps data (attribution in `data/overture/ATTRIBUTION.md`):

| Suite | Tasks |
|---|---|
| `suites/real-work-v1.json` | vegan listings, city page and methodology page (Denver) |
| `suites/wedding-v1.json` | wedding-venue listings, city page and methodology page (Denver) |
| `suites/real-work-all.json` | all six |

Two tasks are **held out** (`methodology-page`, `city-page-wedding-denver`): their checks are frozen and normal runs skip
them. Add `--include-heldout` only for a final scoring run; it calibrates the judges first (`calibration/`) and stops if
a judge passes a known-bad answer or fails a known-good one.

Every results folder gets `run-config.json` (the locked limits: 900 s, $5 spend cap, 30 turns, no permission bypass,
the same for every agent) and `REVIEW.md` (short samples of each output to read next to the scorecard).

## Results so far

- `results/SUMMARY.md`: dry runs that prove the harness works (traps caught, trust ladder, manual mode).
- `results/2026-11-15_scoring-v3-rescore-SUMMARY.md`: five CLI agents, two runs each of a 9-task suite (the six tasks
  above plus three on a private data set that is not published). Scores ranged from 3/9 to 8/9 per run, and the same
  agent got the same verdict on the same task in both runs 64% of the time.

## Limits

- The judges are not validated yet. The best pair of judges agreed on 71% of rows, below the 80% bar, and there is no
  human-labelled reference set yet. Treat judge scores as a second opinion; the code checks are the hard evidence.
- Agents give different outputs on each run, so one run says little. Use two or more runs, or the pass^3 ladder.
- The sample tasks are content and data-cleaning work on US directory data. Coding, browsing and multi-step tool use
  are not covered yet.
- CLI adapters call each vendor's non-interactive flags, which change often. If an agent fails to start, check its
  `argv` in `aqh/adapters/cli_agents.py`.
- The step-by-step guide targets Windows PowerShell first; the same commands work on Linux and macOS.

## Safety defaults

No permission-bypass flags on any agent (Cursor and Grok run with `--trust`, which only trusts the temporary workspace
for headless use). Keys are read from env vars only; the harness does not write or print them, and it hides key values in
error messages. A spend ledger with a hard cap (`AQH_CAP_USD`, default $5) stops the run. Only send public data to cheap
or free models; they may log it.

## Commands

```
aqh agents
aqh run --agent nanobot --task tasks/city-page-denver.json --qa default+judge
aqh suite --agents claude-code,codex --suite suites/real-work-v1.json --out results/my-run
aqh manual export|score ...
aqh score --task tasks/T.json --file saved-output.md
aqh gate --kind article draft.md --rulebook rulebooks/example.toml
aqh calibrate --qa default+judge+judge2
aqh trust suite|trial|check|show|skillcheck ...
aqh agree --run results/my-run
aqh review --run results/my-run
aqh spend
```

Without installing: `python3 -m aqh ...` (Windows: `py -m aqh ...`). Install: `pip install -e .`

## Layout

- `aqh/`: contracts, CLI, runner and scorecard, adapters, QA layers, trust ladder, trap set
- `tasks/`, `suites/`: task specs and fixed suites; `traps/`: synthetic faults that must fail; `calibration/`:
  known-good and known-bad answers for the judges
- `data/`: public input data; `profiles/`: site profiles; `rulebooks/`: gate rules (start from `example.toml`)
- `results/`: summaries and dry-run scorecards; `docs/`: trust ladder and chat-app notes; `research/`: how the agent
  list was ranked; `tests/`: unit tests
- [CHANGELOG.md](CHANGELOG.md): what changed in each scoring version

## License

Apache-2.0. See [LICENSE](LICENSE).
