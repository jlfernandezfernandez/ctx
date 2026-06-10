# Daily Journal MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Daily Journal MVP: a nightly GitHub Action picks the next topic from GitHub Issues, generates a deep-dive Spanish article via an LLM (two-pass: outline → article), publishes it as markdown, and an Astro static site on GitHub Pages serves it.

**Architecture:** Python generator package (`generator/`) with an OpenAI-compatible LLM client, GitHub Issues client, prompt builders, and article writer/validator. Astro blog starter (`site/`) renders `site/src/content/blog/*.md`. Two workflows: `generate.yml` (cron Mon–Fri + manual) and `deploy.yml` (Pages deploy on push / after generate).

**Tech Stack:** Python 3.12 + requests + pytest (unittest.mock, no extra test deps). Astro blog starter + Shiki. GitHub Actions, GitHub Pages (public repo, free plan).

**Spec:** `docs/superpowers/specs/2026-06-10-daily-journal-mvp-design.md`

---

### Task 1: Generator package skeleton

**Files:**
- Create: `.gitignore`, `README.md`
- Create: `generator/pyproject.toml`
- Create: `generator/src/daily_journal_generator/__init__.py` (empty)
- Create: `generator/tests/__init__.py` (empty)

- [ ] **Step 1: Write `.gitignore`**

```gitignore
# Python
__pycache__/
*.egg-info/
.venv/
.pytest_cache/

# Node / Astro
node_modules/
site/dist/
.astro/

# Local secrets — never commit keys
.env
```

- [ ] **Step 2: Write `README.md`**

```markdown
# Daily Journal

Cada día laborable, un artículo técnico en profundidad (~15 min) sobre un tema propuesto por el equipo.

## Cómo funciona

1. Propón un tema: abre una issue con el label `topic` (el cuerpo admite notas de enfoque). Label `priority` salta la cola.
2. Cada noche (L–V) una GitHub Action genera el artículo con un LLM y lo publica en la web (GitHub Pages).
3. La issue se cierra con el link al artículo.

## Estructura

- `generator/` — generador Python (LLM agnóstico, API OpenAI-compatible)
- `site/` — web Astro (GitHub Pages)
- `.github/workflows/` — generación nocturna y deploy

## Configuración (Actions)

- Secret `LLM_API_KEY` — API key del proveedor LLM
- Variable `LLM_BASE_URL` — p. ej. `https://ollama.com/v1`
- Variable `LLM_MODEL` — p. ej. `gpt-oss:120b`

Cambiar de proveedor = cambiar esas tres. Nunca commitees keys; `.env` está en `.gitignore`.

## Desarrollo local

