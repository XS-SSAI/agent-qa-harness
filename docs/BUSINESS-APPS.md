# Business chat apps: Microsoft Copilot, ChatGPT, Claude

| App | How it plugs in | Command | Status (14 Nov 2026) |
|---|---|---|---|
| Microsoft Copilot (copilot.microsoft.com, Microsoft 365 Copilot Chat) | Manual paste mode. There is no public API to send a prompt to the Copilot chat app and read the reply, so the harness exports the task, you paste it, and you paste the reply back for scoring. | `aqh manual export ...` then `aqh manual score --agent copilot-app ...` | Manual pipeline verified end to end with a cheap-model stand-in. Not yet run in the real Copilot app (message length limits there are untested; the listings task prompt is about 15k characters). |
| ChatGPT | (a) Manual paste mode for the ChatGPT app. (b) API adapter `chatgpt-api` (OpenAI Chat Completions, env OPENAI_API_KEY, model via AQH_OPENAI_MODEL). (c) Codex CLI adapter `codex` for the agent product. | `aqh manual score --agent chatgpt-app ...` / `aqh run --agent chatgpt-api ...` / `--agent codex` | Manual pipeline verified with a stand-in. API and Codex adapters written, not executed (paid models not run in dry runs). |
| Claude | (a) Manual paste mode for claude.ai. (b) API adapter `claude-api` (Anthropic Messages API, env ANTHROPIC_API_KEY, model via AQH_ANTHROPIC_MODEL). (c) Claude Code CLI adapter `claude-code`. | `aqh manual score --agent claude-app ...` / `aqh run --agent claude-api ...` / `--agent claude-code` | Manual pipeline verified with a stand-in. API and Claude Code adapters written, not executed. |

Manual mode rules: start a new chat, paste the exported file content as one message, add nothing, copy the full reply into a
text file. The harness refuses a reply file that is really the exported prompt. Scores from manual mode are labelled
`manual-paste` in the scorecard so they are not confused with automated runs.
