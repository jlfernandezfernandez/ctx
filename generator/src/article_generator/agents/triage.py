"""Triage agent: accepts, rejects or escalates topic proposals."""
from dataclasses import dataclass

from ..llm import LLMClient
from ..prompt import load_system_prompt


SYSTEM_PROMPT = load_system_prompt("triage")


class TriageError(Exception):
    pass


@dataclass(frozen=True)
class Classification:
    action: str
    title: str
    description: str
    reason: str


def parse_classification(data: dict) -> Classification:
    action = data.get("action")
    title = data.get("title")
    description = data.get("description")
    reason = data.get("reason")
    if not isinstance(action, str) or action.upper() not in {"APPROVE", "REJECT", "REVIEW"}:
        raise TriageError("triage action must be APPROVE, REJECT or REVIEW")
    if not isinstance(title, str) or not title.strip():
        raise TriageError("triage title is empty")
    if not isinstance(reason, str) or not reason.strip():
        raise TriageError("triage reason is empty")
    if description is None or not isinstance(description, str):
        description = ""
    return Classification(
        action.upper(), title.strip()[:300], description.strip()[:1000], reason.strip()[:160]
    )


def classification_prompt(title: str, body: str) -> str:
    return f"""<propuesta>
Título: {title[:300]}
Notas:
{body[:3000]}
</propuesta>"""


def classify(llm: LLMClient, title: str, body: str) -> Classification:
    data = llm.generate_json(SYSTEM_PROMPT, classification_prompt(title, body))
    return parse_classification(data)
