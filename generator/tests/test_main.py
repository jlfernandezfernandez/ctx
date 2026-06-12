"""Tests for the writer orchestration."""
from unittest.mock import patch

import pytest

from article_generator.agents.writer import run


@pytest.fixture(autouse=True)
def avoid_reference_network():
    with patch("article_generator.agents.writer.validate_body"):
        yield


def env():
    return {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_TOKEN": "tok",
        "LLM_BASE_URL": "https://llm.example/v1",
        "LLM_API_KEY": "k",
        "LLM_WRITER_MODEL": "writer-m",
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


def setup_github(github_cls, issue=None):
    github = github_cls.return_value
    github.next_topic.return_value = issue
    github.open_pr.return_value = ("https://github.com/owner/repo/pull/9", 9)
    return github


@patch("article_generator.agents.writer.LLMClient")
@patch("article_generator.agents.writer.GitHubClient")
def test_writer_generates_and_opens_pr(github_cls, llm_cls, tmp_path):
    github = setup_github(github_cls, topic_issue())
    writer = llm_cls.return_value
    writer.generate.side_effect = ["outline", "palabra " * 1200]
    writer.generate_json.return_value = {"summary": "El TL;DR.", "tags": ["reactive"]}
    output_file = tmp_path / "github_output"
    e = {**env(), "GITHUB_OUTPUT": str(output_file)}

    assert run(e) == 0

    assert writer.generate.call_count == 2  # outline + article
    github.open_pr.assert_called_once()
    kwargs = github.open_pr.call_args.kwargs
    assert kwargs["branch"] == "article/issue-5"
    assert kwargs["path"].startswith("site/src/content/blog/")
    assert "Closes #5" in kwargs["body"]
    assert "title: " in kwargs["content"]
    assert 'tags: ["reactive"]' in kwargs["content"]
    assert '"java"' not in kwargs["content"]
    assert "pr_number=9" in output_file.read_text()


@patch("article_generator.agents.writer.LLMClient")
@patch("article_generator.agents.writer.GitHubClient")
def test_writer_skips_topics_with_open_article_pr(github_cls, llm_cls):
    github = setup_github(github_cls)
    github.open_article_issue_numbers.return_value = {2}

    assert run(env()) == 0

    github.next_topic.assert_called_once_with(skip={2})


@patch("article_generator.agents.writer.LLMClient")
@patch("article_generator.agents.writer.GitHubClient")
def test_metadata_failure_falls_back_to_description(github_cls, llm_cls):
    from article_generator.llm import LLMError

    github = setup_github(github_cls, topic_issue())
    writer = llm_cls.return_value
    writer.generate.side_effect = ["outline", "palabra " * 1200]
    writer.generate_json.side_effect = LLMError("bad json")

    assert run(env()) == 0

    kwargs = github.open_pr.call_args.kwargs
    assert "content" in kwargs


@patch("article_generator.agents.writer.LLMClient")
@patch("article_generator.agents.writer.GitHubClient")
def test_run_exits_zero_when_no_topics(github_cls, llm_cls):
    setup_github(github_cls)
    assert run(env()) == 0
    llm_cls.return_value.generate.assert_not_called()


@patch("article_generator.agents.writer.LLMClient")
@patch("article_generator.agents.writer.GitHubClient")
def test_validation_failure_still_opens_pr(github_cls, llm_cls):
    from article_generator.article import ValidationError

    github = setup_github(github_cls, topic_issue())
    writer = llm_cls.return_value
    writer.generate.side_effect = ["outline", "palabra " * 1200]
    writer.generate_json.return_value = {"summary": "s", "tags": []}

    with patch("article_generator.agents.writer.validate_body", side_effect=ValidationError("Body too short")):
        assert run(env()) == 0

    github.open_pr.assert_called_once()
