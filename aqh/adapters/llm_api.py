"""Raw model adapters over HTTP (stdlib urllib). Keys come from env vars only and are never printed.

Presets (name -> endpoint, model, key env, USD per 1M tokens in/out for the spend ledger):
  deepseek-flash, deepseek-pro        DeepSeek native API
  mimo, mimo-pro                       Xiaomi MiMo through OpenRouter
  gemini-flash                         Google Gemini 2.5 Flash (OpenAI-compatible endpoint; judge3 in scoring v3)
  sonar                                Perplexity (web-grounded)
  chatgpt-api                          OpenAI API (ChatGPT models)      - for the owner to run; not run in dry runs
  claude-api                           Anthropic Messages API (Claude)  - for the owner to run; not run in dry runs
Any other OpenAI-compatible endpoint:  openai-compat with AQH_BASE_URL, AQH_MODEL, AQH_KEY_ENV.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request

from ..core import Output, Task
from .. import spend

PRESETS = {
    "deepseek-flash": dict(url="https://api.deepseek.com/chat/completions", model="deepseek-flash", key="DEEPSEEK_API_KEY", price=(0.14, 0.28), family="deepseek"),
    "deepseek-pro": dict(url="https://api.deepseek.com/chat/completions", model="deepseek-v4-pro", key="DEEPSEEK_API_KEY", price=(1.32, 3.96), family="deepseek"),
    "mimo": dict(url="https://openrouter.ai/api/v1/chat/completions", model="xiaomi/mimo-v2.6-flash", key="OPENROUTER_API_KEY", price=(0.14, 0.28), family="mimo"),
    "mimo-pro": dict(url="https://openrouter.ai/api/v1/chat/completions", model="xiaomi/mimo-v2.6-pro", key="OPENROUTER_API_KEY", price=(0.435, 0.87), family="mimo"),
    # Scoring v3 judge3: Google family (cross-family to MiMo and DeepSeek). Gemini bills thinking tokens as output.
    "gemini-flash": dict(url="https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", model="gemini-2.5-flash", key="GEMINI_API_KEY", price=(0.30, 2.50), family="google"),  # default thinking: reasoning_effort=low misgraded calibration (2 of 18)
    "sonar": dict(url="https://api.perplexity.ai/chat/completions", model="sonar", key="PERPLEXITY_API_KEY", price=(1.0, 1.0), family="perplexity"),
    "chatgpt-api": dict(url="https://api.openai.com/v1/chat/completions", model=os.environ.get("AQH_OPENAI_MODEL", "gpt-5-mini"), key="OPENAI_API_KEY", price=None, family="openai"),
    "claude-api": dict(url="https://api.anthropic.com/v1/messages", model=os.environ.get("AQH_ANTHROPIC_MODEL", "claude-haiku-4-5"), key="ANTHROPIC_API_KEY", price=None, family="anthropic", anthropic=True),
}


def _scrub(msg: str, key: str) -> str:
    return msg.replace(key, "[hidden]") if key else msg


def chat(preset: str, system: str, user: str, max_tokens: int = 4000, temperature: float = 0.2, json_mode: bool = False, tag: str = "") -> tuple[str, dict]:
    cfg = dict(PRESETS[preset]) if preset in PRESETS else dict(
        url=os.environ["AQH_BASE_URL"].rstrip("/") + "/chat/completions", model=os.environ["AQH_MODEL"],
        key=os.environ.get("AQH_KEY_ENV", "AQH_API_KEY"), price=None, family="unknown")
    key = os.environ.get(cfg["key"], "")
    if not key:
        raise RuntimeError(f"env var {cfg['key']} is not set (needed for {preset})")
    spend.guard()
    t0 = time.time()
    if cfg.get("anthropic"):
        body = {"model": cfg["model"], "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    else:
        body = {"model": cfg["model"], "temperature": temperature, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        if json_mode and "perplexity" not in cfg["url"]:
            body["response_format"] = {"type": "json_object"}
        if "openrouter" in cfg["url"]:
            body["usage"] = {"include": True}
        body.update(cfg.get("extra") or {})
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    req = urllib.request.Request(cfg["url"], data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(_scrub(f"{preset} HTTP {e.code}: {e.read().decode(errors='replace')[:300]}", key)) from None
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(_scrub(f"{preset} error: {e}", key)) from None
    if cfg.get("anthropic"):
        text = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
        u = d.get("usage", {}); tin, tout = u.get("input_tokens", 0), u.get("output_tokens", 0)
    else:
        text = d["choices"][0]["message"].get("content") or ""
        if not text.strip():
            raise RuntimeError(f"{preset} returned no text (finish_reason={d['choices'][0].get('finish_reason')}); raise max_tokens")
        u = d.get("usage", {}); tin, tout = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
        # Gemini (and other thinking models) leave reasoning tokens out of completion_tokens but bill them as output.
        tot = u.get("total_tokens") or 0
        if tot and tin and tot - tin > tout:
            tout = tot - tin
    usd = None
    c = u.get("cost")
    if isinstance(c, (int, float)):
        usd = float(c)
    elif isinstance(c, dict) and isinstance(c.get("total_cost"), (int, float)):
        usd = float(c["total_cost"])
    elif cfg.get("price"):
        usd = (tin * cfg["price"][0] + tout * cfg["price"][1]) / 1e6
    meta = {"model": cfg["model"], "preset": preset, "family": cfg["family"], "tokens_in": tin, "tokens_out": tout,
            "usd": round(usd or 0.0, 6), "usd_known": usd is not None, "seconds": round(time.time() - t0, 1),
            "citations": d.get("citations") or [x.get("url") for x in d.get("search_results", []) if isinstance(x, dict)]}
    spend.book(cfg["model"], usd or 0.0, tag=tag or preset)
    return text, meta


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)


class LLMAgent:
    """A bare model as an 'agent': one call, no tools. Good baseline and cheap stand-in."""

    def __init__(self, preset: str, system: str = "You are a careful worker. Follow the task exactly. Output only the deliverable."):
        self.preset, self.system, self.name = preset, system, preset

    def run(self, task: Task) -> Output:
        text, meta = chat(self.preset, self.system, task.material(), max_tokens=16000, tag=task.id)
        return Output(text=text, meta={"agent": self.name, **meta})