```bash
cd generator && pip install -e .[dev] && pytest
cd site && npm install && npm run dev
```
```

- [ ] **Step 3: Write `generator/pyproject.toml`**

```toml
[project]
name = "daily-journal-generator"
version = "0.1.0"
description = "Generates the daily deep-dive article from the topic queue"
requires-python = ">=3.11"
dependencies = ["requests>=2.31"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
daily-journal-generate = "daily_journal_generator.main:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

- [ ] **Step 4: Create empty `generator/src/daily_journal_generator/__init__.py` and `generator/tests/__init__.py`, install, verify pytest runs**

Run: `cd generator && python3 -m venv .venv && .venv/bin/pip install -e .[dev] && .venv/bin/pytest`
Expected: `no tests ran` (exit code 5 is fine at this point)

- [ ] **Step 5: Commit**

```bash
git add .gitignore README.md generator/
git commit -m "chore: scaffold generator package"
```

---

### Task 2: LLM client (OpenAI-compatible, provider-agnostic)

**Files:**
- Create: `generator/src/daily_journal_generator/llm.py`
- Test: `generator/tests/test_llm.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the OpenAI-compatible LLM client."""
from unittest.mock import patch, MagicMock

import pytest

from daily_journal_generator.llm import LLMClient, LLMError


def make_response(status=200, payload=None, text=""):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.text = text
    return resp


def client():
    return LLMClient(base_url="https://llm.example/v1/", api_key="k", model="m")


def test_generate_returns_message_content():
    payload = {"choices": [{"message": {"content": " hola "}}]}
    with patch("daily_journal_generator.llm.requests.post", return_value=make_response(payload=payload)) as post:
        assert client().generate("sys", "user") == "hola"
    args, kwargs = post.call_args
    assert args[0] == "https://llm.example/v1/chat/completions"
    assert kwargs["headers"]["Authorization"] == "Bearer k"
    assert kwargs["json"]["model"] == "m"
    assert kwargs["json"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]


def test_generate_raises_on_http_error():
    with patch("daily_journal_generator.llm.requests.post", return_value=make_response(status=500, text="boom")):
        with pytest.raises(LLMError, match="500"):
            client().generate("sys", "user")


def test_generate_raises_on_unexpected_shape():
    with patch("daily_journal_generator.llm.requests.post", return_value=make_response(payload={"oops": True})):
        with pytest.raises(LLMError):
            client().generate("sys", "user")


def test_generate_raises_on_empty_content():
    payload = {"choices": [{"message": {"content": "  "}}]}
    with patch("daily_journal_generator.llm.requests.post", return_value=make_response(payload=payload)):
        with pytest.raises(LLMError, match="empty"):
            client().generate("sys", "user")
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd generator && .venv/bin/pytest tests/test_llm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'daily_journal_generator.llm'`

- [ ] **Step 3: Implement `llm.py`**

```python
"""Minimal client for any OpenAI-compatible chat completions API.

Provider-agnostic on purpose: switching provider means changing
LLM_BASE_URL / LLM_API_KEY / LLM_MODEL, nothing else.
"""
import requests


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 600):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate(self, system: str, user: str) -> str:
        resp = requests.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
            },
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise LLMError(f"LLM API error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"Unexpected LLM response shape: {str(data)[:500]}") from exc
        if not content or not content.strip():
            raise LLMError("LLM returned empty content")
        return content.strip()
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd generator && .venv/bin/pytest tests/test_llm.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add generator/src/daily_journal_generator/llm.py generator/tests/test_llm.py
git commit -m "feat: add provider-agnostic LLM client"
```

---

### Task 3: GitHub Issues client (topic queue)

**Files:**
- Create: `generator/src/daily_journal_generator/github_issues.py`
- Test: `generator/tests/test_github_issues.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the topic queue backed by GitHub Issues."""
from unittest.mock import MagicMock

import pytest

from daily_journal_generator.github_issues import IssuesClient, GitHubError


def issue(number, created, labels, title="t"):
    return {
        "number": number,
        "title": title,
        "body": "notes",
        "created_at": created,
        "labels": [{"name": name} for name in labels],
    }


def client_with(issues_payload, status=200):
    c = IssuesClient(repo="owner/repo", token="tok")
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = issues_payload
    resp.text = "err"
    c.session = MagicMock()
    c.session.get.return_value = resp
    c.session.post.return_value = MagicMock(status_code=201)
    c.session.patch.return_value = MagicMock(status_code=200)
    return c


def test_next_topic_returns_oldest():
    c = client_with([
        issue(2, "2026-06-02T00:00:00Z", ["topic"]),
        issue(1, "2026-06-01T00:00:00Z", ["topic"]),
    ])
    assert c.next_topic()["number"] == 1


def test_next_topic_priority_jumps_queue():
    c = client_with([
        issue(1, "2026-06-01T00:00:00Z", ["topic"]),
        issue(2, "2026-06-02T00:00:00Z", ["topic", "priority"]),
    ])
    assert c.next_topic()["number"] == 2


def test_next_topic_none_when_empty():
    assert client_with([]).next_topic() is None


def test_next_topic_skips_pull_requests():
    pr = issue(3, "2026-05-01T00:00:00Z", ["topic"])
    pr["pull_request"] = {"url": "x"}
    c = client_with([pr, issue(1, "2026-06-01T00:00:00Z", ["topic"])])
    assert c.next_topic()["number"] == 1


def test_next_topic_raises_on_api_error():
    with pytest.raises(GitHubError):
        client_with([], status=500).next_topic()


def test_close_with_comment_comments_then_closes():
    c = client_with([])
    c.close_with_comment(7, "done")
    c.session.post.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/issues/7/comments",
        json={"body": "done"},
    )
    c.session.patch.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/issues/7",
        json={"state": "closed"},
    )
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd generator && .venv/bin/pytest tests/test_github_issues.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `github_issues.py`**

```python
"""Topic queue backed by GitHub Issues.

An open issue labeled `topic` is a pending topic. `priority` jumps the
queue. Closing the issue with a link marks it published.
"""
import requests

TOPIC_LABEL = "topic"
PRIORITY_LABEL = "priority"


class GitHubError(Exception):
    pass


class IssuesClient:
    def __init__(self, repo: str, token: str):
        self.base = f"https://api.github.com/repos/{repo}"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        })

    def next_topic(self) -> dict | None:
        resp = self.session.get(
            f"{self.base}/issues",
            params={"state": "open", "labels": TOPIC_LABEL, "per_page": 100},
        )
        if resp.status_code != 200:
            raise GitHubError(f"GitHub API error {resp.status_code}: {resp.text[:500]}")
        issues = [i for i in resp.json() if "pull_request" not in i]
        if not issues:
            return None
        priority = [
            i for i in issues
            if any(l["name"] == PRIORITY_LABEL for l in i["labels"])
        ]
        pool = priority or issues
        return min(pool, key=lambda i: i["created_at"])

    def close_with_comment(self, number: int, comment: str) -> None:
        resp = self.session.post(f"{self.base}/issues/{number}/comments", json={"body": comment})
        if resp.status_code not in (200, 201):
            raise GitHubError(f"Failed to comment on issue #{number}: {resp.status_code}")
        resp = self.session.patch(f"{self.base}/issues/{number}", json={"state": "closed"})
        if resp.status_code != 200:
            raise GitHubError(f"Failed to close issue #{number}: {resp.status_code}")
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd generator && .venv/bin/pytest tests/test_github_issues.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add generator/src/daily_journal_generator/github_issues.py generator/tests/test_github_issues.py
git commit -m "feat: add GitHub Issues topic queue client"
```

---

### Task 4: Prompt builders (two-pass, Spanish)

**Files:**
- Create: `generator/src/daily_journal_generator/prompts.py`
- Test: `generator/tests/test_prompts.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for prompt builders."""
from daily_journal_generator.prompts import SYSTEM_PROMPT, outline_prompt, article_prompt


def test_system_prompt_sets_role_and_language():
    assert "español" in SYSTEM_PROMPT.lower()


def test_outline_prompt_includes_topic_and_notes():
    p = outline_prompt("Project Reactor", "no entendemos el paradigma")
    assert "Project Reactor" in p
    assert "no entendemos el paradigma" in p


def test_outline_prompt_omits_notes_section_when_empty():
    p = outline_prompt("Project Reactor", "")
    assert "Notas del equipo" not in p


def test_article_prompt_includes_outline_topic_and_notes():
    p = article_prompt("SSE", "lo usamos con agentes", "1. Intro\n2. Detalle")
    assert "SSE" in p
    assert "lo usamos con agentes" in p
    assert "1. Intro" in p
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd generator && .venv/bin/pytest tests/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `prompts.py`**

```python
"""Prompt builders for the two-pass article generation.

