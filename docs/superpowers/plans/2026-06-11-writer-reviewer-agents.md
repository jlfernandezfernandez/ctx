# Writer–Reviewer Agents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the linear article generation with a LangGraph writer–reviewer loop using two Ollama Cloud models; rejected articles become draft PRs for human rescue.

**Architecture:** A `StateGraph` with three nodes (write → validate → review) and conditional routing. Nodes are plain functions over the existing `LLMClient` (no LangChain wrappers). `main.py` invokes the graph per topic: approved → existing publish flow; rejected after max iterations → draft PR + `needs-human-review` label, then try the next topic (max 2 per run).

**Tech Stack:** Python 3.11+, langgraph (orchestration only), requests, pytest. GitHub REST API for branches/PRs. Spec: `docs/superpowers/specs/2026-06-11-writer-reviewer-agents-design.md`.

**Conventions:** All commands run from `generator/` unless noted. Local venv is `generator/.venv`; run tests with `.venv/bin/python -m pytest -q`. Comments/docstrings in English (codebase convention), prompts and user-facing text in Spanish.

---

### Task 1: Add langgraph dependency

**Files:**
- Modify: `generator/pyproject.toml`
- Modify: `generator/uv.lock` (regenerated)

- [ ] **Step 1: Add dependency**

In `generator/pyproject.toml` change:

```toml
dependencies = ["requests>=2.31"]
```

to:

```toml
dependencies = ["requests>=2.31", "langgraph>=1.0"]
```

- [ ] **Step 2: Regenerate lock and install**

```bash
cd generator
uv lock
.venv/bin/python -m pip install -e '.[dev]'
```

Expected: lock updated, install succeeds, `langgraph` importable:

```bash
.venv/bin/python -c "from langgraph.graph import StateGraph, START, END; print('ok')"
```

Expected: `ok`

- [ ] **Step 3: Run existing tests (no regressions)**

```bash
.venv/bin/python -m pytest -q
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add langgraph dependency"
```

---

### Task 2: Reviewer and rewrite prompts

**Files:**
- Modify: `generator/src/article_generator/prompts.py`
- Test: `generator/tests/test_prompts.py`

Note: `review_prompt()` (old code-review pass) is removed later in Task 6, when `main.py` stops importing it.

- [ ] **Step 1: Write failing tests**

Append to `generator/tests/test_prompts.py`:

```python
def test_reviewer_prompt_includes_article_and_json_contract():
    from article_generator.prompts import reviewer_prompt

    p = reviewer_prompt("Project Reactor", "cuerpo del articulo")
    assert "cuerpo del articulo" in p
    assert "Project Reactor" in p
    assert '"approved"' in p
    assert '"issues"' in p
    assert '"category"' in p


def test_rewrite_prompt_includes_outline_draft_and_feedback():
    from article_generator.prompts import rewrite_prompt

    p = rewrite_prompt(
        "Project Reactor",
        "el esquema",
        "el borrador",
        ["[codigo] falta import de Flux", "[rigor] URL inventada"],
    )
    assert "el esquema" in p
    assert "el borrador" in p
    assert "falta import de Flux" in p
    assert "URL inventada" in p
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_prompts.py -q
```

Expected: FAIL with `ImportError` (cannot import `reviewer_prompt`).

- [ ] **Step 3: Implement prompts**

Append to `generator/src/article_generator/prompts.py`:

