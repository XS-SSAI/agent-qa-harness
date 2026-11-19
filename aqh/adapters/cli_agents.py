"""Agents driven as local CLI programs (subprocess). One small class per agent.

Each run gets a fresh temp working folder containing TASK.md (and any input files), so the agent
can read long material from disk. Safe defaults: read-only or default permission modes, no bypass
or "yolo" flags, no auto-approve. The owner's own login/subscription for each CLI is used.

Verified status is tracked in STATUS below and printed by `aqh agents`.
"""
from __future__ import annotations

import json
import re
import os
import signal
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ..core import Output, Task

STATUS = {}  # name -> "executed in dry run" | "written, not executed (reason)"


def _which(cmd: str) -> str | None:
    return shutil.which(cmd) or shutil.which(cmd + ".cmd") or shutil.which(cmd + ".exe")


def _kill_process_group(pid: int) -> None:
    """Stop a timed-out agent and any child processes it started (OpenCode left a leftover process)."""
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=15)
        else:
            os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError, subprocess.TimeoutExpired):
        pass


class CLIAgent:
    name = "cli"
    binary = ""
    status = "written, not executed"
    prefer_file_prompt = False  # True: always point the agent at TASK.md (safer than a huge argv)

    @property
    def timeout(self) -> int:
        from ..locked import timeout_seconds
        return timeout_seconds()

    def argv(self, prompt: str, workdir: Path) -> list[str]:
        raise NotImplementedError

    def parse(self, stdout: str, workdir: Path) -> tuple[str, dict]:
        return stdout.strip(), {}

    def extra_env(self, workdir: Path) -> dict[str, str]:
        """Extra subprocess environment. Keys already in the process env are inherited."""
        return {}

    file_prompt = None  # class-specific FILE_PROMPT override (None = shared FILE_PROMPT)

    def before_run(self, wd: Path) -> dict:
        """Hook called just before the agent starts (e.g. read a usage counter). Returns state for after_run."""
        return {}

    def after_run(self, state: dict, meta: dict) -> None:
        """Hook called after the agent exits, to fill meta (e.g. cost) from before_run state."""

    stdin_ok = False  # True if the CLI reads extra material from stdin
    uses_spend_cap = False  # True if this agent can incur billed model spend

    def run(self, task: Task) -> Output:
        exe = _which(self.binary)
        if not exe:
            raise RuntimeError(f"'{self.binary}' not found on PATH. Install it and sign in first (see RUN-IT-YOURSELF.md).")
        wd = Path(tempfile.mkdtemp(prefix=f"aqh-{self.name}-"))
        material = task.material()
        (wd / "TASK.md").write_text(material, encoding="utf-8")
        # Windows .cmd wrappers (npm installs) cut arguments at the first newline, so the full task never goes
        # on the command line there: the agent gets one line pointing at TASK.md (and stdin when supported).
        if self.prefer_file_prompt or os.name == "nt" or len(material) > 20000 or "\n" in material and exe.lower().endswith((".cmd", ".bat")):
            prompt = self.file_prompt or FILE_PROMPT
        else:
            prompt = material
        cmd = self.argv(prompt, wd)
        cmd[0] = exe
        if self.uses_spend_cap:
            from .. import spend
            spend.guard()
        env = os.environ.copy()
        env.update(self.extra_env(wd))
        t0 = time.time()
        hook_state = self.before_run(wd)
        stdin = material if (self.stdin_ok and prompt == FILE_PROMPT) else None
        proc = subprocess.Popen(cmd, cwd=wd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace", start_new_session=True, env=env)
        try:
            stdout, stderr = proc.communicate(input=stdin, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            _kill_process_group(proc.pid)
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise RuntimeError(
                f"{self.name} timed out after {self.timeout}s and was stopped, including child processes. "
                "This is a FAIL, not a skip."
            ) from None
        # Match the previous CompletedProcess shape used by parse + meta.
        class _Done:
            def __init__(self, rc, out, err):
                self.returncode, self.stdout, self.stderr = rc, out, err
        p = _Done(proc.returncode, stdout or "", stderr or "")
        text, meta = self.parse(p.stdout, wd)
        if p.returncode != 0 and not text and meta.get("error"):
            p.stderr = (p.stderr or "") + "\n" + str(meta["error"])
        if not deliverable_present(text):
            found = find_deliverable_file(wd, t0)
            if found:
                name, body = found
                meta["deliverable_source"] = f"file:{name}"
                meta["stdout_text"] = text[:2000]
                text = body
        self.after_run(hook_state, meta)

        meta.update(agent=self.name, rc=p.returncode, seconds=round(time.time() - t0, 1), prompt_via="file" if prompt == FILE_PROMPT else "argv")
        if meta.get("usd") is not None:
            from .. import spend
            spend.book(str(meta.get("model") or self.name), meta["usd"], tag=task.id)
        if p.returncode != 0 and not text:
            raise RuntimeError(f"{self.name} exited {p.returncode}: {p.stderr[-2000:]}")
        return Output(text=text, meta=meta)


# ---- Scoring v2: deliverable fallback --------------------------------------------------------------
# Some agents (Grok Build on the methodology pages) end their turn with narration ("I'll read TASK.md...")
# and leave the actual page in a file in their workdir. If stdout has no deliverable, the harness scores
# the deliverable file the agent saved in the workdir instead (any adapter). Preference: DELIVERABLE.md,
# then the largest .md/.json/.html/.txt file written during the run. Harness files and dot-folders are skipped.
NARRATION_START = re.compile(r"^\s*(?:I'?ll|I will|I'm going to|I am going to|Let me|Now I|First,? I|Next,? I|Okay|OK,)\b", re.I)
DELIVERABLE_NAMES = ("DELIVERABLE.md", "deliverable.md", "OUTPUT.md", "output.md")
HARNESS_FILES = {"TASK.md", "query.txt"}
MIN_DELIVERABLE_WORDS = 120


def deliverable_present(text: str) -> bool:
    """False when stdout is empty or only short narration with no page/JSON structure."""
    t = (text or "").strip()
    if not t:
        return False
    if t[0] in "[{" or re.search(r"(?m)^#{1,3} \S", t):
        return True
    words = len(t.split())
    if NARRATION_START.match(t) and words < 400:
        return False
    return words >= MIN_DELIVERABLE_WORDS


def find_deliverable_file(wd: Path, since: float = 0.0) -> tuple[str, str] | None:
    wd = Path(wd)
    cands = []
    for f in wd.rglob("*"):
        rel = f.relative_to(wd)
        if not f.is_file() or any(part.startswith(".") for part in rel.parts) or f.name in HARNESS_FILES:
            continue
        if f.suffix.lower() not in (".md", ".json", ".html", ".txt") or f.stat().st_mtime < since - 1:
            continue
        try:
            body = f.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if len(body.split()) < 40 and not body.startswith(("[", "{")):
            continue
        named = f.name in DELIVERABLE_NAMES
        cands.append((named, f.suffix.lower() != ".txt", len(body), str(rel).replace("\\", "/"), body))
    if not cands:
        return None
    cands.sort(reverse=True)
    return cands[0][3], cands[0][4]


FILE_PROMPT = ("Your full task and its data are in the file TASK.md in the current folder. Read all of it first, "
               "then reply with ONLY the deliverable it asks for, no preamble and no questions.")


class EchoCLI(CLIAgent):
    """Test double: a tiny script that prints a reply file. Proves the subprocess plumbing on any OS."""
    name, binary = "echo-cli", "aqh-echo"

    def argv(self, prompt, wd):
        return [self.binary, prompt]


class ClaudeCode(CLIAgent):
    """Anthropic Claude Code: `claude -p` (print mode), JSON result, default permission mode."""
    name, binary, stdin_ok = "claude-code", "claude", True

    def argv(self, prompt, wd):
        m = os.environ.get("AQH_CLAUDE_MODEL")
        return [self.binary, "-p", prompt, "--output-format", "json"] + (["--model", m] if m else [])

    def parse(self, stdout, wd):
        try:
            d = json.loads(stdout)
            return d.get("result", ""), {"usd": d.get("total_cost_usd"), "model": "claude-code"}
        except json.JSONDecodeError:
            return stdout.strip(), {}


class Codex(CLIAgent):
    """OpenAI Codex CLI: `codex exec` non-interactive, read-only sandbox, last message to a file."""
    name, binary = "codex", "codex"

    def argv(self, prompt, wd):
        m = os.environ.get("AQH_CODEX_MODEL")
        return [self.binary, "exec", "--skip-git-repo-check", "--sandbox", "read-only",
                "--output-last-message", str(wd / "last.txt")] + (["-m", m] if m else []) + [prompt]

    def parse(self, stdout, wd):
        f = wd / "last.txt"
        return (f.read_text(encoding="utf-8").strip() if f.exists() else stdout.strip()), {"model": "codex"}


# ANSI and CLI chrome that Copilot prints around the deliverable in `copilot -p` output.
# Kept conservative: only known banners, tool traces, usage footers, and their indented wraps.
_ANSI_RE = re.compile(r"\x1b(?:\[[0-9;?]*[A-Za-z]|\].*?(?:\x07|\x1b\\))")
_CHROME_RE = re.compile(
    r"""(?x)^
    \s*
    (?:
        [?●!✗*/$•]\s |
        (?:MD|PY|JSON|TS|JS|SH|\{\})\s+Read\b |
        Changes\s+\+\d+ |
        AI[ ]Credits\b |
        Tokens\s+ |
        Resume\s+copilot\b |
        Third-party[ ]MCP[ ]servers[ ]are[ ]disabled |
        \d+\s+MCP[ ]server[ ]was[ ]blocked[ ]by[ ]policy |
        Approval[ ]check\b |
        Permission[ ]denied[ ]because[ ]no[ ]interactive |
        Denied,[ ]no[ ]one[ ]to[ ]approve |
        Copilot[ ]Fusion[ ]selected\b
    )
    """
)


def _strip_copilot_cli_chrome(stdout: str) -> str:
    """Return only the agent deliverable, without Copilot CLI banners, traces, or usage stats."""
    lines = _ANSI_RE.sub("", stdout or "").splitlines()
    i, j = 0, len(lines)
    while i < j:
        raw = lines[i]
        if not raw.strip() or _CHROME_RE.match(raw) or raw.startswith("  "):
            i += 1
            continue
        break
    while j > i:
        raw = lines[j - 1]
        if not raw.strip() or _CHROME_RE.match(raw):
            j -= 1
            continue
        break
    return "\n".join(lines[i:j]).strip()


class CopilotCLI(CLIAgent):
    """GitHub Copilot CLI: `copilot -p` non-interactive. No --allow-all-tools; tools stay denied.

    parse() strips CLI chrome (Fusion banner, tool traces, usage footer) so only the deliverable is scored.
    """
    name, binary = "copilot-cli", "copilot"

    def argv(self, prompt, wd):
        m = os.environ.get("AQH_COPILOT_MODEL")
        return [self.binary, "-p", prompt, "--no-color"] + (["--model", m] if m else [])

    def parse(self, stdout, wd):
        return _strip_copilot_cli_chrome(stdout), {"model": "copilot-cli"}


class CursorAgent(CLIAgent):
    """Cursor CLI: `cursor-agent -p` print mode, text output, `--trust` for headless workspace trust (never --yolo/-f)."""
    name, binary = "cursor", "cursor-agent"

    def argv(self, prompt, wd):
        m = os.environ.get("AQH_CURSOR_MODEL")
        return [self.binary, "-p", prompt, "--output-format", "text", "--trust"] + (["--model", m] if m else [])


class OpenCode(CLIAgent):
    """OpenCode (open source): `opencode run`. Works with cheap models, e.g. AQH_OPENCODE_MODEL=deepseek/deepseek-chat.

    Always reads TASK.md (prefer_file_prompt). On a methodology-page run the agent hung for the
    full 15-minute timeout with no output, and a leftover process kept the harness open. The
    shared runner now uses a process group and kills the whole tree on timeout.
    """
    name, binary = "opencode", "opencode"
    prefer_file_prompt = True
    uses_spend_cap = True  # OpenRouter-billed (scoring v2: its cost is booked in the spend ledger)

    def argv(self, prompt, wd):
        m = os.environ.get("AQH_OPENCODE_MODEL")
        return [self.binary, "run", "--format", "json"] + (["-m", m] if m else []) + [prompt]

    def parse(self, stdout, wd):
        return parse_opencode_json(stdout)

    def before_run(self, wd):
        return {"or_usage": openrouter_key_usage()}

    def after_run(self, state, meta):
        """Cost: step-finish 'cost' from the JSON events if present, else the OpenRouter key-usage delta."""
        if meta.get("usd") is not None:
            meta["usd_source"] = "opencode step_finish cost"
            return
        before = state.get("or_usage")
        after = openrouter_key_usage() if before is not None else None
        if before is not None and after is not None:
            meta["usd"] = round(max(0.0, after - before), 6)
            meta["usd_source"] = "OpenRouter key usage delta (OPENROUTER_API_KEY)"


def parse_opencode_json(stdout: str) -> tuple[str, dict]:
    """`opencode run --format json` prints one JSON event per line (step_start, text, tool_use, step_finish, error).
    The deliverable is the text of the LAST step (earlier steps are narration between tool calls)."""
    steps, cur, cost, errors, model, seen = [], [], 0.0, [], None, False
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        seen = True
        typ, part = ev.get("type"), ev.get("part") or {}
        if typ == "step_start":
            if cur:
                steps.append(cur)
            cur = []
        elif typ == "text" and part.get("text"):
            cur.append(part["text"])
        elif typ == "step_finish":
            c = part.get("cost")
            if isinstance(c, (int, float)):
                cost += float(c)
        elif typ == "error":
            err = ev.get("error") or part.get("error") or ev
            errors.append(json.dumps(err)[:400] if not isinstance(err, str) else err[:400])
        model = model or part.get("modelID") or ev.get("modelID")
    if cur:
        steps.append(cur)
    if not seen:
        return (stdout or "").strip(), {"model": os.environ.get("AQH_OPENCODE_MODEL") or "opencode"}
    text = "".join(steps[-1]).strip() if steps else ""
    meta = {"model": model or os.environ.get("AQH_OPENCODE_MODEL") or "opencode"}
    if cost > 0:
        meta["usd"] = round(cost, 6)
    if errors:
        meta["error"] = " | ".join(errors)
    return text, meta


def openrouter_key_usage() -> float | None:
    """Total USD used so far by OPENROUTER_API_KEY (GET /api/v1/key). None if no key or the call fails.
    Assumes OpenCode bills through the same OpenRouter key; the key is never printed."""
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key or os.environ.get("AQH_NO_NETWORK"):
        return None
    import urllib.request
    try:
        req = urllib.request.Request("https://openrouter.ai/api/v1/key", headers={"Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.loads(r.read().decode()).get("data", {})
        u = d.get("usage")
        return float(u) if isinstance(u, (int, float)) else None
    except Exception:  # noqa: BLE001
        return None


class GeminiCLI(CLIAgent):
    """Google Gemini CLI: `gemini -p` non-interactive."""
    name, binary, stdin_ok = "gemini-cli", "gemini", True

    def argv(self, prompt, wd):
        m = os.environ.get("AQH_GEMINI_MODEL")
        return [self.binary, "-p", prompt] + (["-m", m] if m else [])


class Hermes(CLIAgent):
    """Nous Research Hermes Agent: `hermes chat --query-file`, stream-json, file tool only."""
    name, binary = "hermes", "hermes"

    def argv(self, prompt, wd):
        (wd / "query.txt").write_text(prompt, encoding="utf-8")
        return [self.binary, "chat", "--query-file", str(wd / "query.txt"), "--format", "stream-json", "-t", "file", "--max-turns", "20"]

    def parse(self, stdout, wd):
        text = ""
        for line in stdout.splitlines():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") == "result":
                text = d.get("result") or d.get("text") or text
        return text.strip(), {"model": "hermes"}


DEFAULT_GROK_MODEL = "grok-4.7"  # official current best Grok coding model (docs.x.ai)


class GrokBuild(CLIAgent):
    """Official xAI Grok Build CLI (`grok -p`), not the Grok Bot app.

    Headless JSON, permission-mode dontAsk with explicit Read/Edit/Write/Grep allows,
    workspace sandbox (writes limited to the task folder), and `--trust` for that
    folder only. Never --always-approve, --yolo, or --dangerously-skip-permissions.
    A clean HOME/GROK_HOME isolates the run from the machine's user skills and MCP.
    """
    name, binary, uses_spend_cap = "grok", "grok", True
    prefer_file_prompt = True  # always use the TASK.md prompt below (Windows already did; now Linux/macOS too)
    # Scoring v2: Grok sometimes ended with narration only. Tell it to save the page to DELIVERABLE.md and
    # also print it; the harness scores DELIVERABLE.md when stdout has no deliverable.
    file_prompt = ("Your full task and its data are in the file TASK.md in the current folder. Read all of it first. "
                   "Write the COMPLETE deliverable it asks for to a file named DELIVERABLE.md in the current folder, "
                   "then reply with ONLY that same full deliverable text: no preamble, no plan, no summary of what you did, "
                   "and no questions. Your final message must be the deliverable itself.")

    def argv(self, prompt, wd):
        from ..locked import max_turns
        m = os.environ.get("AQH_GROK_MODEL") or DEFAULT_GROK_MODEL
        cmd = [self.binary, "-p", prompt, "--output-format", "json",
               "--permission-mode", "dontAsk",
               "--allow", "Read", "--allow", "Edit", "--allow", "Write", "--allow", "Grep",
               "--sandbox", "workspace", "--disable-web-search", "--no-plan",
               "--no-alt-screen", "--no-subagents", "--trust", "--max-turns", str(max_turns()),
               "-m", m]
        effort = os.environ.get("AQH_GROK_EFFORT")
        if effort:
            cmd.extend(["--reasoning-effort", effort])
        return cmd

    def extra_env(self, workdir: Path) -> dict[str, str]:
        home = workdir / ".aqh-home"
        grok_home = workdir / ".aqh-grok"
        (home / ".config").mkdir(parents=True, exist_ok=True)
        grok_home.mkdir(parents=True, exist_ok=True)
        return {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "GROK_HOME": str(grok_home),
            "GROK_DISABLE_AUTOUPDATER": "1",
            "GROK_MEMORY": "0",
            "GROK_SUBAGENTS": "0",
            "GROK_WEB_FETCH": "0",
        }

    def parse(self, stdout, wd):
        d = _parse_json_payload(stdout)
        if d is None:
            return (stdout or "").strip(), {"model": "grok (Grok Build CLI)"}
        text = d.get("result") or d.get("text") or ""
        model = d.get("model")
        usage = d.get("modelUsage") if isinstance(d.get("modelUsage"), dict) else {}
        if not model and usage:
            model = next(iter(usage), None)
        usd = d.get("total_cost_usd")
        if usd is None and isinstance(usage, dict):
            costs = [v.get("costUSD") for v in usage.values() if isinstance(v, dict) and isinstance(v.get("costUSD"), (int, float))]
            if costs:
                usd = sum(costs)
        label_model = f"{model} (Grok Build CLI)" if model else "grok (Grok Build CLI)"
        meta = {"model": label_model, "adapter": "Grok Build CLI"}
        if model:
            meta["model_id"] = model
        if usd is not None:
            meta["usd"] = float(usd)
        if d.get("num_turns") is not None:
            meta["turns"] = d.get("num_turns")
        return str(text).strip(), meta


def _parse_json_payload(stdout: str) -> dict | None:
    raw = (stdout or "").strip()
    if not raw:
        return None
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else None
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            d = json.loads(raw[start:end + 1])
            return d if isinstance(d, dict) else None
        except json.JSONDecodeError:
            return None
    return None