Pass 1 (outline) keeps long articles structured; single-pass long-form
output tends to lose structure and produce generic examples.
"""

SYSTEM_PROMPT = """Eres un ingeniero de software senior que escribe artículos técnicos \
en profundidad para un equipo de desarrollo experimentado pero nuevo en cada tema.

Reglas:
- Escribes en español, con los términos técnicos en inglés (no traduzcas \
"backpressure", "event loop", "consumer group", etc.).
- Partes de cero: el lector no conoce el tema, pero es un ingeniero competente.
- Llegas a profundidad real, más allá de una newsletter generalista: internals, \
trade-offs, comparativas y casos límite.
- Todos los ejemplos de código son completos y ejecutables, no pseudocódigo.
- Tono directo y claro, sin relleno ni marketing."""

ARTICLE_STRUCTURE = """1. Contexto: qué problema existe y por qué este tema importa (desde cero).
2. Concepto central: la idea clave explicada con precisión.
3. En profundidad: internals, trade-offs, comparativas (lo que una newsletter no cuenta).
4. Ejemplos de código ejecutables, comentados, de menos a más complejo.
5. Trampas comunes: errores reales que comete la gente y cómo evitarlos.
6. Para saber más: 3-5 referencias concretas (docs oficiales, papers, posts de calidad)."""


def outline_prompt(topic: str, notes: str) -> str:
    notes_block = f"\n\nNotas del equipo sobre el enfoque deseado:\n{notes}" if notes.strip() else ""
    return f"""Diseña el esquema de un artículo técnico de ~3000 palabras sobre: {topic}{notes_block}