```python
REVIEWER_SYSTEM_PROMPT = """Eres un revisor técnico exigente de artículos de ingeniería \
de software. Evalúas un artículo escrito por otro modelo antes de su publicación.

Evalúas exactamente tres aspectos:
- codigo: todos los snippets compilan tal cual (imports completos, incluidos los de tipos \
usados solo en firmas; sin APIs inventadas; sin `this` en contextos static) y ningún \
ejemplo contradice las buenas prácticas que el propio artículo enseña.
- rigor: las afirmaciones técnicas son correctas, no hay datos inventados, y las \
referencias apuntan a fuentes reales y plausibles (docs oficiales > papers/specs > blogs \
de ingeniería reconocidos).
- legibilidad: español natural y fluido, términos técnicos en inglés, nivel adecuado \
para un ingeniero competente que no conoce el tema.

No evalúas la estructura (número de secciones, jerarquía de títulos): eso lo cubre un \
validador automático.

Eres estricto con defectos objetivos y tolerante con el estilo: rechaza por código que \
no compila, errores técnicos o referencias inventadas; no rechaces por preferencias \
de redacción."""


def reviewer_prompt(topic: str, body: str) -> str:
    return f"""Revisa este artículo técnico sobre "{topic}":

{body}

Devuelve un objeto JSON con exactamente estas claves:
- "approved": true si el artículo es publicable tal cual, false si tiene defectos que \
el redactor debe corregir.
- "issues": lista (vacía si approved es true) de objetos con claves "category" \
(exactamente una de: "codigo", "rigor", "legibilidad") y "detail" (descripción concreta \
y accionable del defecto, citando la sección o el snippet afectado).

Devuelve SOLO el JSON, sin explicaciones."""


def rewrite_prompt(topic: str, outline: str, body: str, feedback: list[str]) -> str:
    issues = "\n".join(f"- {item}" for item in feedback)
    return f"""Reescribe este artículo técnico sobre: {topic}

Sigue fielmente el esquema original:
{outline}

Versión actual:
{body}

Un revisor ha señalado estos defectos; corrígelos TODOS:
{issues}

Mantén todo lo que el revisor no ha señalado: misma estructura de secciones ##, \
misma extensión (2500-3500 palabras), mismos requisitos que la versión original \
(markdown puro, sin frontmatter ni título principal, código completo y ejecutable, \
última sección "Para saber más" con 3-5 enlaces reales).

Devuelve SOLO el cuerpo completo del artículo corregido en markdown."""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_prompts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/article_generator/prompts.py tests/test_prompts.py
git commit -m "feat: add reviewer and rewrite prompts for agent loop"
```

---

### Task 3: `needs-human-review` label and `add_label` in IssuesClient

**Files:**
- Modify: `generator/src/article_generator/github_issues.py`
- Test: `generator/tests/test_github_issues.py`

- [ ] **Step 1: Write failing tests**

Append to `generator/tests/test_github_issues.py`:

```python
def test_next_topic_skips_needs_human_review():
    c = client_with([
        issue(1, "2026-06-01T00:00:00Z", ["topic", "needs-human-review"]),
        issue(2, "2026-06-02T00:00:00Z", ["topic"]),
    ])
    assert c.next_topic()["number"] == 2


def test_next_topic_none_when_all_need_human_review():
    c = client_with([issue(1, "2026-06-01T00:00:00Z", ["topic", "needs-human-review"])])
    assert c.next_topic() is None


def test_add_label_posts_single_label():
    c = client_with([])
    c.add_label(7, "needs-human-review")
    c.session.post.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/issues/7/labels",
        json={"labels": ["needs-human-review"]},
    )


def test_ensure_system_labels_creates_needs_human_review():
    c = client_with([{"name": "topic"}, {"name": "triage"}])
    c.ensure_system_labels()
    created = [call.kwargs["json"]["name"] for call in c.session.post.call_args_list]
    assert "needs-human-review" in created
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_github_issues.py -q
```

Expected: 4 failures (`AttributeError: add_label`, wrong issue picked, missing label).

- [ ] **Step 3: Implement**

In `generator/src/article_generator/github_issues.py`:

After `RATE_LIMITED_LABEL = "rate-limited"` add:

```python
NEEDS_HUMAN_REVIEW_LABEL = "needs-human-review"
```

Add `NEEDS_HUMAN_REVIEW_LABEL` to the `SYSTEM_LABELS` set, and to `SYSTEM_LABEL_DETAILS`:

```python
    NEEDS_HUMAN_REVIEW_LABEL: ("e99695", "El revisor IA no aprobó el borrador; pendiente de humano"),
```

In `next_topic()` change the list comprehension to:

```python
        issues = [
            i
            for i in resp.json()
            if "pull_request" not in i
            and not any(l["name"] == NEEDS_HUMAN_REVIEW_LABEL for l in i["labels"])
        ]
```

Add method after `set_labels`:

```python
    def add_label(self, number: int, label: str) -> None:
        resp = self.session.post(
            f"{self.base}/issues/{number}/labels",
            json={"labels": [label]},
        )
        self._require(resp, (200, 201), f"add label {label} to issue #{number}")
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_github_issues.py -q
```

Expected: PASS (all, including pre-existing).

- [ ] **Step 5: Commit**

```bash
git add src/article_generator/github_issues.py tests/test_github_issues.py
git commit -m "feat: add needs-human-review label and add_label method"
```

---

### Task 4: Extract `render_article` from `write_article`

**Files:**
- Modify: `generator/src/article_generator/article.py:157-191`
- Test: `generator/tests/test_article.py`

Why: the draft-PR path needs the rendered markdown (frontmatter + body) as a string to push via the GitHub contents API, without touching local disk.

- [ ] **Step 1: Write failing test**

