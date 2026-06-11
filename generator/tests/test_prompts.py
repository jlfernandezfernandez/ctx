"""Tests for prompt builders."""
from article_generator.prompts import SYSTEM_PROMPT, outline_prompt, article_prompt


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


def test_reviewer_prompt_includes_article_and_json_contract():
    from article_generator.prompts import reviewer_prompt

    p = reviewer_prompt("Project Reactor", "cuerpo del articulo")
    assert "cuerpo del articulo" in p
    assert "Project Reactor" in p
    assert '"approved"' in p
    assert '"issues"' in p
    assert '"category"' in p
    assert '"blocking"' in p
    assert "ronda anterior" not in p


def test_reviewer_prompt_includes_previous_feedback_on_later_rounds():
    from article_generator.prompts import reviewer_prompt

    p = reviewer_prompt("Project Reactor", "cuerpo", ["[codigo] falta import de Flux"])
    assert "ronda anterior" in p
    assert "falta import de Flux" in p


def test_rewrite_prompt_includes_draft_and_feedback():
    from article_generator.prompts import rewrite_prompt

    p = rewrite_prompt(
        "Project Reactor",
        "el borrador",
        ["[codigo] falta import de Flux", "[rigor] URL inventada"],
    )
    assert "el borrador" in p
    assert "falta import de Flux" in p
    assert "URL inventada" in p
