"""Tests for the LangGraph writer-reviewer loop."""
from article_generator.graph import build_graph, initial_state
from article_generator.llm import LLMError

VALID_BODY = (
    "## Contexto\n\n" + "palabra " * 200
    + "\n\n## Concepto\n\n" + "palabra " * 200
    + "\n\n## Profundidad\n\n" + "palabra " * 200
    + "\n\n## Ejemplos\n\n" + "palabra " * 200
    + "\n\n## Trampas\n\n" + "palabra " * 200
    + "\n\n## Para saber más\n\n"
    + "- [Docs](https://example.com/a)\n"
    + "- [Spec](https://example.com/b)\n"
    + "- [Blog](https://example.com/c)\n"
)

INVALID_BODY = "demasiado corto"


class FakeLLM:
    """Returns queued responses; records prompts it was called with."""

    def __init__(self, responses=None, json_responses=None):
        self.responses = list(responses or [])
        self.json_responses = list(json_responses or [])
        self.prompts = []
        self.json_prompts = []

    def generate(self, system, user):
        self.prompts.append(user)
        return self.responses.pop(0)

    def generate_json(self, system, user):
        self.json_prompts.append(user)
        item = self.json_responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


APPROVED = {"approved": True, "issues": []}
REJECTED = {
    "approved": False,
    "issues": [{"category": "codigo", "detail": "falta import de Flux"}],
}


def invoke(writer, reviewer, max_iterations=2):
    graph = build_graph(writer, reviewer, max_iterations)
    return graph.invoke(initial_state("Project Reactor", "notas"))


def test_approved_on_first_pass():
    writer = FakeLLM(responses=["outline", VALID_BODY])
    reviewer = FakeLLM(json_responses=[APPROVED])
    state = invoke(writer, reviewer)
    assert state["approved"] is True
    assert state["draft"] == VALID_BODY
    assert state["iteration"] == 1
    assert len(writer.prompts) == 2  # outline + article


def test_rejected_then_approved_rewrite_gets_feedback():
    writer = FakeLLM(responses=["outline", VALID_BODY, VALID_BODY + "\nmejorado.\n"])
    reviewer = FakeLLM(json_responses=[REJECTED, APPROVED])
    state = invoke(writer, reviewer)
    assert state["approved"] is True
    assert state["iteration"] == 2
    rewrite = writer.prompts[2]
    assert "falta import de Flux" in rewrite
    assert "outline" in rewrite


def test_rejected_at_max_iterations_ends_unapproved():
    writer = FakeLLM(responses=["outline", VALID_BODY, VALID_BODY])
    reviewer = FakeLLM(json_responses=[REJECTED, REJECTED])
    state = invoke(writer, reviewer)
    assert state["approved"] is False
    assert state["iteration"] == 2
    assert len(state["feedback"]) == 2  # one rejection per review


def test_validation_failure_feeds_back_without_calling_reviewer():
    writer = FakeLLM(responses=["outline", INVALID_BODY, VALID_BODY])
    reviewer = FakeLLM(json_responses=[APPROVED])
    state = invoke(writer, reviewer)
    assert state["approved"] is True
    assert len(reviewer.json_prompts) == 1  # invalid draft never reached the reviewer
    assert any("[estructura]" in f for f in state["feedback"])
    assert "[estructura]" in writer.prompts[2]  # rewrite prompt carries the error


def test_validation_failure_at_max_iterations_ends_unapproved():
    writer = FakeLLM(responses=["outline", INVALID_BODY, INVALID_BODY])
    reviewer = FakeLLM(json_responses=[])
    state = invoke(writer, reviewer)
    assert state["approved"] is False
    assert len(reviewer.json_prompts) == 0


def test_reviewer_invalid_json_retries_once_then_rejects_generically():
    writer = FakeLLM(responses=["outline", VALID_BODY, VALID_BODY])
    reviewer = FakeLLM(json_responses=[LLMError("bad json"), LLMError("bad json"), APPROVED])
    state = invoke(writer, reviewer)
    # First review: two failures -> generic rejection. Rewrite. Second review: approved.
    assert state["approved"] is True
    assert any("informe válido" in f for f in state["feedback"])
    assert len(reviewer.json_prompts) == 3


def test_reviewer_json_missing_keys_treated_as_invalid():
    writer = FakeLLM(responses=["outline", VALID_BODY, VALID_BODY])
    reviewer = FakeLLM(json_responses=[{"foo": "bar"}, {"foo": "bar"}, APPROVED])
    state = invoke(writer, reviewer)
    assert state["approved"] is True
    assert len(reviewer.json_prompts) == 3