Append to `generator/tests/test_article.py`:

```python
def test_render_article_returns_frontmatter_and_body():
    from datetime import date

    from article_generator.article import render_article

    content = render_article(
        pub_date=date(2026, 6, 11),
        title="Project Reactor",
        description="desc",
        tags=["java"],
        body="## Sección\n\nTexto.",
        summary="El TL;DR.",
        issue_number=5,
        requested_by="jordi",
        model="writer + reviewer (reviewer)",
    )
    assert content.startswith("---\n")
    assert 'title: "Project Reactor"' in content
    assert "pubDate: 2026-06-11" in content
    assert 'model: "writer + reviewer (reviewer)"' in content
    assert content.endswith("## Sección\n\nTexto.\n")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_article.py -q
```

Expected: FAIL with `ImportError` (cannot import `render_article`).

- [ ] **Step 3: Refactor**

In `generator/src/article_generator/article.py` replace the whole `write_article` function with:

```python
def render_article(
    pub_date: date,
    title: str,
    description: str,
    tags: list[str],
    body: str,
    summary: str = "",
    issue_number: int | None = None,
    requested_by: str = "",
    model: str = "",
) -> str:
    tags_yaml = "[" + ", ".join(_yaml_str(t) for t in tags) + "]"
    summary_line = f"summary: {_yaml_str(summary)}\n" if summary else ""
    issue_line = f"issue: {issue_number}\n" if issue_number else ""
    requested_line = f"requestedBy: {_yaml_str(requested_by)}\n" if requested_by else ""
    model_line = f"model: {_yaml_str(model)}\n" if model else ""
    frontmatter = (
        "---\n"
        f"title: {_yaml_str(title)}\n"
        f"description: {_yaml_str(description)}\n"
        f"pubDate: {pub_date.isoformat()}\n"
        f"tags: {tags_yaml}\n"
        f"{summary_line}"
        f"{issue_line}"
        f"{requested_line}"
        f"{model_line}"
        "---\n\n"
    )
    return frontmatter + body.strip() + "\n"


def write_article(
    output_dir: str,
    pub_date: date,
    slug: str,
    title: str,
    description: str,
    tags: list[str],
    body: str,
    summary: str = "",
    issue_number: int | None = None,
    requested_by: str = "",
    model: str = "",
) -> str:
    content = render_article(
        pub_date=pub_date,
        title=title,
        description=description,
        tags=tags,
        body=body,
        summary=summary,
        issue_number=issue_number,
        requested_by=requested_by,
        model=model,
    )
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{pub_date.isoformat()}-{slug}.md"
    path.write_text(content, encoding="utf-8")
    return str(path)
```

- [ ] **Step 4: Run full test file to verify pass (including old write_article tests)**

```bash
.venv/bin/python -m pytest tests/test_article.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/article_generator/article.py tests/test_article.py
git commit -m "refactor: extract render_article from write_article"
```

---

### Task 5: LangGraph writer–reviewer graph

**Files:**
- Create: `generator/src/article_generator/graph.py`
- Test: `generator/tests/test_graph.py`

State semantics: `iteration` = completed writer passes. `MAX_REVIEW_ITERATIONS = 2` means initial write + at most 1 rewrite. A deterministic validation failure also consumes an iteration (it sends the draft back to the writer).

- [ ] **Step 1: Write failing tests**

Create `generator/tests/test_graph.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_graph.py -q
```

Expected: FAIL with `ModuleNotFoundError: article_generator.graph`.

- [ ] **Step 3: Implement the graph**

Create `generator/src/article_generator/graph.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_graph.py -q
```

Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add src/article_generator/graph.py tests/test_graph.py
git commit -m "feat: LangGraph writer-reviewer loop with deterministic validation gate"
```

---

### Task 6: Draft PR client

**Files:**
- Create: `generator/src/article_generator/github_drafts.py`
- Test: `generator/tests/test_github_drafts.py`

- [ ] **Step 1: Write failing tests**

Create `generator/tests/test_github_drafts.py`:

```python
"""Tests for the draft PR rescue client."""
import base64
from unittest.mock import MagicMock

import pytest

from article_generator.github_drafts import DraftsClient, DraftsError


def client():
    c = DraftsClient(repo="owner/repo", token="tok")
    c.session = MagicMock()
    ref = MagicMock(status_code=200)
    ref.json.return_value = {"object": {"sha": "abc123"}}
    c.session.get.return_value = ref
    branch = MagicMock(status_code=201)
    pr = MagicMock(status_code=201)
    pr.json.return_value = {"html_url": "https://github.com/owner/repo/pull/9"}
    c.session.post.side_effect = [branch, pr]
    c.session.put.return_value = MagicMock(status_code=201)
    return c