El artículo seguirá esta estructura:
{ARTICLE_STRUCTURE}

Devuelve SOLO el esquema: las secciones con 2-4 bullets cada una indicando qué \
cubrir, qué ejemplos de código concretos incluir y qué trampas mencionar."""


def article_prompt(topic: str, notes: str, outline: str) -> str:
    notes_block = f"\n\nNotas del equipo sobre el enfoque deseado:\n{notes}" if notes.strip() else ""
    return f"""Escribe el artículo completo sobre: {topic}{notes_block}

Sigue fielmente este esquema:
{outline}

Requisitos:
- Entre 2500 y 3500 palabras (~15 minutos de lectura).
- Markdown puro: títulos con ##, código en bloques con su lenguaje (```java, ```python...).
- NO incluyas frontmatter YAML ni el título principal: empieza directamente por la \
primera sección con ##.
- Código completo y ejecutable, con comentarios donde aporten.

Devuelve SOLO el cuerpo del artículo en markdown."""
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd generator && .venv/bin/pytest tests/test_prompts.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add generator/src/daily_journal_generator/prompts.py generator/tests/test_prompts.py
git commit -m "feat: add two-pass prompt builders"
```

---

### Task 5: Article writer and validation

**Files:**
- Create: `generator/src/daily_journal_generator/article.py`
- Test: `generator/tests/test_article.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for article slugging, validation, description and file writing."""
from datetime import date
from pathlib import Path

import pytest

from daily_journal_generator.article import (
    ValidationError,
    make_description,
    slugify,
    validate_body,
    write_article,
)


def test_slugify_normalizes_accents_and_symbols():
    assert slugify("Vistas materializadas en Snowflake: ¿cuándo?") == "vistas-materializadas-en-snowflake-cuando"


def test_slugify_collapses_dashes():
    assert slugify("Kafka  --  sin ZooKeeper") == "kafka-sin-zookeeper"


def test_validate_body_accepts_long_body():
    validate_body("palabra " * 1200)


def test_validate_body_rejects_short_body():
    with pytest.raises(ValidationError, match="short"):
        validate_body("demasiado corto")


def test_validate_body_rejects_leftover_frontmatter():
    with pytest.raises(ValidationError, match="frontmatter"):
        validate_body("---\ntitle: x\n---\n" + "palabra " * 1200)


def test_make_description_uses_first_paragraph_stripped():
    body = "## Intro\n\nEl **paradigma** reactivo cambia el modelo.\n\nMás texto."
    assert make_description(body) == "El paradigma reactivo cambia el modelo."


def test_make_description_truncates_at_200_chars():
    body = "x" * 500
    assert len(make_description(body)) <= 200


def test_write_article_creates_file_with_frontmatter(tmp_path):
    body = "palabra " * 1200
    path = write_article(
        output_dir=str(tmp_path),
        pub_date=date(2026, 6, 10),
        slug="project-reactor",
        title='El "paradigma" reactivo',
        description="Una intro.",
        tags=["java", "reactor"],
        body=body,
    )
    content = Path(path).read_text(encoding="utf-8")
    assert Path(path).name == "2026-06-10-project-reactor.md"
    assert content.startswith("---\n")
    assert 'title: "El \\"paradigma\\" reactivo"' in content
    assert "pubDate: 2026-06-10" in content
    assert 'tags: ["java", "reactor"]' in content
    assert content.rstrip().endswith("palabra")
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd generator && .venv/bin/pytest tests/test_article.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `article.py`**

