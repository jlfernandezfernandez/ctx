"""Tests for article slugging, validation, description and rendering."""
from datetime import date

import pytest

from article_generator.article import (
    ValidationError,
    make_description,
    slugify,
    validate_body,
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


def test_make_description_uses_first_paragraph_stripped():
    body = "## Intro\n\nEl **paradigma** reactivo cambia el modelo.\n\nMás texto."
    assert make_description(body) == "El paradigma reactivo cambia el modelo."


def test_make_description_truncates_at_200_chars():
    body = "x" * 500
    assert len(make_description(body)) <= 200


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
        writer="deepseek-v4-pro",
    )
    assert content.startswith("---\n")
    assert 'title: "Project Reactor"' in content
    assert "date: 2026-06-11" in content
    assert 'writer: "deepseek-v4-pro"' in content
    assert content.endswith("## Sección\n\nTexto.\n")


def test_split_frontmatter_separates_block_and_body():
    from article_generator.article import split_frontmatter

    fm, body = split_frontmatter('---\ntitle: "X"\ndate: 2026-06-11\n---\n\n## Sección\n\nTexto.')
    assert fm == '---\ntitle: "X"\ndate: 2026-06-11\n---\n\n'
    assert body == "## Sección\n\nTexto."


def test_split_frontmatter_without_block_returns_body_untouched():
    from article_generator.article import split_frontmatter

    fm, body = split_frontmatter("## Sección\n\nTexto.")
    assert fm == ""
    assert body == "## Sección\n\nTexto."
