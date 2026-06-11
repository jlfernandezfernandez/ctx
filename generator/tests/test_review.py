"""Tests for the reviewer orchestration."""
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


def article_pr():
    return {
        "body": "Closes #5",
        "head": {"ref": "article/issue-5"},
        "title": "article: Vistas materializadas en Snowflake",
    }


def clients(prs_cls, issue_pr=None):
    prs = prs_cls.return_value
    prs.get_pr.return_value = issue_pr or article_pr()
    prs.get_article_path.return_value = PATH
    prs.read_file.return_value = ARTICLE_BODY
    return prs


@patch("article_generator.review.PRClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_approved_merges_and_closes_issue(issues_cls, llm_cls, prs_cls):
    prs = clients(prs_cls)
    reviewer = llm_cls.return_value
    reviewer.generate_json.return_value = {"approved": True, "issues": []}

    assert run(env()) == 0

    prs.merge_pr.assert_called_once_with(9, branch="article/issue-5")
    issues_cls.return_value.close_with_comment.assert_called_once()


@patch("article_generator.review.PRClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_rejected_then_fix_approved_pushes_and_merges(issues_cls, llm_cls, prs_cls):
    prs = clients(prs_cls)
    reviewer = llm_cls.return_value
    reviewer.generate_json.side_effect = [
        {"approved": False, "issues": [{"category": "codigo", "detail": "falta import de Flux"}]},
        {"approved": True, "issues": []},
    ]
    reviewer.generate.return_value = ARTICLE_BODY

    with patch("article_generator.review.validate_body"):
        assert run(env()) == 0

    prs.update_file.assert_called_once_with(
        "article/issue-5", PATH, ARTICLE_BODY, "fix: address review feedback"
    )
    prs.merge_pr.assert_called_once_with(9, branch="article/issue-5")
    comment = issues_cls.return_value.close_with_comment.call_args.args[1]
    assert "con correcciones" in comment


@patch("article_generator.review.PRClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_fix_fails_validation_leaves_pr_open_with_comment(issues_cls, llm_cls, prs_cls):
    from article_generator.article import ValidationError

    prs = clients(prs_cls)
    reviewer = llm_cls.return_value
    reviewer.generate_json.return_value = {
        "approved": False,
        "issues": [{"category": "rigor", "detail": "URL inventada"}],
    }
    reviewer.generate.return_value = "too short"

    with patch("article_generator.review.validate_body", side_effect=ValidationError("Body too short")):
        assert run(env()) == 0

    prs.merge_pr.assert_not_called()
    prs.update_file.assert_not_called()
    issues_cls.return_value.close_with_comment.assert_not_called()
    comment = prs.comment_on_pr.call_args.args[1]
    assert "URL inventada" in comment
    assert "Body too short" in comment


@patch("article_generator.review.PRClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_fix_rejected_on_second_review_pushes_and_leaves_pr_open(issues_cls, llm_cls, prs_cls):
    prs = clients(prs_cls)
    reviewer = llm_cls.return_value
    reviewer.generate_json.side_effect = [
        {"approved": False, "issues": [{"category": "codigo", "detail": "falta import de Flux"}]},
        {"approved": False, "issues": [{"category": "rigor", "detail": "sigue citando una API inexistente"}]},
    ]
    reviewer.generate.return_value = ARTICLE_BODY

    with patch("article_generator.review.validate_body"):
        assert run(env()) == 0

    prs.update_file.assert_called_once()  # the human sees the best version
    prs.merge_pr.assert_not_called()
    comment = prs.comment_on_pr.call_args.args[1]
    assert "API inexistente" in comment


@patch("article_generator.review.PRClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_no_issue_number_still_merges(issues_cls, llm_cls, prs_cls):
    pr = article_pr()
    pr["body"] = "Some description without Closes"
    prs = clients(prs_cls, issue_pr=pr)
    reviewer = llm_cls.return_value
    reviewer.generate_json.return_value = {"approved": True, "issues": []}

    assert run(env()) == 0

    prs.merge_pr.assert_called_once_with(9, branch="article/issue-5")
    issues_cls.return_value.close_with_comment.assert_not_called()
