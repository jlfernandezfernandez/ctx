"""Tests for article slugging, validation, description and file writing."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from article_generator.article import (
    ValidationError,
    make_description,
    slugify,
    validate_body,
    validate_reference_urls,
    write_article,
)


def valid_body() -> str:
    sections = [
        "Contexto",
        "Concepto central",
        "En profundidad",
        "Ejemplos de código",
        "Trampas comunes",
    ]
    body = "\n\n".join(f"## {title}\n\n" + "palabra " * 220 for title in sections)
    references = "\n".join(
        f"{i}. [Fuente {i}](https://example.com/{i})" for i in range(1, 4)
    )
    return body + "\n\n## Para saber más\n\n" + references


def test_slugify_normalizes_accents_and_symbols():
    assert slugify("Vistas materializadas en Snowflake: ¿cuándo?") == "vistas-materializadas-en-snowflake-cuando"


def test_slugify_collapses_dashes():
    assert slugify("Kafka  --  sin ZooKeeper") == "kafka-sin-zookeeper"


def test_validate_body_accepts_long_body():
    validate_body(valid_body())


def test_validate_body_rejects_short_body():
    with pytest.raises(ValidationError, match="short"):
        validate_body("demasiado corto")


def test_validate_body_rejects_leftover_frontmatter():
    with pytest.raises(ValidationError, match="frontmatter"):
        validate_body("---\ntitle: x\n---\n" + valid_body())


def test_validate_body_rejects_h1():
    with pytest.raises(ValidationError, match="H1"):
        validate_body("# Título\n\n" + valid_body())


def test_validate_body_rejects_numbered_h2():
    with pytest.raises(ValidationError, match="numbered"):
        validate_body(valid_body().replace("## Contexto", "## 1. Contexto"))


def test_validate_body_rejects_missing_section():
    with pytest.raises(ValidationError, match="exactly 6"):
        validate_body(valid_body().replace("## Trampas comunes", "### Trampas comunes"))


def test_validate_body_ignores_headings_inside_code_fences():
    code = "```bash\n# instalar dependencias\npip install reactor\n## no es heading\n```"
    validate_body(valid_body().replace("## Para saber más", code + "\n\n## Para saber más"))


def test_validate_body_rejects_unclosed_code_fence():
    with pytest.raises(ValidationError, match="unclosed"):
        validate_body(valid_body() + "\n\n```python\nprint('hola')")


def test_validate_body_rejects_too_few_references():
    with pytest.raises(ValidationError, match="3 to 5"):
        validate_body(valid_body().replace("3. [Fuente 3](https://example.com/3)", ""))


def test_validate_body_rejects_vague_reference():
    with pytest.raises(ValidationError, match="vague"):
        validate_body(valid_body() + "\n\nDisponible en el blog oficial.")


def test_validate_reference_urls_accepts_reachable_sources(monkeypatch):
    response = SimpleNamespace(status_code=200)
    monkeypatch.setattr("article_generator.article.requests.head", lambda *args, **kwargs: response)
    validate_reference_urls(valid_body())


def test_validate_reference_urls_rejects_broken_source(monkeypatch):
    response = SimpleNamespace(status_code=404)
    monkeypatch.setattr("article_generator.article.requests.head", lambda *args, **kwargs: response)
    with pytest.raises(ValidationError, match="404"):
        validate_reference_urls(valid_body())


def test_validate_reference_urls_accepts_forbidden_but_reachable_source(monkeypatch):
    response = SimpleNamespace(status_code=403)
    monkeypatch.setattr("article_generator.article.requests.head", lambda *args, **kwargs: response)
    validate_reference_urls(valid_body())


def test_make_description_uses_first_paragraph_stripped():
    body = "## Intro\n\nEl **paradigma** reactivo cambia el modelo.\n\nMás texto."
    assert make_description(body) == "El paradigma reactivo cambia el modelo."


def test_make_description_truncates_at_200_chars():
    body = "x" * 500
    assert len(make_description(body)) <= 200


def test_write_article_includes_summary_when_given(tmp_path):
    path = write_article(
        output_dir=str(tmp_path),
        pub_date=date(2026, 6, 11),
        slug="x",
        title="X",
        description="d",
        tags=[],
        body="palabra " * 1200,
        summary="Resumen en\ndos líneas.",
    )
    content = Path(path).read_text(encoding="utf-8")
    assert 'summary: "Resumen en dos líneas."' in content


def test_write_article_omits_summary_line_when_empty(tmp_path):
    path = write_article(
        output_dir=str(tmp_path),
        pub_date=date(2026, 6, 11),
        slug="x",
        title="X",
        description="d",
        tags=[],
        body="palabra " * 1200,
    )
    assert "summary:" not in Path(path).read_text(encoding="utf-8")


def test_write_article_includes_issue_and_requester_when_given(tmp_path):
    path = write_article(
        output_dir=str(tmp_path),
        pub_date=date(2026, 6, 11),
        slug="x",
        title="X",
        description="d",
        tags=[],
        body="palabra " * 1200,
        issue_number=7,
        requested_by="jordi",
        model="deepseek-v4-pro",
    )
    content = Path(path).read_text(encoding="utf-8")
    assert "issue: 7" in content
    assert 'requestedBy: "jordi"' in content
    assert 'model: "deepseek-v4-pro"' in content


def test_write_article_omits_issue_and_requester_when_missing(tmp_path):
    path = write_article(
        output_dir=str(tmp_path),
        pub_date=date(2026, 6, 11),
        slug="x",
        title="X",
        description="d",
        tags=[],
        body="palabra " * 1200,
    )
    content = Path(path).read_text(encoding="utf-8")
    assert "issue:" not in content
    assert "requestedBy:" not in content


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