```python
"""Builds, validates and writes the article markdown file.

Frontmatter is built programmatically (not by the LLM) so the Astro
content schema is always satisfied.
"""
import re
import unicodedata
from datetime import date
from pathlib import Path

MIN_WORDS = 1000  # target is 2500-3500; below 1000 means generation went wrong


class ValidationError(Exception):
    pass


def slugify(title: str) -> str:
    norm = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    norm = re.sub(r"[^a-z0-9]+", "-", norm.lower())
    return norm.strip("-")


def validate_body(body: str) -> None:
    if body.lstrip().startswith("---"):
        raise ValidationError("Body contains leftover frontmatter")
    words = len(body.split())
    if words < MIN_WORDS:
        raise ValidationError(f"Body too short: {words} words (min {MIN_WORDS})")


def make_description(body: str) -> str:
    for paragraph in body.split("\n\n"):
        text = paragraph.strip()
        if not text or text.startswith("#") or text.startswith("```"):
            continue
        text = re.sub(r"[*_`]", "", text)
        text = re.sub(r"\s+", " ", text)
        return text[:200].strip()
    return ""


def _yaml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_article(
    output_dir: str,
    pub_date: date,
    slug: str,
    title: str,
    description: str,
    tags: list[str],
    body: str,
) -> str:
    tags_yaml = "[" + ", ".join(_yaml_str(t) for t in tags) + "]"
    frontmatter = (
        "---\n"
        f"title: {_yaml_str(title)}\n"
        f"description: {_yaml_str(description)}\n"
        f"pubDate: {pub_date.isoformat()}\n"
        f"tags: {tags_yaml}\n"
        "---\n\n"
    )
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{pub_date.isoformat()}-{slug}.md"
    path.write_text(frontmatter + body.strip() + "\n", encoding="utf-8")
    return str(path)
```

- [ ] **Step 4: Run tests, verify they pass**

Run: `cd generator && .venv/bin/pytest tests/test_article.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add generator/src/daily_journal_generator/article.py generator/tests/test_article.py
git commit -m "feat: add article writer and validation"
```

---

### Task 6: Orchestration (`main`)

**Files:**
- Create: `generator/src/daily_journal_generator/main.py`
- Test: `generator/tests/test_main.py`

- [ ] **Step 1: Write the failing tests**

```python
"""Tests for the generation orchestration."""
from unittest.mock import MagicMock, patch

from daily_journal_generator.main import run


def env():
    return {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_TOKEN": "tok",
        "LLM_BASE_URL": "https://llm.example/v1",
        "LLM_API_KEY": "k",
        "LLM_MODEL": "m",
        "OUTPUT_DIR": "/tmp/out",
        "SITE_URL": "https://owner.github.io/repo",
    }


def topic_issue():
    return {
        "number": 5,
        "title": "Project Reactor",
        "body": "no entendemos el paradigma",
        "created_at": "2026-06-01T00:00:00Z",
        "labels": [{"name": "topic"}, {"name": "java"}],
    }


@patch("daily_journal_generator.main.write_article", return_value="/tmp/out/2026-06-10-project-reactor.md")
@patch("daily_journal_generator.main.validate_body")
@patch("daily_journal_generator.main.LLMClient")
@patch("daily_journal_generator.main.IssuesClient")
def test_run_generates_validates_writes_and_closes(issues_cls, llm_cls, validate, write):
    issues = issues_cls.return_value
    issues.next_topic.return_value = topic_issue()
    llm = llm_cls.return_value
    llm.generate.side_effect = ["the outline", "palabra " * 1200]

    assert run(env()) == 0

    assert llm.generate.call_count == 2
    validate.assert_called_once()
    write.assert_called_once()
    kwargs = write.call_args.kwargs
    assert kwargs["slug"] == "project-reactor"
    assert kwargs["tags"] == ["java"]  # topic/priority labels excluded
    issues.close_with_comment.assert_called_once()
    comment = issues.close_with_comment.call_args.args[1]
    assert "https://owner.github.io/repo/blog/2026-06-10-project-reactor/" in comment


@patch("daily_journal_generator.main.LLMClient")
@patch("daily_journal_generator.main.IssuesClient")
def test_run_exits_zero_when_no_topics(issues_cls, llm_cls):
    issues_cls.return_value.next_topic.return_value = None
    assert run(env()) == 0
    llm_cls.return_value.generate.assert_not_called()


