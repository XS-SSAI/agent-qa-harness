"""Manual paste mode for chat apps with no API you can drive (Microsoft Copilot, ChatGPT app, Claude app).

  aqh manual export --task tasks/X.json            -> writes a prompt file to paste into the app
  (paste it into the app, copy the full reply, save it as a .txt/.md file)
  aqh manual score --task tasks/X.json --agent chatgpt-app --reply reply.txt
                                                    -> scores the reply with the same QA layers
The ReplayAgent below is what `manual score` uses: it returns the pasted reply as the agent's output.
"""
from __future__ import annotations

from pathlib import Path

from ..core import Output, Task

APP_NOTES = {
    "copilot-app": "Microsoft Copilot (copilot.microsoft.com or Microsoft 365 Copilot Chat)",
    "chatgpt-app": "ChatGPT (chatgpt.com or desktop app)",
    "claude-app": "Claude (claude.ai or desktop app)",
}


def export_prompt(task: Task, out: str | Path) -> Path:
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    head = ("PASTE EVERYTHING BELOW INTO THE APP AS ONE MESSAGE. Start a new chat. Do not add anything.\n"
            "Then copy the app's full reply into a text file.\n" + "=" * 72 + "\n\n")
    p.write_text(head + task.material(), encoding="utf-8")
    return p


class ReplayAgent:
    """Returns a saved reply as the output (manual mode, or re-scoring an old run)."""

    def __init__(self, reply_path: str | Path, name: str = "manual"):
        self.reply_path, self.name = Path(reply_path), name

    def run(self, task: Task) -> Output:
        text = self.reply_path.read_text(encoding="utf-8")
        if text.startswith("PASTE EVERYTHING BELOW"):
            raise RuntimeError("that file is the exported prompt, not the app's reply")
        return Output(text=text.strip(), meta={"agent": self.name, "mode": "manual-paste", "source": self.reply_path.name,
                                               "app": APP_NOTES.get(self.name, self.name)})
