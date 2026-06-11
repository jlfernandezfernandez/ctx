"""Tests for the generation orchestration."""
from unittest.mock import MagicMock, patch

import pytest

from article_generator.main import run


@pytest.fixture(autouse=True)
def avoid_reference_network():
    with patch("article_generator.main.validate_body"):
        yield


def env():
    return {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_TOKEN": "tok",
        "LLM_BASE_URL": "https://llm.example/v1",
        "LLM_API_KEY": "k",
        "LLM_WRITER_MODEL": "writer-m",
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


@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_writer_generates_and_opens_pr(issues_cls, llm_cls, drafts_cls):
    issues = issues_cls.return_value
    issues.next_topic.return_value = topic_issue()
    writer = llm_cls.return_value
    writer.generate.side_effect = ["outline", "palabra " * 1200]
    writer.generate_json.return_value = {"summary": "El TL;DR.", "tags": ["reactive", "java"]}
    drafts = drafts_cls.return_value
    drafts.create_draft_pr.return_value = ("https://github.com/owner/repo/pull/9", 9)

    assert run(env()) == 0

    assert writer.generate.call_count == 2  # outline + article
    drafts.create_draft_pr.assert_called_once()
    kwargs = drafts.create_draft_pr.call_args.kwargs
    assert kwargs["branch"] == "article/issue-5"
    assert kwargs["path"].startswith("site/src/content/blog/")
    assert "Closes #5" in kwargs["body"]
    assert "title: " in kwargs["content"]
    issues.add_label.assert_any_call(5, "needs-review")
    issues.add_label.assert_any_call(9, "needs-review")


@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_metadata_failure_falls_back_to_description(issues_cls, llm_cls, drafts_cls):
    from article_generator.llm import LLMError

    issues = issues_cls.return_value
    issues.next_topic.return_value = topic_issue()
    writer = llm_cls.return_value
    writer.generate.side_effect = ["outline", "palabra " * 1200]
    writer.generate_json.side_effect = LLMError("bad json")
    drafts = drafts_cls.return_value
    drafts.create_draft_pr.return_value = ("https://github.com/owner/repo/pull/9", 9)

    assert run(env()) == 0

    kwargs = drafts.create_draft_pr.call_args.kwargs
    assert "content" in kwargs


@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_strips_issue_form_artifacts_from_notes(issues_cls, llm_cls, drafts_cls):
    issue = topic_issue()
    issue["body"] = "### Notas de enfoque\n\n_No response_"
    issues = issues_cls.return_value
    issues.next_topic.return_value = issue
    writer = llm_cls.return_value
    writer.generate.side_effect = ["outline", "palabra " * 1200]
    writer.generate_json.return_value = {"summary": "s", "tags": []}
    drafts = drafts_cls.return_value
    drafts.create_draft_pr.return_value = ("https://github.com/owner/repo/pull/9", 9)

    run(env())

    outline_prompt = writer.generate.call_args_list[0]
    assert "### Notas de enfoque" not in outline_prompt


@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_skips_when_article_already_published_today(issues_cls, llm_cls, tmp_path):
    from datetime import date

    (tmp_path / f"{date.today().isoformat()}-cualquier-tema.md").write_text("x")
    e = env()
    e["OUTPUT_DIR"] = str(tmp_path)

    assert run(e) == 0

    issues_cls.return_value.next_topic.assert_not_called()


@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_exits_zero_when_no_topics(issues_cls, llm_cls, drafts_cls):
    issues_cls.return_value.next_topic.return_value = None
    assert run(env()) == 0
    llm_cls.return_value.generate.assert_not_called()


@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_validation_failure_still_opens_pr(issues_cls, llm_cls, drafts_cls):
    from article_generator.article import ValidationError

    issues = issues_cls.return_value
    issues.next_topic.return_value = topic_issue()
    writer = llm_cls.return_value
    writer.generate.side_effect = ["outline", "palabra " * 1200]
    writer.generate_json.return_value = {"summary": "s", "tags": []}
    drafts = drafts_cls.return_value
    drafts.create_draft_pr.return_value = ("https://github.com/owner/repo/pull/9", 9)

    with patch("article_generator.main.validate_body", side_effect=ValidationError("Body too short")):
        assert run(env()) == 0

    drafts.create_draft_pr.assert_called_once()