@patch("daily_journal_generator.main.write_article")
@patch("daily_journal_generator.main.LLMClient")
@patch("daily_journal_generator.main.IssuesClient")
def test_run_does_not_close_issue_if_validation_fails(issues_cls, llm_cls, write):
    issues = issues_cls.return_value
    issues.next_topic.return_value = topic_issue()
    llm_cls.return_value.generate.side_effect = ["outline", "too short"]

    try:
        run(env())
        raised = False
    except Exception:
        raised = True

    assert raised
    write.assert_not_called()
    issues.close_with_comment.assert_not_called()
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `cd generator && .venv/bin/pytest tests/test_main.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `main.py`**

```python
"""Orchestrates one generation run: pick topic -> outline -> article -> publish."""
import os
import sys
from datetime import date

from .article import make_description, slugify, validate_body, write_article
from .github_issues import PRIORITY_LABEL, TOPIC_LABEL, IssuesClient
from .llm import LLMClient
from .prompts import SYSTEM_PROMPT, article_prompt, outline_prompt

QUEUE_LABELS = {TOPIC_LABEL, PRIORITY_LABEL}


def run(env: dict) -> int:
    issues = IssuesClient(repo=env["GITHUB_REPOSITORY"], token=env["GITHUB_TOKEN"])
    llm = LLMClient(
        base_url=env["LLM_BASE_URL"],
        api_key=env["LLM_API_KEY"],
        model=env["LLM_MODEL"],
    )
    output_dir = env.get("OUTPUT_DIR", "site/src/content/blog")
    site_url = env.get("SITE_URL", "").rstrip("/")

    issue = issues.next_topic()
    if issue is None:
        print("No pending topics; nothing to publish.")
        return 0

    topic = issue["title"]
    notes = issue.get("body") or ""
    print(f"Generating article for issue #{issue['number']}: {topic}")

    outline = llm.generate(SYSTEM_PROMPT, outline_prompt(topic, notes))
    body = llm.generate(SYSTEM_PROMPT, article_prompt(topic, notes, outline))
    validate_body(body)

    pub_date = date.today()
    slug = slugify(topic)
    tags = [l["name"] for l in issue["labels"] if l["name"] not in QUEUE_LABELS]
    path = write_article(
        output_dir=output_dir,
        pub_date=pub_date,
        slug=slug,
        title=topic,
        description=make_description(body),
        tags=tags,
        body=body,
    )
    print(f"Article written: {path}")

    if site_url:
        link = f"{site_url}/blog/{pub_date.isoformat()}-{slug}/"
    else:
        link = path
    issues.close_with_comment(issue["number"], f"Publicado: {link}")
    print(f"Issue #{issue['number']} closed.")
    return 0


def main() -> None:
    sys.exit(run(dict(os.environ)))
