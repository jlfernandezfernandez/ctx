"""Tests for article slugging, validation, description and rendering."""
from datetime import date

import pytest

from article_generator.article import (
    ValidationError,
    make_description,
    parse_title_and_tags,
    sign_reviewer,
    slugify,
    validate_body,
    validate_tags,
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


def test_validate_body_accepts_short_valid_markdown():
    validate_body("## Una sección\n\nBreve y suficiente.")


def test_validate_body_rejects_leftover_frontmatter():
    with pytest.raises(ValidationError, match="frontmatter"):
        validate_body("---\ntitle: x\n---\n" + valid_body())


def test_validate_body_rejects_h1():
    with pytest.raises(ValidationError, match="H1"):
        validate_body("# Título\n\n" + valid_body())


def test_validate_body_accepts_any_useful_structure():
    validate_body("## Única sección\n\nContenido.")


def test_validate_body_ignores_headings_inside_code_fences():
    code = "```bash\n# instalar dependencias\npip install reactor\n## no es heading\n```"
    validate_body(valid_body().replace("## Para saber más", code + "\n\n## Para saber más"))


def test_validate_body_rejects_unclosed_code_fence():
    with pytest.raises(ValidationError, match="unclosed"):
        validate_body(valid_body() + "\n\n```python\nprint('hola')")


def test_validate_tags_accepts_only_canonical_tags():
    validate_tags(["java", "reactive"], ["java", "reactive", "kafka"])


def test_validate_tags_rejects_unknown_tags():
    with pytest.raises(ValidationError, match="unknown"):
        validate_tags(["inventado"], ["java"])


def test_validate_tags_rejects_more_than_three():
    with pytest.raises(ValidationError, match="more than 3"):
        validate_tags(["a", "b", "c", "d"], ["a", "b", "c", "d"])


def test_make_description_uses_first_paragraph_stripped():
    body = "## Intro\n\nEl **paradigma** reactivo cambia el modelo.\n\nMás texto."
    assert make_description(body) == "El paradigma reactivo cambia el modelo."


def test_make_description_truncates_at_200_chars():
    body = "x" * 500
    assert len(make_description(body)) <= 200


def test_render_article_returns_frontmatter_and_body():

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


def test_parse_title_and_tags_reads_frontmatter():
    content = (
        '---\ntitle: "Vistas materializadas en Snowflake"\ndate: 2026-06-11\n'
        'tags: ["snowflake", "sql"]\n---\n\n## Contexto\n\ncuerpo\n'
    )
    assert parse_title_and_tags(content) == (
        "Vistas materializadas en Snowflake", ["snowflake", "sql"]
    )


def test_parse_title_and_tags_without_frontmatter():
    assert parse_title_and_tags("## Contexto\n\ncuerpo\n") == ("", [])


def test_sign_reviewer_adds_line_before_closing():
    fm = '---\ntitle: "X"\nwriter: "writer-m"\n---\n\n'
    signed = sign_reviewer(fm, "reviewer-m")
    assert '\nreviewer: "reviewer-m"\n---\n' in signed


def test_sign_reviewer_is_idempotent():
    fm = '---\ntitle: "X"\nreviewer: "reviewer-m"\n---\n\n'
    assert sign_reviewer(fm, "reviewer-m") == fm
    assert sign_reviewer("", "reviewer-m") == ""
