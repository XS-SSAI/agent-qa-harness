# Most-used AI agents, ranked (14 Nov 2026)

Method: Perplexity sonar web research (survey figures, raw answer in `perplexity_ranking_raw.json`), then the hard numbers we
could re-pull ourselves the same day: npm weekly downloads (api.npmjs.org, 7-13 Nov 2026), PyPI last-month downloads
(pypistats.org), GitHub stars (api.github.com). Survey figures are as reported by the sources linked; the npm/PyPI/GitHub
numbers were verified directly (`verified_metrics.txt`).

| # | Agent | Type | Evidence | Why it ranks here |
|---|---|---|---|---|
| 1 | Claude Code | CLI coding agent | Stack Overflow 2026: 65.5% of agent users; npm 17.6M/week; 156k stars | Highest survey share and top-2 npm downloads |
| 2 | GitHub Copilot (agent + Copilot CLI) | IDE/cloud agent + CLI | SO 2026: 58.7%; `@github/copilot` CLI npm 1.7M/week | Second in the survey; bundled with GitHub/VS Code |
| 3 | OpenAI Codex CLI | CLI coding agent | SO 2026: 29.5%; npm 26.4M/week (highest); 135k stars | Most downloaded agent CLI |
| 4 | Cursor | IDE agent (+ `cursor-agent` CLI) | SO 2026: 25.5%; JetBrains 2026 workplace adoption 12% | Most-used agent IDE |
| 5 | OpenCode | Open-source CLI agent | SO 2026: 13.6%; npm 3.8M/week; 227k stars | Biggest open-source coding agent; runs any cheap model |
| 6 | Gemini CLI / Code Assist | CLI / IDE agent | SO 2026: 14.6% (Code Assist); Gemini CLI npm 447k/week; 109k stars | Large survey share, smaller CLI usage |
| 7 | OpenClaw | Open-source personal agent | npm 3.1M/week; 394k stars | Most-starred personal agent |
| 8 | Hermes Agent (Nous Research) | Open-source personal agent | PyPI 317k/month; 263k stars; SO 2026 10.2% (as reported) | Fast-growing; already set up in our stack |
| 9 | LangGraph | Agent framework | PyPI 58.8M/month; SO 2026 18.8% (framework question) | A framework, not an agent: wrap your graph in a 10-line adapter |
| 10 | Cline | Open-source VS Code agent | 71.6k stars; 5.9M VS Code installs (reported); SO 4.5% | IDE-only, no headless mode needed for tests |
| 11 | CrewAI | Agent framework | PyPI 2.6M/month; 61k stars | Framework; same note as LangGraph |
| 12 | Aider | Open-source CLI agent | PyPI 343k/month; 50k stars; SO 2.1% | Smaller, steady |
| 13 | OpenHands | Open-source agent runtime | PyPI 265k/month; 93k stars | Heavier runtime (Docker) |
| 14 | nanobot (HKUDS) | Open-source personal agent | PyPI 95k/month; 50k stars | Small, but already in our stack and cheap to run |
| 15 | Goose | Open-source agent | 56.6k stars; ships as a binary, PyPI figure not meaningful | No reliable usage number found |

Skipped as negligible for a first release: Duet, dots and other agents with no measurable survey share or download volume.

## The five headline adapters (practical set)
Claude Code, GitHub Copilot CLI, Codex CLI, Cursor (cursor-agent), OpenCode: ranks 1-5 by measured use, all with a
non-interactive CLI mode so one command runs a task. Extras: Hermes and Nanobot (already installed in our stack),
Gemini CLI (rank 6), and raw model APIs (DeepSeek, MiMo, Perplexity, OpenAI, Anthropic) as baselines and judges.

## Sources
- https://survey.stackoverflow.co/2026/ai/data/ai-code-agent
- https://survey.stackoverflow.co/2026/ai/data
- https://blog.jetbrains.com/research/2026/08/ai-coding-agent-adoption-2026/
- https://stackness.dev/blog/stack-overflow-developer-survey-2026-tool-changes-year-over-year
- https://agentgid.com/lists/ai-coding-agents-for-vs-code/
- https://api.npmjs.org/downloads/point/last-week/<package>  (verified 14 Nov 2026)
- https://pypistats.org/api/packages/<package>/recent        (verified 14 Nov 2026)
- https://api.github.com/repos/<owner>/<repo>                 (verified 14 Nov 2026)
