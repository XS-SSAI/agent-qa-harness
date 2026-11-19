# Run it yourself (Windows walkthrough)

On Linux or macOS the commands are the same with `python3 -m aqh` instead of `py -m aqh`, `/` instead of `\` in paths, and `export NAME=value` (or `read -s NAME && export NAME`) to set keys.

This runs the same real-work tests on each agent, then prints a scorecard you can compare: one row per agent, one column
per task, PASS or FAIL, how many checks passed, and the judge score.

The original test suite is fixed: `suites/real-work-v1.json`, three tasks on public data (Overture Maps vegan listings for Denver). Task 3 is held out, so a normal run scores tasks 1 and 2:
1. **listings-denver**: clean and verify 10 vegan listings from the raw data. Scored by code: every field must match the source.
2. **city-page-denver**: write a city page from the 10 verified listings, following the site profile, with the review block.
3. **methodology-page**: write a "How we verify listings" page. Its facts are checked on the web by Perplexity.

A wider suite, `suites/real-work-all.json`, adds a second niche with the same three task types (6 tasks in all): wedding venues in Denver (Overture Maps data, a wedding-directory site profile). To run only the wedding niche: `suites/wedding-v1.json`.

## 1. One-time setup (about 5 minutes)

Open **PowerShell** and go to the folder:

```powershell
cd agent-qa-harness   # wherever you cloned it
py -m unittest discover -s tests
```
You should see `OK` at the end. That confirms the harness runs on this PC (no internet needed, no cost).

The scoring uses low-cost outside models (a few cents per run): one judge in a normal run, up to three judges with
`+judge2` and `+judge3`, and Perplexity for `+factcheck`. Put the keys you need in this window. Your typing is hidden,
and the key lasts only until you close this PowerShell window:

```powershell
function Set-Key($name) { $s = Read-Host "$name" -AsSecureString; [Environment]::SetEnvironmentVariable($name, [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s)), "Process") }
Set-Key OPENROUTER_API_KEY     # MiMo judge
Set-Key DEEPSEEK_API_KEY       # second judge and claim extraction
Set-Key GEMINI_API_KEY         # third judge (+judge3)
Set-Key PERPLEXITY_API_KEY     # web fact-check (+factcheck)
```

## 2. One command per agent

Use the **same** `--out` folder for every agent, so they all land in one scorecard. Each agent uses its own login or
subscription on this PC; the harness never asks it to skip permissions. Every agent gets the same locked limits
(15 minutes, $5 spend cap unless you lower `AQH_CAP_USD` for a one-off). Those limits are saved as `run-config.json`
in the results folder, and a short `REVIEW.md` sits next to the scorecard so you can read the outputs.

Two tasks are held out of ordinary runs (`methodology-page`, `city-page-wedding-denver`).
To score them as well, in a final run only, add `--include-heldout`.

| Agent | Install and sign in | Command |
|---|---|---|
| Claude Code | install Claude Code, then run `claude` once to sign in | `py -m aqh suite --agents claude-code --out results\my-run` |
| OpenAI Codex CLI | `npm install -g @openai/codex`, then `codex login` | `py -m aqh suite --agents codex --out results\my-run` |
| GitHub Copilot CLI | `npm install -g @github/copilot`, then run `copilot` once to sign in | `py -m aqh suite --agents copilot-cli --out results\my-run` |
| Cursor CLI | install from cursor.com/cli, then `cursor-agent login` | `py -m aqh suite --agents cursor --out results\my-run` |
| OpenCode | install OpenCode and set up a model provider | `py -m aqh suite --agents opencode --out results\my-run` |
| Grok Build CLI (`grok`) | official install `irm https://x.ai/cli/install.ps1 | iex`, then set `XAI_API_KEY` (this is the Grok Build CLI, not the Grok Bot app) | `py -m aqh suite --agents grok --out results\my-run` |

Optional extras: `hermes`, `nanobot` and `gemini-cli` (if installed and on PATH).
To pick a model for an agent, set it first, for example `$env:AQH_CLAUDE_MODEL = "sonnet"`, `$env:AQH_OPENCODE_MODEL = "deepseek/deepseek-chat"`, or `$env:AQH_GROK_MODEL = "grok-4.7"` (the grok adapter default).

## 3. Chat apps: Microsoft Copilot, ChatGPT, Claude (copy and paste)

For each task:

```powershell
py -m aqh manual export --task tasks\city-page-denver.json --out prompts\city-page-denver.txt
```
1. Open the file, copy everything below the line of `=` signs, and paste it into a **new chat** in the app. Add nothing.
2. Copy the app's full reply into a new text file, for example `replies\chatgpt-city-page-denver.md`.
3. Score it (use `chatgpt-app`, `claude-app` or `copilot-app`):

```powershell
py -m aqh manual score --task tasks\city-page-denver.json --agent chatgpt-app --reply replies\chatgpt-city-page-denver.md --qa default+judge --out results\my-run
```
Repeat with `tasks\listings-denver.json` (`--qa default+judge`). `tasks\methodology-page.json` (`--qa default+factcheck`) is held out: score it only in a final run.

## 4. Read the scorecard

Open `results\my-run\scorecard.md` (or `scorecard.csv` in Excel). Each cell reads like `PASS (22/22, judge 9.0)`.
Under the table, every FAIL says exactly which check failed and why. Each agent's full output is in `results\my-run\outputs\`.

## 5. Optional: prove an agent is reliable (pass^3)

```powershell
py tools\trust_run.py --eval-id my-claude-listings-1 --family listings-claude --agent claude-code --worker claude-code --tasks listings-denver,listings-las-vegas --qa default --grader rules-script --out results\trust-claude
```
It runs each task 3 times. "TRUSTED" means all 6 runs passed. One failure means "BLOCKED"; rerun with a new `--eval-id`.

## Optional: two-judge agreement

To see whether a second cheap judge (a different model family) agrees with the first, add `+judge2` and then print the summary:

```powershell
py -m aqh suite --agents grok --qa default+judge+judge2 --suite suites\real-work-v1.json --out results\agree-demo
py -m aqh agree --run results\agree-demo
```

You can also rescore a saved output with `--qa default+judge+judge2` without rerunning the agent. For Grok, the first judge is MiMo and the second is DeepSeek Flash.

## What it costs
The agents run on your own subscriptions. The judges cost about $0.01 to $0.03 per agent for the original three-task suite.
`py -m aqh spend` shows the running total; the harness stops itself at $5 (`$env:AQH_CAP_USD` to change it).