def test_create_draft_pr_creates_branch_file_and_pr():
    c = client()
    url = c.create_draft_pr(
        branch="draft/issue-5",
        path="site/src/content/blog/2026-06-11-tema.md",
        content="---\ntitle: x\n---\n\ncuerpo\n",
        title="draft: tema",
        body="Closes #5",
    )
    assert url == "https://github.com/owner/repo/pull/9"

    c.session.get.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/git/ref/heads/main"
    )
    branch_call = c.session.post.call_args_list[0]
    assert branch_call.args == ("https://api.github.com/repos/owner/repo/git/refs",)
    assert branch_call.kwargs["json"] == {"ref": "refs/heads/draft/issue-5", "sha": "abc123"}

    put_call = c.session.put.call_args
    assert put_call.args == (
        "https://api.github.com/repos/owner/repo/contents/site/src/content/blog/2026-06-11-tema.md",
    )
    sent = put_call.kwargs["json"]
    assert sent["branch"] == "draft/issue-5"
    assert base64.b64decode(sent["content"]).decode() == "---\ntitle: x\n---\n\ncuerpo\n"

    pr_call = c.session.post.call_args_list[1]
    assert pr_call.args == ("https://api.github.com/repos/owner/repo/pulls",)
    assert pr_call.kwargs["json"] == {
        "title": "draft: tema",
        "head": "draft/issue-5",
        "base": "main",
        "body": "Closes #5",
    }


def test_create_draft_pr_fails_clearly_when_branch_exists():
    c = client()
    c.session.post.side_effect = [MagicMock(status_code=422, text="Reference already exists")]
    with pytest.raises(DraftsError, match="draft/issue-5"):
        c.create_draft_pr(
            branch="draft/issue-5",
            path="p.md",
            content="x",
            title="t",
            body="b",
        )


def test_create_draft_pr_raises_on_ref_lookup_error():
    c = client()
    c.session.get.return_value = MagicMock(status_code=404, text="nope")
    with pytest.raises(DraftsError):
        c.create_draft_pr(branch="b", path="p.md", content="x", title="t", body="b")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_github_drafts.py -q
```

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `generator/src/article_generator/github_drafts.py`:

```python
"""Opens a pull request with a rejected article so a human can rescue it.

Uses the GitHub contents API instead of local git: the run must not leave
uncommitted files behind for the publish step, and merging the PR is the
human approval mechanism (merge = publish, close = discard).
"""
import base64

import requests


class DraftsError(Exception):
    pass