```

- [ ] **Step 4: Run the full generator test suite**

Run: `cd generator && .venv/bin/pytest -v`
Expected: all tests pass (Tasks 2-6)

- [ ] **Step 5: Commit**

```bash
git add generator/src/daily_journal_generator/main.py generator/tests/test_main.py
git commit -m "feat: add generation orchestration entrypoint"
```

---

### Task 7: Astro site from blog starter

**Files:**
- Create: `site/` (scaffolded by `npm create astro` with the official blog template)
- Modify: `site/astro.config.mjs`, `site/src/consts.ts`, `site/src/content.config.ts` (or `src/content/config.ts` depending on starter version), homepage and header components
- Delete: starter placeholder posts

- [ ] **Step 1: Scaffold the starter**

Run from repo root:
```bash
npm create astro@latest site -- --template blog --no-install --no-git --yes
cd site && npm install
```
Expected: `site/` exists, `npm install` succeeds.

- [ ] **Step 2: Configure site + base for GitHub Pages project site**

In `site/astro.config.mjs` (adjust OWNER at execution time from `gh api user -q .login`):

```js
export default defineConfig({
  site: 'https://OWNER.github.io',
  base: '/daily-journal',
  integrations: [mdx(), sitemap()],
});
```

**Important:** with a non-root `base`, every internal `href`/`src` in the starter (header links, post lists, images) must be prefixed. Sweep all components/pages for `href="/..."` and replace with `` href={`${import.meta.env.BASE_URL}/...`} `` (or a small `withBase()` helper). Verify with the build in Step 6 — Astro warns on broken internal links is not guaranteed, so click through in preview.

- [ ] **Step 3: Add `tags` to the blog content schema**

In the starter's content config (`site/src/content.config.ts`), extend the schema:

```ts
schema: z.object({
  title: z.string(),
  description: z.string(),
  pubDate: z.coerce.date(),
  updatedDate: z.coerce.date().optional(),
  heroImage: z.string().optional(),
  tags: z.array(z.string()).default([]),
}),
```

- [ ] **Step 4: Spanish identity + homepage = today's article**

- `site/src/consts.ts`: `SITE_TITLE = 'Daily Journal'`, `SITE_DESCRIPTION = 'Cada día, un tema técnico en profundidad. Propuesto por el equipo, explicado desde cero.'`
- Homepage (`site/src/pages/index.astro`): sort posts by `pubDate` desc; render the newest post's title, description, date and a prominent link as "Artículo de hoy"; list the rest below as archive links. Reuse the starter's existing list markup — restyle minimally, do not redesign.
- Header nav: keep `Inicio` and `Archivo` (blog index). Remove "About" page or convert to a one-paragraph "Cómo funciona" page linking to the GitHub repo issues page for proposing topics.

- [ ] **Step 5: Remove placeholder posts, add welcome article**

Delete the starter's sample posts in `site/src/content/blog/`. Add `site/src/content/blog/2026-06-10-bienvenida.md`:

```markdown
---
title: "Cómo funciona Daily Journal"
description: "Un artículo técnico en profundidad cada día laborable, con temas propuestos por el equipo."
pubDate: 2026-06-10
tags: ["meta"]
---

Cada día laborable a primera hora se publica aquí un artículo técnico (~15 minutos de lectura) sobre un tema propuesto por el equipo: desde cero hasta los detalles que una newsletter generalista no cuenta, con ejemplos de código ejecutables.

## Proponer un tema

Abre una issue en el repositorio con el label `topic`. El cuerpo de la issue admite notas de enfoque ("no entendemos X, compáralo con Y"). El label `priority` salta la cola.

Cada noche, una GitHub Action coge el siguiente tema, genera el artículo y cierra la issue con el link.
```

(Note: the starter requires `heroImage`? If the starter schema made it optional per Step 3, plain posts work. If any layout component assumes `heroImage` exists, guard it with a conditional.)

- [ ] **Step 6: Build and verify**

Run: `cd site && npm run build && npm run preview`
Expected: build succeeds; preview at the `/daily-journal` base path shows homepage with the welcome article as "Artículo de hoy"; internal links work under the base path.

- [ ] **Step 7: Commit**

```bash
git add site/
git commit -m "feat: add Astro site from blog starter"
```

---

### Task 8: GitHub Actions workflows

**Files:**
- Create: `.github/workflows/generate.yml`
- Create: `.github/workflows/deploy.yml`

- [ ] **Step 1: Write `generate.yml`**

```yaml
name: Generate daily article

on:
  schedule:
    # 04:30 UTC Mon-Fri = 06:30 Madrid (summer) / 05:30 (winter)
    - cron: "30 4 * * 1-5"
  workflow_dispatch:

permissions:
  contents: write
  issues: write

concurrency:
  group: generate
  cancel-in-progress: false

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install generator
        run: pip install ./generator

      - name: Generate article
        env:
          LLM_BASE_URL: ${{ vars.LLM_BASE_URL }}
          LLM_MODEL: ${{ vars.LLM_MODEL }}
          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_REPOSITORY: ${{ github.repository }}
          OUTPUT_DIR: site/src/content/blog
          SITE_URL: https://${{ github.repository_owner }}.github.io/daily-journal
        run: daily-journal-generate

      - name: Commit and push article
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add site/src/content/blog
          if git diff --cached --quiet; then
            echo "Nothing to publish."
          else
            git commit -m "chore: publish daily article"
            git push
          fi
