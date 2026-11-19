"""Adapter registry. Add an agent = add one class and one line here."""
from __future__ import annotations

from .cli_agents import ClaudeCode, Codex, CopilotCLI, CursorAgent, GeminiCLI, GrokBuild, Hermes, OpenCode
from .llm_api import PRESETS, LLMAgent
from .manual import APP_NOTES, ReplayAgent
from .nanobot import Nanobot

# The five headline CLI agents (ranked by measured use), extra CLIs, and model-API baselines.
REGISTRY = {
    "claude-code": ClaudeCode,
    "codex": Codex,
    "copilot-cli": CopilotCLI,
    "cursor": CursorAgent,
    "opencode": OpenCode,
    "hermes": Hermes,
    "gemini-cli": GeminiCLI,
    "grok": GrokBuild,
    "nanobot": Nanobot,
}
for _p in PRESETS:
    REGISTRY[_p] = (lambda p=_p: LLMAgent(p))
# Any OpenAI-compatible endpoint: set AQH_BASE_URL, AQH_MODEL and AQH_KEY_ENV (the name of the env var holding the key).
REGISTRY["openai-compat"] = lambda: LLMAgent("openai-compat")

KIND = {
    "claude-code": "CLI", "codex": "CLI", "copilot-cli": "CLI", "cursor": "CLI", "opencode": "CLI", "hermes": "CLI",
    "gemini-cli": "CLI", "grok": "CLI", "nanobot": "CLI (python package)",
    **{p: "API" for p in PRESETS}, "openai-compat": "API (AQH_BASE_URL)",
    **{a: "manual paste" for a in APP_NOTES},
}


def get_agent(name: str, reply: str | None = None):
    if name in APP_NOTES or name == "manual" or reply:
        if not reply:
            raise SystemExit(f"{name} is a manual-paste app: use `aqh manual export` then `aqh manual score --reply FILE`")
        return ReplayAgent(reply, name)
    if name not in REGISTRY:
        raise SystemExit(f"unknown agent {name!r}. Known: {', '.join(sorted(REGISTRY))}, {', '.join(APP_NOTES)}")
    return REGISTRY[name]()