class DraftsClient:
    def __init__(self, repo: str, token: str):
        self.base = f"https://api.github.com/repos/{repo}"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _require(self, response, expected: tuple[int, ...], action: str) -> None:
        if response.status_code not in expected:
            raise DraftsError(
                f"Failed to {action}: GitHub API error {response.status_code}: "
                f"{response.text[:500]}"
            )

    def create_draft_pr(
        self, branch: str, path: str, content: str, title: str, body: str, base: str = "main"
    ) -> str:
        ref = self.session.get(f"{self.base}/git/ref/heads/{base}")
        self._require(ref, (200,), f"resolve {base} ref")
        sha = ref.json()["object"]["sha"]

        created = self.session.post(
            f"{self.base}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        if created.status_code == 422:
            raise DraftsError(
                f"Branch {branch} already exists; close or delete the previous draft PR first"
            )
        self._require(created, (201,), f"create branch {branch}")

        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        put = self.session.put(
            f"{self.base}/contents/{path}",
            json={"message": f"draft: {title}", "content": encoded, "branch": branch},
        )
        self._require(put, (201,), f"create {path} on {branch}")

        pr = self.session.post(
            f"{self.base}/pulls",
            json={"title": title, "head": branch, "base": base, "body": body},
        )
        self._require(pr, (201,), "open draft pull request")
        return pr.json()["html_url"]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_github_drafts.py -q
```

Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/article_generator/github_drafts.py tests/test_github_drafts.py
git commit -m "feat: draft PR client for human rescue of rejected articles"
```

---

### Task 7: Rewire `main.py` around the graph

**Files:**
- Modify: `generator/src/article_generator/main.py` (full rewrite below)
- Modify: `generator/src/article_generator/prompts.py` (delete `review_prompt`)
- Test: `generator/tests/test_main.py` (full rewrite below)

Behavior changes:
- `review_code()` dies; the graph replaces outline/article/review calls.
- Loop over up to `MAX_TOPICS_PER_RUN` topics: approved → publish and stop; rejected → draft PR + label, try next topic.
- Frontmatter `model` becomes `"<writer> + <reviewer> (reviewer)"`.
- Env: `WRITER_MODEL` (falls back to legacy `LLM_MODEL`, then `deepseek-v4-pro`), `REVIEWER_MODEL` (default `minimax-m3`), `MAX_REVIEW_ITERATIONS` (default 2), `MAX_TOPICS_PER_RUN` (default 2). Use `env.get("X") or default` — workflow vars that are unset arrive as empty strings.
- `validate_reference_urls` runs only on the publish path; a draft PR is reviewed by a human anyway.

- [ ] **Step 1: Rewrite the tests**

Replace the entire content of `generator/tests/test_main.py` with:

```python
"""Tests for the generation orchestration."""
from unittest.mock import MagicMock, patch

import pytest

from article_generator.main import run


@pytest.fixture(autouse=True)
def avoid_reference_network():
    with patch("article_generator.main.validate_reference_urls"):
        yield


def env():
    return {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_TOKEN": "tok",
        "LLM_BASE_URL": "https://llm.example/v1",
        "LLM_API_KEY": "k",
        "WRITER_MODEL": "writer-m",
        "REVIEWER_MODEL": "reviewer-m",
        "OUTPUT_DIR": "/tmp/out",
        "SITE_URL": "https://owner.github.io/repo",
    }


def topic_issue(number=5, title="Project Reactor"):
    return {
        "number": number,
        "title": title,
        "body": "no entendemos el paradigma",
        "created_at": "2026-06-01T00:00:00Z",
        "labels": [{"name": "topic"}, {"name": "java"}],
        "user": {"login": "jordi"},
    }


def graph_state(approved, body="palabra " * 1200, feedback=None):
    return {
        "approved": approved,
        "draft": body,
        "feedback": feedback or [],
        "outline": "outline",
        "iteration": 2,
        "valid": True,
        "topic": "Project Reactor",
        "notes": "no entendemos el paradigma",
    }


@patch("article_generator.main.write_article", return_value="/tmp/out/2026-06-10-project-reactor.md")
@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_approved_article_is_published_and_issue_closed(
    issues_cls, llm_cls, drafts_cls, build_graph, write
):
    issues = issues_cls.return_value
    issues.next_topic.return_value = topic_issue()
    graph = build_graph.return_value
    graph.invoke.return_value = graph_state(approved=True)
    llm_cls.return_value.generate_json.return_value = {
        "summary": "El TL;DR.",
        "tags": ["reactive", "java"],
    }

    assert run(env()) == 0

    kwargs = write.call_args.kwargs
    assert kwargs["slug"] == "project-reactor"
    assert kwargs["body"] == "palabra " * 1200
    assert kwargs["summary"] == "El TL;DR."
    assert kwargs["tags"] == ["java", "reactive"]
    assert kwargs["model"] == "writer-m + reviewer-m (reviewer)"
    assert kwargs["issue_number"] == 5
    assert kwargs["requested_by"] == "jordi"
    issues.close_with_comment.assert_called_once()
    comment = issues.close_with_comment.call_args.args[1]
    assert "https://owner.github.io/repo/blog/" in comment
    drafts_cls.return_value.create_draft_pr.assert_not_called()
    issues.next_topic.assert_called_once()


@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_two_models_and_max_iterations_from_env(issues_cls, llm_cls, drafts_cls, build_graph):
    issues_cls.return_value.next_topic.return_value = None
    e = env()
    e["MAX_REVIEW_ITERATIONS"] = "3"

    assert run(e) == 0

    models = [call.kwargs["model"] for call in llm_cls.call_args_list]
    assert models == ["writer-m", "reviewer-m"]
    assert build_graph.call_args.args[2] == 3


@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_writer_model_falls_back_to_legacy_llm_model(issues_cls, llm_cls, drafts_cls, build_graph):
    issues_cls.return_value.next_topic.return_value = None
    e = env()
    del e["WRITER_MODEL"]
    e["LLM_MODEL"] = "legacy-m"

    assert run(e) == 0

    assert llm_cls.call_args_list[0].kwargs["model"] == "legacy-m"


@patch("article_generator.main.write_article", return_value="/tmp/out/x.md")
@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_rejected_article_becomes_draft_pr_then_next_topic_published(
    issues_cls, llm_cls, drafts_cls, build_graph, write
):
    issues = issues_cls.return_value
    issues.next_topic.side_effect = [topic_issue(5), topic_issue(6, title="Kafka")]
    graph = build_graph.return_value
    graph.invoke.side_effect = [
        graph_state(approved=False, feedback=["[codigo] falta import"]),
        graph_state(approved=True),
    ]
    llm_cls.return_value.generate_json.return_value = {"summary": "s", "tags": []}
    drafts = drafts_cls.return_value
    drafts.create_draft_pr.return_value = "https://github.com/owner/repo/pull/9"

    assert run(env()) == 0

    kwargs = drafts.create_draft_pr.call_args.kwargs
    assert kwargs["branch"] == "draft/issue-5"
    assert kwargs["path"].startswith("site/src/content/blog/")
    assert kwargs["path"].endswith("-project-reactor.md")
    assert "Closes #5" in kwargs["body"]
    assert "[codigo] falta import" in kwargs["body"]
    assert "title: " in kwargs["content"]  # rendered frontmatter
    issues.add_label.assert_called_once_with(5, "needs-human-review")
    issues.close_with_comment.assert_called_once()  # only the published one (#6)
    assert write.call_args.kwargs["slug"] == "kafka"


@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_stops_after_max_topics_rejections(issues_cls, llm_cls, drafts_cls, build_graph):
    issues = issues_cls.return_value
    issues.next_topic.side_effect = [topic_issue(5), topic_issue(6), topic_issue(7)]
    build_graph.return_value.invoke.return_value = graph_state(approved=False)
    llm_cls.return_value.generate_json.return_value = {"summary": "", "tags": []}

    assert run(env()) == 0

    assert issues.next_topic.call_count == 2  # MAX_TOPICS_PER_RUN default
    assert drafts_cls.return_value.create_draft_pr.call_count == 2
    issues.close_with_comment.assert_not_called()


@patch("article_generator.main.write_article", return_value="/tmp/out/x.md")
@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_metadata_failure_falls_back_to_first_paragraph(
    issues_cls, llm_cls, drafts_cls, build_graph, write
):
    from article_generator.llm import LLMError

    issues_cls.return_value.next_topic.return_value = topic_issue()
    body = "Primer párrafo del artículo.\n\n" + "palabra " * 1200
    build_graph.return_value.invoke.return_value = graph_state(approved=True, body=body)
    llm_cls.return_value.generate_json.side_effect = LLMError("bad json")

    assert run(env()) == 0

    kwargs = write.call_args.kwargs
    assert kwargs["summary"] == ""
    assert kwargs["description"] == "Primer párrafo del artículo."
    assert kwargs["tags"] == ["java"]


@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_strips_issue_form_artifacts_from_notes(issues_cls, llm_cls, drafts_cls, build_graph):
    issue = topic_issue()
    issue["body"] = "### Notas de enfoque\n\n_No response_"
    issues = issues_cls.return_value
    issues.next_topic.return_value = issue
    graph = build_graph.return_value
    graph.invoke.return_value = graph_state(approved=True)
    llm_cls.return_value.generate_json.return_value = {"summary": "s", "tags": []}

    with patch("article_generator.main.write_article", return_value="/tmp/out/x.md"):
        run(env())

    state = graph.invoke.call_args.args[0]
    assert state["notes"] == ""


@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_skips_when_article_already_published_today(issues_cls, llm_cls, tmp_path):
    from datetime import date

    (tmp_path / f"{date.today().isoformat()}-cualquier-tema.md").write_text("x")
    e = env()
    e["OUTPUT_DIR"] = str(tmp_path)

    assert run(e) == 0

    issues_cls.return_value.next_topic.assert_not_called()


@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_exits_zero_when_no_topics(issues_cls, llm_cls, drafts_cls, build_graph):
    issues_cls.return_value.next_topic.return_value = None
    assert run(env()) == 0
    build_graph.return_value.invoke.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_main.py -q
```

Expected: FAIL (`ImportError`: `main` has no `build_graph`/`DraftsClient`).

- [ ] **Step 3: Rewrite main.py**

Replace the entire content of `generator/src/article_generator/main.py` with:

```python
"""Orchestrates one generation run: pick topic -> writer-reviewer graph -> publish.

An approved article is published directly. A rejected one becomes a draft
PR (merge = publish, close = discard) and the run moves on to the next
topic, up to MAX_TOPICS_PER_RUN.
"""
import os
import sys
from datetime import date
from pathlib import Path

from .article import (
    make_description,
    render_article,
    slugify,
    validate_reference_urls,
    write_article,
)
from .github_drafts import DraftsClient
from .github_issues import NEEDS_HUMAN_REVIEW_LABEL, SYSTEM_LABELS, IssuesClient
from .graph import build_graph, initial_state
from .llm import LLMClient, LLMError
from .prompts import SYSTEM_PROMPT, metadata_prompt

# Artifacts that GitHub issue forms inject into the body.
FORM_ARTIFACTS = ("### Notas de enfoque", "_No response_")


def clean_notes(body: str) -> str:
    for artifact in FORM_ARTIFACTS:
        body = body.replace(artifact, "")
    return body.strip()


def collect_metadata(llm: LLMClient, issue: dict, topic: str, body: str) -> tuple[str, list[str]]:
    """Summary and tags; issue labels first, LLM tags appended, deduped."""
    tags = [l["name"] for l in issue["labels"] if l["name"] not in SYSTEM_LABELS]
    summary = ""
    try:
        meta = llm.generate_json(SYSTEM_PROMPT, metadata_prompt(topic, body))
        if isinstance(meta.get("summary"), str):
            summary = meta["summary"].strip()
        if isinstance(meta.get("tags"), list):
            for tag in meta["tags"]:
                tag = str(tag).strip().lower()
                if tag and tag not in tags:
                    tags.append(tag)
    except LLMError as exc:
        print(f"Metadata generation failed ({exc}); falling back to defaults.")
    return summary, tags


def publish(issues, writer, issue, body, output_dir, site_url, today, model_stamp) -> None:
    topic = issue["title"]
    validate_reference_urls(body)
    summary, tags = collect_metadata(writer, issue, topic, body)
    slug = slugify(topic)
    path = write_article(
        output_dir=output_dir,
        pub_date=today,
        slug=slug,
        title=topic,
        description=summary or make_description(body),
        tags=tags,
        body=body,
        summary=summary,
        issue_number=issue["number"],
        requested_by=(issue.get("user") or {}).get("login", ""),
        model=model_stamp,
    )
    print(f"Article written: {path}")
    link = f"{site_url}/blog/{today.isoformat()}-{slug}/" if site_url else path
    issues.close_with_comment(issue["number"], f"Publicado: {link}")
    print(f"Issue #{issue['number']} closed.")


def open_draft_pr(drafts, issues, writer, issue, body, feedback, today, model_stamp) -> None:
    topic = issue["title"]
    summary, tags = collect_metadata(writer, issue, topic, body)
    slug = slugify(topic)
    content = render_article(
        pub_date=today,
        title=topic,
        description=summary or make_description(body),
        tags=tags,
        body=body,
        summary=summary,
        issue_number=issue["number"],
        requested_by=(issue.get("user") or {}).get("login", ""),
        model=model_stamp,
    )
    issues_list = "\n".join(f"- {item}" for item in feedback) or "- (sin detalle)"
    pr_body = (
        f"Closes #{issue['number']}\n\n"
        f"El revisor (`{model_stamp}`) no aprobó el artículo. Defectos pendientes:\n\n"
        f"{issues_list}\n\n"
        "**Merge** = publicar tal cual (el deploy se dispara con el push a main). "
        "**Cerrar el PR** = descartar el borrador."
    )
    url = drafts.create_draft_pr(
        branch=f"draft/issue-{issue['number']}",
        path=f"site/src/content/blog/{today.isoformat()}-{slug}.md",
        content=content,
        title=f"draft: {topic}",
        body=pr_body,
    )
    issues.add_label(issue["number"], NEEDS_HUMAN_REVIEW_LABEL)
    print(f"Draft PR opened for issue #{issue['number']}: {url}")


def run(env: dict) -> int:
    output_dir = env.get("OUTPUT_DIR", "site/src/content/blog")
    today = date.today()

    # One article per day, even if the workflow is dispatched again.
    existing = list(Path(output_dir).glob(f"{today.isoformat()}-*.md"))
    if existing:
        print(f"Already published today: {existing[0].name}. Nothing to do.")
        return 0

    issues = IssuesClient(repo=env["GITHUB_REPOSITORY"], token=env["GITHUB_TOKEN"])
    drafts = DraftsClient(repo=env["GITHUB_REPOSITORY"], token=env["GITHUB_TOKEN"])
    site_url = env.get("SITE_URL", "").rstrip("/")

    # Unset workflow vars arrive as empty strings, hence `or` over defaults.
    writer_model = env.get("WRITER_MODEL") or env.get("LLM_MODEL") or "deepseek-v4-pro"
    reviewer_model = env.get("REVIEWER_MODEL") or "minimax-m3"
    max_iterations = int(env.get("MAX_REVIEW_ITERATIONS") or 2)
    max_topics = int(env.get("MAX_TOPICS_PER_RUN") or 2)

    writer = LLMClient(base_url=env["LLM_BASE_URL"], api_key=env["LLM_API_KEY"], model=writer_model)
    reviewer = LLMClient(base_url=env["LLM_BASE_URL"], api_key=env["LLM_API_KEY"], model=reviewer_model)
    graph = build_graph(writer, reviewer, max_iterations)
    model_stamp = f"{writer_model} + {reviewer_model} (reviewer)"

    for _ in range(max_topics):
        issue = issues.next_topic()
        if issue is None:
            print("No pending topics; nothing to publish.")
            return 0

        topic = issue["title"]
        notes = clean_notes(issue.get("body") or "")
        print(f"Generating article for issue #{issue['number']}: {topic}")

        state = graph.invoke(initial_state(topic, notes))

        if state["approved"]:
            publish(issues, writer, issue, state["draft"], output_dir, site_url, today, model_stamp)
            return 0

        print(f"Reviewer did not approve issue #{issue['number']}; opening draft PR.")
        open_draft_pr(drafts, issues, writer, issue, state["draft"], state["feedback"], today, model_stamp)

    print("No topic was approved this run.")
    return 0


def main() -> None:
    sys.exit(run(dict(os.environ)))
```

- [ ] **Step 4: Delete the obsolete review prompt**

In `generator/src/article_generator/prompts.py` delete the whole `review_prompt` function (lines starting at `def review_prompt(body: str) -> str:` through the end of its docstring/return, i.e. the block ending with `Sin explicaciones ni comentarios sobre lo corregido."""`).

- [ ] **Step 5: Run the full suite**

```bash
.venv/bin/python -m pytest -q
```

Expected: ALL PASS. If `test_prompts.py` had a test referencing `review_prompt`, delete that test.

- [ ] **Step 6: Commit**

```bash
git add src/article_generator/main.py src/article_generator/prompts.py tests/test_main.py tests/test_prompts.py
git commit -m "feat: orchestrate generation through writer-reviewer graph with draft PR rescue"
```

---

### Task 8: Workflow and repo variables

**Files:**
- Modify: `.github/workflows/generate.yml`
- No change: `.github/workflows/deploy.yml` (already triggers on `push` to main; a human merge fires it)

- [ ] **Step 1: Update generate.yml permissions**

```yaml
permissions:
  contents: write
  issues: write
  pull-requests: write
```

- [ ] **Step 2: Update generate.yml env block**

Replace the `LLM_MODEL` line in the "Generate article" step env with:

```yaml
          WRITER_MODEL: ${{ vars.WRITER_MODEL }}
          REVIEWER_MODEL: ${{ vars.REVIEWER_MODEL }}
          MAX_REVIEW_ITERATIONS: ${{ vars.MAX_REVIEW_ITERATIONS }}
          MAX_TOPICS_PER_RUN: ${{ vars.MAX_TOPICS_PER_RUN }}
```

(`LLM_BASE_URL`, `LLM_API_KEY` and the rest stay as they are. Unset vars arrive empty; the code defaults handle them.)

- [ ] **Step 3: Set repo variables** (run from repo root; needs network/auth)

```bash
gh variable set WRITER_MODEL --body "deepseek-v4-pro"
gh variable set REVIEWER_MODEL --body "minimax-m3"
gh variable delete LLM_MODEL
```

Expected: `gh variable list` shows WRITER_MODEL and REVIEWER_MODEL; LLM_MODEL gone.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/generate.yml
git commit -m "ci: writer/reviewer model vars and PR permission for draft rescue"
```

---

### Task 9: Verification and smoke test

- [ ] **Step 1: Full suite + import check**

```bash
cd generator
.venv/bin/python -m pytest -q
.venv/bin/python -c "from article_generator.main import run; from article_generator.graph import build_graph; print('ok')"
```

Expected: all tests pass, `ok`.

- [ ] **Step 2: Push and watch CI**

```bash
git push
gh run watch
```

Expected: CI green (generator + site jobs).

- [ ] **Step 3: Manual smoke test (needs a pending `topic` issue and no article published today)**

```bash
gh workflow run "Generate daily article"
gh run watch
```

Expected: either an article commit (approved) or a `draft/issue-N` PR with the reviewer report (rejected). Check the run logs for the iteration messages.

- [ ] **Step 4: Verify the label exists** (triage creates it via `ensure_system_labels`, or create it now)

```bash
gh label list | grep needs-human-review || gh label create needs-human-review --color e99695 --description "El revisor IA no aprobó el borrador; pendiente de humano"
```
