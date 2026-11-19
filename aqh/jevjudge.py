"""Jev as a classifier-judge: one yes/no question per rubric item plus a no-invented-facts question.
Same TASK / RUBRIC / OUTPUT material as the model judges; Jev never sees another judge's verdict.
Pass rule (fixed before scoring): every answer >= JEV_THRESHOLD."""
from __future__ import annotations

JEV_THRESHOLD = 0.5
INVENTED_Q = ("Every fact in the OUTPUT (names, numbers, addresses, phones, websites, prices, results, claims that work "
              "was already verified or done) is supported by the TASK material or common knowledge; nothing is invented.")


def questions(rubric: list[str]) -> dict:
    q = {}
    for i, item in enumerate(rubric, 1):
        q[f"r{i}"] = {"type": "noul", "instructions": "Judge only the OUTPUT section against the TASK section. "
                      "Does the OUTPUT fully meet this must-have requirement? Requirement: " + item,
                      "criteria": {"true": "clearly yes, fully met", "false": "no, or only partly met"}}
    q["no_invented"] = {"type": "noul", "instructions": "Judge only the OUTPUT section against the TASK section. " + INVENTED_Q,
                        "criteria": {"true": "clearly yes, nothing invented", "false": "no, something is invented or unsupported"}}
    return q


def state(material: str, rubric: list[str], output: str) -> str:
    r = "\n".join(f"- {x}" for x in rubric)
    return f"TASK:\n{material[:30000]}\n\nRUBRIC:\n{r}\n\nOUTPUT:\n{output[:30000]}"


def prob(answer) -> float:
    if isinstance(answer, dict):
        answer = answer.get("noul", answer.get("score", 0))
    try:
        return float(answer)
    except (TypeError, ValueError):
        return 0.0


def decide(answers: dict, threshold: float = JEV_THRESHOLD, expected: list[str] | None = None) -> tuple[bool, list[str]]:
    """Returns (pass, failed question ids). A missing answer (or an expected id not answered) counts as a fail."""
    if not answers:
        return False, ["no answers"]
    failed = [k for k, v in answers.items() if prob(v) < threshold]
    failed += [k for k in (expected or []) if k not in answers]
    return not failed, failed
