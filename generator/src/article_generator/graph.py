"""LangGraph writer-reviewer loop.

Nodes are plain functions over our own LLMClient; LangGraph only
orchestrates state and routing, so the generator stays provider-agnostic.

`iteration` counts completed writer passes. A deterministic validation
failure consumes an iteration too: the draft goes back to the writer with
the error as feedback instead of wasting a reviewer call.
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .article import ValidationError, validate_body
from .llm import LLMClient, LLMError
from .prompts import (
    REVIEWER_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    article_prompt,
    outline_prompt,
    reviewer_prompt,
    rewrite_prompt,
)


class ArticleState(TypedDict):
    topic: str
    notes: str
    outline: str
    draft: str
    feedback: list[str]
    iteration: int
    valid: bool
    approved: bool


def initial_state(topic: str, notes: str) -> ArticleState:
    return {
        "topic": topic,
        "notes": notes,
        "outline": "",
        "draft": "",
        "feedback": [],
        "iteration": 0,
        "valid": False,
        "approved": False,
    }


def _review_report(reviewer: LLMClient, topic: str, draft: str) -> dict:
    """One retry on malformed output; a persistent failure becomes a generic
    rejection so a flaky reviewer never blocks the run."""
    fallback = {
        "approved": False,
        "issues": [{"category": "general", "detail": "el revisor no devolvió un informe válido"}],
    }
    for retry_left in (True, False):
        try:
            report = reviewer.generate_json(REVIEWER_SYSTEM_PROMPT, reviewer_prompt(topic, draft))
        except LLMError:
            if retry_left:
                continue
            return fallback
        if isinstance(report.get("approved"), bool) and isinstance(report.get("issues"), list):
            return report
        if not retry_left:
            return fallback
    return fallback


def build_graph(writer: LLMClient, reviewer: LLMClient, max_iterations: int):
    def write(state: ArticleState) -> dict:
        if state["iteration"] == 0:
            outline = writer.generate(SYSTEM_PROMPT, outline_prompt(state["topic"], state["notes"]))
            draft = writer.generate(SYSTEM_PROMPT, article_prompt(state["topic"], state["notes"], outline))
            return {"outline": outline, "draft": draft, "iteration": 1}
        draft = writer.generate(
            SYSTEM_PROMPT,
            rewrite_prompt(state["topic"], state["outline"], state["draft"], state["feedback"]),
        )
        return {"draft": draft, "iteration": state["iteration"] + 1}

    def validate(state: ArticleState) -> dict:
        try:
            validate_body(state["draft"])
        except ValidationError as exc:
            return {"valid": False, "feedback": state["feedback"] + [f"[estructura] {exc}"]}
        return {"valid": True}

    def review(state: ArticleState) -> dict:
        report = _review_report(reviewer, state["topic"], state["draft"])
        if report["approved"]:
            return {"approved": True}
        issues = [
            f"[{issue.get('category', 'general')}] {issue.get('detail', '')}"
            for issue in report["issues"]
        ]
        return {"approved": False, "feedback": state["feedback"] + issues}

    def after_validate(state: ArticleState) -> str:
        if state["valid"]:
            return "review"
        return "write" if state["iteration"] < max_iterations else END

    def after_review(state: ArticleState) -> str:
        if state["approved"] or state["iteration"] >= max_iterations:
            return END
        return "write"

    graph = StateGraph(ArticleState)
    graph.add_node("write", write)
    graph.add_node("validate", validate)
    graph.add_node("review", review)
    graph.add_edge(START, "write")
    graph.add_edge("write", "validate")
    graph.add_conditional_edges("validate", after_validate, {"review": "review", "write": "write", END: END})
    graph.add_conditional_edges("review", after_review, {"write": "write", END: END})
    return graph.compile()
