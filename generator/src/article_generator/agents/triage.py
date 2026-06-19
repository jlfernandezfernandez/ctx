"""Triage agent: accepts, rejects or escalates topic proposals."""
from dataclasses import dataclass

from ..llm import LLMClient
from ..prompt import load_system_prompt


SYSTEM_PROMPT = load_system_prompt("triage")


TRIAGE_SCHEMA = {
    "title": "classification",
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["APPROVE", "REJECT", "REVIEW"]},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": ["action", "title", "description", "reason"],
    "additionalProperties": False,
}


class TriageError(Exception):
    pass


@dataclass(frozen=True)
class Classification:
    action: str
    title: str
    description: str
    reason: str


def parse_classification(data: dict) -> Classification:
    action = data.get("action", "").strip().upper()
    title = data.get("title", "").strip()
    reason = data.get("reason", "").strip()
    description = data.get("description", "").strip()
    if action not in {"APPROVE", "REJECT", "REVIEW"}:
        raise TriageError("triage action must be APPROVE, REJECT or REVIEW")
    if not title:
        raise TriageError("triage title is empty")
    if not reason:
        raise TriageError("triage reason is empty")
    return Classification(action, title[:300], description[:1000], reason[:160])


def classification_prompt(title: str, body: str) -> str:
    return f"""<propuesta>
Título: {title[:300]}
Notas:
{body[:3000]}
</propuesta>"""


def classify(llm: LLMClient, title: str, body: str) -> Classification:
    data = llm.generate_structured(
        SYSTEM_PROMPT, classification_prompt(title, body), TRIAGE_SCHEMA
    )
    return parse_classification(data)
