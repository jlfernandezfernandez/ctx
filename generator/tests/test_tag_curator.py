"""Tests for the tag taxonomy curator."""
import json
from unittest.mock import patch

import pytest

from article_generator import agents
from article_generator.llm import LLMError
from article_generator.agents.tag_curator import run

ARTICLE = """---
title: "Vistas materializadas en Snowflake"
description: "d"
date: 2026-06-11
tags: ["snowflake", "sql"]
---

## Contexto

cuerpo
"""


def env():
    return {
        "LLM_BASE_URL": "https://llm.example/v1",
        "LLM_API_KEY": "k",
        "LLM_TRIAGE_MODEL": "triage-m",
    }


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    blog = tmp_path / "blog"
    blog.mkdir()
    tags_file = tmp_path / "tags.json"
    monkeypatch.setattr(agents.tag_curator, "BLOG_DIR_PATH", blog)
    monkeypatch.setattr(agents.tag_curator, "TAGS_FILE_PATH", tags_file)
    return blog, tags_file


@patch("article_generator.agents.tag_curator.subprocess")
@patch("article_generator.agents.tag_curator.LLMClient")
def test_no_articles_skips_llm(llm_cls, subprocess_mod, workspace):
    assert run(env()) == 0

    llm_cls.assert_not_called()
    subprocess_mod.run.assert_not_called()


@patch("article_generator.agents.tag_curator.subprocess")
@patch("article_generator.agents.tag_curator.LLMClient")
def test_llm_error_is_not_fatal(llm_cls, subprocess_mod, workspace):
    blog, _ = workspace
    (blog / "a.md").write_text(ARTICLE, encoding="utf-8")
    llm_cls.return_value.generate_json.side_effect = LLMError("boom")

    assert run(env()) == 0

    subprocess_mod.run.assert_not_called()


@patch("article_generator.agents.tag_curator.subprocess")
@patch("article_generator.agents.tag_curator.LLMClient")
def test_invalid_response_is_not_fatal(llm_cls, subprocess_mod, workspace):
    blog, _ = workspace
    (blog / "a.md").write_text(ARTICLE, encoding="utf-8")
    llm_cls.return_value.generate_json.return_value = {"tags": "not-a-list"}

    assert run(env()) == 0

    subprocess_mod.run.assert_not_called()


@patch("article_generator.agents.tag_curator.subprocess")
@patch("article_generator.agents.tag_curator.LLMClient")
def test_unchanged_taxonomy_does_not_push(llm_cls, subprocess_mod, workspace):
    blog, tags_file = workspace
    (blog / "a.md").write_text(ARTICLE, encoding="utf-8")
    tags_file.write_text('["snowflake", "sql"]')
    llm_cls.return_value.generate_json.return_value = {"tags": ["sql", "snowflake"]}

    assert run(env()) == 0

    subprocess_mod.run.assert_not_called()


@patch("article_generator.agents.tag_curator.subprocess")
@patch("article_generator.agents.tag_curator.LLMClient")
def test_changed_taxonomy_writes_commits_and_pushes(llm_cls, subprocess_mod, workspace):
    blog, tags_file = workspace
    (blog / "a.md").write_text(ARTICLE, encoding="utf-8")
    tags_file.write_text('["snowflake", "sql", "kraft"]')
    # Duplicates and casing normalize away before comparing or writing.
    llm_cls.return_value.generate_json.return_value = {"tags": ["Snowflake", "sql", "sql"]}

    assert run(env()) == 0

    assert json.loads(tags_file.read_text()) == ["snowflake", "sql"]
    commands = [c.args[0] for c in subprocess_mod.run.call_args_list]
    assert ["git", "pull", "origin", "main", "--rebase"] in commands
    assert ["git", "push", "origin", "main"] in commands