```

- [ ] **Step 2: Write `deploy.yml`**

Pushes made with `GITHUB_TOKEN` do **not** trigger `push` workflows, so deploy also listens to `workflow_run` of the generate workflow.

```yaml
name: Deploy site

on:
  push:
    branches: [main]
  workflow_dispatch:
  workflow_run:
    workflows: ["Generate daily article"]
    types: [completed]

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: true

jobs:
  build:
    if: github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: withastro/action@v3
        with:
          path: ./site

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 3: Validate YAML locally**

Run: `python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('.github/workflows/*.yml')]" && echo OK`
Expected: `OK` (install pyyaml in the venv if needed)

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/
git commit -m "ci: add generate and deploy workflows"
```

---

### Task 9: GitHub repo setup and launch

**Files:** none (gh CLI operations)

- [ ] **Step 1: Verify gh auth and create public repo**

```bash
gh auth status
gh repo create daily-journal --public --source . --push
```
Expected: repo created under the authenticated user, `main` pushed. If a remote already exists, just `git push -u origin main`.

- [ ] **Step 2: Create labels**

```bash
gh label create topic --description "Tema pendiente para Daily Journal" --color 0E8A16
gh label create priority --description "Saltar la cola" --color D93F0B
```

- [ ] **Step 3: Enable Pages (workflow build) and set repo variables**

```bash
gh api repos/{owner}/daily-journal/pages -X POST -f build_type=workflow
gh variable set LLM_BASE_URL --body "https://ollama.com/v1"
gh variable set LLM_MODEL --body "gpt-oss:120b"
```
(Replace `{owner}` with the authenticated login. Model is a repo variable — change anytime without touching code.)

- [ ] **Step 4: Seed topic issues**

```bash
gh issue create --title "Project Reactor: el paradigma reactivo en Java" \
  --label topic --label java \
  --body "No entendemos el paradigma reactivo. Partir de código imperativo y compararlo. Qué es backpressure."
gh issue create --title "Novedades de Java 21 a 25" --label topic --label java \
  --body "Virtual threads, pattern matching, lo relevante para el día a día."
gh issue create --title "SSE vs HTTP clásico: streaming para agentes" --label topic \
  --body "Trabajamos con agentes. Cuándo SSE, cuándo websockets, cuándo polling."
gh issue create --title "Kafka sin ZooKeeper: KRaft" --label topic \
  --body "Qué cambia, por qué, y qué implica operacionalmente."
gh issue create --title "Vistas materializadas en Snowflake" --label topic --label sql \
  --body "Cuándo usarlas, costes, limitaciones frente a tablas dinámicas."
```

- [ ] **Step 5: Verify deploy workflow ran and site is live**

```bash
gh run list --workflow deploy.yml
gh run watch <run-id>
```
Expected: deploy green; site live at `https://<owner>.github.io/daily-journal/` showing the welcome article.

- [ ] **Step 6: User adds the LLM key (only manual step)**

The user must run (key value never enters the repo or this session's files):
```
gh secret set LLM_API_KEY
```

- [ ] **Step 7: End-to-end test**

```bash
gh workflow run generate.yml
gh run watch <run-id>
```
Expected: generate green → article committed → deploy triggered via workflow_run → article visible on the site → topic issue closed with link.

---

## Verification checklist (maps to spec)

- [ ] Topic queue: issues with `topic`, `priority` jumps queue, PRs ignored — Task 3
- [ ] Two-pass generation, Spanish, fixed structure, notes injected — Tasks 4, 6
- [ ] Provider-agnostic LLM: base_url/key/model only — Task 2, repo vars in Task 9
- [ ] Validation prevents publishing garbage; issue stays open on failure — Tasks 5, 6
- [ ] No topics → exit 0, nothing published — Task 6
- [ ] Cron Mon-Fri + workflow_dispatch — Task 8
- [ ] Astro site, syntax highlight, homepage = today — Task 7
- [ ] Pages deploy on push and after generate (GITHUB_TOKEN push caveat) — Task 8
- [ ] Secrets only in Actions Secrets, `.env` gitignored — Tasks 1, 9
