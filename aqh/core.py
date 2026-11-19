"""The two contracts. Everything else is an implementation of one of them.

Agent adapter:  run(task) -> Output
QA layer:       score(output, task) -> Verdict
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@dataclass
class Task:
    id: str
    prompt: str
    kind: str = "report"            # gate kind: article, report, web, chat, data, ...
    data_label: str = "public"      # public | synthetic | private (label before the run)
    inputs: dict[str, Any] = field(default_factory=dict)   # extra material: files, records, profile path
    expect: dict[str, Any] = field(default_factory=dict)   # what QA should check (counts, required lines, ...)
    family: str = ""                # task family for the trust ladder
    heldout: bool = False           # frozen eval task; skipped in suites unless --include-heldout

    @classmethod
    def load(cls, path: str | Path) -> "Task":
        p = Path(path)
        d = json.loads(p.read_text(encoding="utf-8"))
        d.setdefault("id", p.stem)
        t = cls(**d)
        t.inputs.setdefault("_base", str(p.parent.resolve()))
        return t

    def material(self) -> str:
        """Prompt plus any inline input files, ready to send to a text agent."""
        base = Path(self.inputs.get("_base", "."))
        parts = []
        if self.inputs.get("writer_instructions"):
            from .qa.profile import WRITER_INSTRUCTIONS
            parts.append("=== WRITER INSTRUCTIONS ===\n" + WRITER_INSTRUCTIONS)
        parts.append("=== TASK ===\n" + self.prompt)
        for f in self.inputs.get("files", []):
            fp = (base / f) if not Path(f).is_absolute() else Path(f)
            parts.append(f"\n--- {fp.name} ---\n" + fp.read_text(encoding="utf-8"))
        return "\n".join(parts)


@dataclass
class Output:
    text: str
    artifacts: dict[str, str] = field(default_factory=dict)   # name -> path or inline content
    meta: dict[str, Any] = field(default_factory=dict)        # agent, model, usd, tokens, seconds, rc


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Verdict:
    passed: bool
    checks: list[Check] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_checks(cls, checks: list[Check], **meta) -> "Verdict":
        reasons = [f"{c.name}: {c.detail}" for c in checks if not c.passed]
        return cls(passed=not reasons, checks=checks, reasons=reasons, meta=meta)

    def to_dict(self) -> dict:
        return asdict(self)


@runtime_checkable
class Agent(Protocol):
    name: str

    def run(self, task: Task) -> Output: ...


@runtime_checkable
class QALayer(Protocol):
    name: str

    def score(self, output: Output, task: Task) -> Verdict: ...
