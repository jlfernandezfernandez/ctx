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
