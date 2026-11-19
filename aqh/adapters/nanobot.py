"""Nanobot (HKUDS nanobot-ai) as an agent: `nanobot agent -m` with a throwaway config and workspace.

Model: DeepSeek by default (cheap). The key is passed by env reference (${DEEPSEEK_API_KEY}) in the
config, so it never touches disk. Exec and web tools are off; the agent is restricted to its workspace.
Set NANOBOT_BIN to the nanobot executable if it is not on PATH.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
from pathlib import Path

from ..core import Output, Task
from .. import spend

PRICES = {"deepseek-flash": (0.14, 0.28), "deepseek-v4-pro": (1.32, 3.96)}


class Nanobot:
    """HKUDS nanobot: `nanobot agent -m`, DeepSeek by default, exec/web tools off."""
    name = "nanobot"

    def __init__(self, model: str | None = None, provider: str = "deepseek", key_env: str = "DEEPSEEK_API_KEY"):
        self.model = model or os.environ.get("AQH_NANOBOT_MODEL", "deepseek-flash")
        self.provider, self.key_env = provider, key_env

    def run(self, task: Task) -> Output:
        exe = os.environ.get("NANOBOT_BIN") or shutil.which("nanobot")
        if not exe:
            raise RuntimeError("nanobot not found: pip install nanobot-ai, or set NANOBOT_BIN")
        if not os.environ.get(self.key_env):
            raise RuntimeError(f"env var {self.key_env} is not set")
        spend.guard()
        run = Path(tempfile.mkdtemp(prefix="aqh-nanobot-"))
        home, ws = run / "home", run / "ws"
        home.mkdir(); ws.mkdir()
        material = task.material()
        (ws / "TASK.md").write_text(material, encoding="utf-8")
        cfg = {"providers": {self.provider: {"apiKey": "${" + self.key_env + "}"}},
               "agents": {"defaults": {"workspace": str(ws), "model": self.model, "provider": self.provider, "maxToolIterations": 20}},
               "tools": {"exec": {"enable": False}, "web": {"enable": False}, "restrictToWorkspace": True}}
        (home / "config.json").write_text(json.dumps(cfg))
        prompt = material if len(material) < 60000 else "Read TASK.md in your workspace fully, then reply with ONLY the deliverable."
        env = {k: os.environ[k] for k in ("PATH", "LANG", "SYSTEMROOT") if k in os.environ}
        env.update({self.key_env: os.environ[self.key_env], "HOME": str(home), "USERPROFILE": str(home)})
        t0 = time.time()
        p = subprocess.run([exe, "agent", "-c", str(home / "config.json"), "-w", str(ws), "-m", prompt, "--no-markdown"],
                           env=env, cwd=ws, capture_output=True, text=True, timeout=900)
        final, u = "", {}
        for db in home.rglob("sessions.sqlite3"):
            c = sqlite3.connect(db)
            for (m,) in c.execute("select metadata from sessions"):
                u = json.loads(m).get("_last_usage", {}) or u
            for (r,) in c.execute("select record from messages order by position"):
                m = json.loads(r)
                if m.get("role") == "assistant" and m.get("content") and not m.get("tool_calls"):
                    final = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
        if not final:
            final = p.stdout.strip()
        tin, tout = u.get("input_tokens", 0), u.get("output_tokens", 0)
        pr = PRICES.get(self.model)
        usd = (tin * pr[0] + tout * pr[1]) / 1e6 if pr else 0.0
        spend.book(f"nanobot/{self.model}", usd, tag=task.id)
        return Output(text=final.strip(), meta={"agent": self.name, "model": self.model, "family": "deepseek", "rc": p.returncode,
                                                 "usd": round(usd, 6), "tokens_in": tin, "tokens_out": tout,
                                                 "seconds": round(time.time() - t0, 1)})
