"""Tests for the review orchestration."""
from unittest.mock import MagicMock, patch

import pytest

from article_generator.review import run


def env(pr_number=9):
    return {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_TOKEN": "tok",
        "LLM_BASE_URL": "https://llm.example/v1",
        "LLM_API_KEY": "k",
        "LLM_REVIEWER_MODEL": "reviewer-m",
        "PR_NUMBER": str(pr_number),
        "SITE_URL": "https://owner.github.io/repo",
    }


ARTICLE_BODY = (
    "## Contexto\n\n" + "palabra " * 200
    + "\n\n## Concepto\n\n" + "palabra " * 200
    + "\n\n## Profundidad\n\n" + "palabra " * 200
    + "\n\n## Ejemplos\n\n" + "palabra " * 200
    + "\n\n## Trampas\n\n" + "palabra " * 200
    + "\n\n## Para saber más\n\n"
    + "- [Docs](https://example.com/a)\n"
    + "- [Spec](https://example.com/b)\n"
    + "- [Blog](https://example.com/c)\n"
)

PATH = "site/src/content/blog/2026-06-11-vistas-materializadas-en-snowflake.md"


@patch("article_generator.review.DraftsClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_approved_auto_merges(issues_cls, llm_cls, drafts_cls):
    pr = {
        "body": "Closes #5",
        "head": {"ref": "article/issue-5"},
        "title": "article: Vistas materializadas en Snowflake",
    }
    drafts = drafts_cls.return_value
    drafts.get_pr.return_value = pr
    drafts.get_article_path.return_value = PATH
    drafts.read_file.return_value = ARTICLE_BODY

    reviewer = llm_cls.return_value
    reviewer.generate_json.return_value = {"approved": True, "issues": []}

    assert run(env()) == 0

    drafts.merge_pr.assert_called_once_with(9)
    issues_cls.return_value.close_with_comment.assert_called_once()


@patch("article_generator.review.DraftsClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_rejected_then_fixed_auto_merges(issues_cls, llm_cls, drafts_cls):
    pr = {
        "body": "Closes #5",
        "head": {"ref": "article/issue-5"},
        "title": "article: Vistas materializadas en Snowflake",
    }
    drafts = drafts_cls.return_value
    drafts.get_pr.return_value = pr
    drafts.get_article_path.return_value = PATH
    drafts.read_file.return_value = ARTICLE_BODY

    reviewer = llm_cls.return_value
    reviewer.generate_json.return_value = {
        "approved": False,
        "issues": [{"category": "codigo", "detail": "falta import de Flux"}],
    }
    reviewer.generate.return_value = ARTICLE_BODY

    with patch("article_generator.review.validate_body"):
        assert run(env()) == 0

    drafts.update_file.assert_called_once_with(
        "article/issue-5", PATH, ARTICLE_BODY, "fix: address review feedback"
    )
    drafts.merge_pr.assert_called_once_with(9)


@patch("article_generator.review.DraftsClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_rejected_fix_fails_validation_needs_human(issues_cls, llm_cls, drafts_cls):
    from article_generator.article import ValidationError

    pr = {
        "body": "Closes #5",
        "head": {"ref": "article/issue-5"},
        "title": "article: Vistas materializadas en Snowflake",
    }
    drafts = drafts_cls.return_value
    drafts.get_pr.return_value = pr
    drafts.get_article_path.return_value = PATH
    drafts.read_file.return_value = ARTICLE_BODY

    reviewer = llm_cls.return_value
    reviewer.generate_json.return_value = {
        "approved": False,
        "issues": [{"category": "rigor", "detail": "URL inventada"}],
    }
    reviewer.generate.return_value = "too short"

    with patch("article_generator.review.validate_body", side_effect=ValidationError("Body too short")):
        assert run(env()) == 0

    drafts.merge_pr.assert_not_called()
    issues_cls.return_value.add_label.assert_called_once_with(5, "needs-human-review")
    drafts.comment_on_pr.assert_called_once()


@patch("article_generator.review.DraftsClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_no_issue_number_still_merges(issues_cls, llm_cls, drafts_cls):
    pr = {
        "body": "Some description without Closes",
        "head": {"ref": "article/issue-5"},
        "title": "article: Vistas materializadas en Snowflake",
    }
    drafts = drafts_cls.return_value
    drafts.get_pr.return_value = pr
    drafts.get_article_path.return_value = PATH
    drafts.read_file.return_value = ARTICLE_BODY

    reviewer = llm_cls.return_value
    reviewer.generate_json.return_value = {"approved": True, "issues": []}

    assert run(env()) == 0

    drafts.merge_pr.assert_called_once_with(9)
    issues_cls.return_value.close_with_comment.assert_not_called()