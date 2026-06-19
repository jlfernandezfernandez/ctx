"""Reviewer agent: judges article quality and returns actionable issues."""
from ..llm import LLMClient, LLMError
from ..prompt import load_system_prompt


SYSTEM_PROMPT = load_system_prompt("reviewer")


REVIEWER_SCHEMA = {
    "title": "review",
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": ["codigo", "rigor", "legibilidad"]},
                    "detail": {"type": "string"},
                    "blocking": {"type": "boolean"},
                },
                "required": ["category", "detail", "blocking"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["issues"],
    "additionalProperties": False,
}


def reviewer_prompt(topic: str, body: str, previous_feedback: list[str] | None = None) -> str:
    previous = ""
    if previous_feedback:
        fixed = "\n".join(f"- {item}" for item in previous_feedback)
        previous = f"""

En una ronda anterior señalaste estos defectos:
{fixed}

Comprueba que están resueltos. Solo añade bloqueantes nuevos si son errores objetivos importantes."""
    return f"""Revisa este artículo técnico sobre "{topic}":

<articulo>
{body}
</articulo>{previous}

Devuelve SOLO el informe JSON definido en tu system prompt."""


def review_article(
    llm: LLMClient, topic: str, body: str, previous_feedback: list[str] | None = None
) -> dict | None:
    try:
        return llm.generate_structured(
            SYSTEM_PROMPT, reviewer_prompt(topic, body, previous_feedback), REVIEWER_SCHEMA
        )
    except LLMError:
        return None


def split_issues(report: dict) -> tuple[list[str], list[str]]:
    """Return blocking issues and non-blocking suggestions."""
    blocking, suggestions = [], []
    for issue in report["issues"]:
        line = f"[{issue['category']}] {issue['detail']}"
        if issue["blocking"] is False:
            suggestions.append(line)
        else:
            blocking.append(line)
    return blocking, suggestions
