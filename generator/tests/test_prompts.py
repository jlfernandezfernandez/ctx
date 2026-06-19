"""Tests for static system prompts and task prompt builders."""
from article_generator.agents.reviewer import reviewer_prompt
from article_generator.agents.writer import (
    SYSTEM_PROMPT,
    article_prompt,
    metadata_prompt,
    normalize_tags,
    rewrite_prompt,
)
from article_generator.prompt import load_system_prompt


def test_system_prompt_sets_role_and_language():
    assert "español" in SYSTEM_PROMPT.lower()


def test_system_prompts_are_loaded_verbatim():
    assert SYSTEM_PROMPT == load_system_prompt("writer")
    assert "{" not in load_system_prompt("triage")
    assert "{" not in load_system_prompt("reviewer")


def test_writer_selects_central_tags_and_can_create_one():
    prompt = metadata_prompt("MSAL", "cuerpo", ["agents", "java"])
    assert "Tags existentes para reutilizar" in prompt
    assert "agents" in prompt
    assert "ejes centrales" in SYSTEM_PROMPT
    assert "agradecería encontrar este artículo" in SYSTEM_PROMPT
    assert "como máximo un tag nuevo" in SYSTEM_PROMPT
    assert normalize_tags(["Auth", "auth", "OAuth", "agents"], ["agents"]) == ["auth", "agents"]


def test_article_prompt_includes_topic_and_notes():
    p = article_prompt("SSE", "lo usamos con agentes")
    assert "SSE" in p
    assert "lo usamos con agentes" in p


def test_reviewer_prompt_includes_article_and_json_contract():
    p = reviewer_prompt("Project Reactor", "cuerpo del articulo")
    assert "cuerpo del articulo" in p
    assert "Project Reactor" in p
    system = load_system_prompt("reviewer")
    assert '"issues"' in system
    assert "category" in system
    assert "blocking" in system
    assert "ronda anterior" not in p


def test_reviewer_prompt_includes_previous_feedback_on_later_rounds():
    p = reviewer_prompt("Project Reactor", "cuerpo", ["[codigo] falta import de Flux"])
    assert "ronda anterior" in p
    assert "falta import de Flux" in p


def test_rewrite_prompt_includes_draft_and_feedback():
    p = rewrite_prompt(
        "Project Reactor",
        "el borrador",
        ["[codigo] falta import de Flux", "[rigor] URL inventada"],
    )
    assert "el borrador" in p
    assert "falta import de Flux" in p
    assert "URL inventada" in p
