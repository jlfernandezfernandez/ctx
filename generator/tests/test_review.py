"""Tests for the writer-reviewer review loop."""
from unittest.mock import MagicMock, patch

import pytest

from article_generator.review import run


def env(pr_number=9, max_rounds=None):
    e = {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_TOKEN": "tok",
        "LLM_BASE_URL": "https://llm.example/v1",
        "LLM_API_KEY": "k",
        "LLM_REVIEWER_MODEL": "reviewer-m",
        "LLM_WRITER_MODEL": "writer-m",
        "PR_NUMBER": str(pr_number),
        "SITE_URL": "https://owner.github.io/repo",
    }
    if max_rounds is not None:
        e["MAX_REVIEW_ROUNDS"] = max_rounds
    return e


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

APPROVED = {"approved": True, "issues": []}


def blocking_issue(detail="falta import de Flux"):
    return {"category": "codigo", "blocking": True, "detail": detail}


def suggestion(detail="el ejemplo 2 sería más claro con records"):
    return {"category": "legibilidad", "blocking": False, "detail": detail}


def setup_pr(prs_cls, body="Closes #5"):
    prs = prs_cls.return_value
    prs.get_pr.return_value = {
        "body": body,
        "head": {"ref": "article/issue-5"},
        "title": "article: Vistas materializadas en Snowflake",
    }
    prs.get_article_path.return_value = PATH
    prs.read_file.return_value = ARTICLE_BODY
    return prs


def setup_llms(llm_cls, reports, fixes=()):
    """Side-effect both LLM clients: reviewer returns reports, writer returns fixes."""
    reviewer = MagicMock()
    reviewer.generate_json.side_effect = reports
    writer = MagicMock()
    writer.generate.side_effect = list(fixes)

    def by_model(base_url, api_key, model):
        return reviewer if model == "reviewer-m" else writer

    llm_cls.side_effect = by_model
    return reviewer, writer


@patch("article_generator.review.PRClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_approved_first_round_merges_and_closes_issue(issues_cls, llm_cls, prs_cls):
    prs = setup_pr(prs_cls)
    setup_llms(llm_cls, [APPROVED])

    assert run(env()) == 0

    prs.merge_pr.assert_called_once_with(9, branch="article/issue-5")
    prs.comment_on_pr.assert_not_called()
    prs.update_file.assert_not_called()
    closing = issues_cls.return_value.close_with_comment.call_args.args[1]
    assert closing.endswith("/blog/2026-06-11-vistas-materializadas-en-snowflake/")


@patch("article_generator.review.PRClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_suggestions_only_merge_with_comment(issues_cls, llm_cls, prs_cls):
    prs = setup_pr(prs_cls)
    setup_llms(llm_cls, [{"approved": False, "issues": [suggestion()]}])

    assert run(env()) == 0

    prs.merge_pr.assert_called_once_with(9, branch="article/issue-5")
    prs.update_file.assert_not_called()
    comment = prs.comment_on_pr.call_args.args[1]
    assert "sugerencias" in comment
    assert "records" in comment


@patch("article_generator.review.PRClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_blocking_defect_writer_fixes_then_merges(issues_cls, llm_cls, prs_cls):
    prs = setup_pr(prs_cls)
    reviewer, writer = setup_llms(
        llm_cls,
        reports=[{"approved": False, "issues": [blocking_issue()]}, APPROVED],
        fixes=[ARTICLE_BODY],
    )

    with patch("article_generator.review.validate_body"):
        assert run(env()) == 0

    writer.generate.assert_called_once()
    assert "falta import de Flux" in writer.generate.call_args.args[1]
    prs.update_file.assert_called_once_with(
        "article/issue-5", PATH, ARTICLE_BODY, "fix: review feedback (round 1)"
    )
    round_comment = prs.comment_on_pr.call_args_list[0].args[1]
    assert "Cambios solicitados (ronda 1)" in round_comment
    prs.merge_pr.assert_called_once_with(9, branch="article/issue-5")
    closing = issues_cls.return_value.close_with_comment.call_args.args[1]
    assert "con correcciones" in closing
    # Second review sees the previously reported defects.
    assert "falta import de Flux" in reviewer.generate_json.call_args.args[1]


@patch("article_generator.review.PRClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_round_budget_exhausted_leaves_pr_open(issues_cls, llm_cls, prs_cls):
    prs = setup_pr(prs_cls)
    rejected = {"approved": False, "issues": [blocking_issue("API inexistente")]}
    reviewer, writer = setup_llms(
        llm_cls,
        reports=[rejected, rejected, rejected],
        fixes=[ARTICLE_BODY, ARTICLE_BODY],
    )

    with patch("article_generator.review.validate_body"):
        assert run(env(max_rounds="2")) == 0

    assert writer.generate.call_count == 2  # the budget
    assert prs.update_file.call_count == 2  # human sees the best version
    prs.merge_pr.assert_not_called()
    issues_cls.return_value.close_with_comment.assert_not_called()
    final_comment = prs.comment_on_pr.call_args_list[-1].args[1]
    assert "sigue sin aprobar tras 2 correcciones" in final_comment
    assert "API inexistente" in final_comment


@patch("article_generator.review.PRClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_fix_breaking_structure_escalates(issues_cls, llm_cls, prs_cls):
    from article_generator.article import ValidationError

    prs = setup_pr(prs_cls)
    setup_llms(
        llm_cls,
        reports=[{"approved": False, "issues": [blocking_issue("URL inventada")]}],
        fixes=["too short"],
    )

    with patch("article_generator.review.validate_body", side_effect=ValidationError("Body too short")):
        assert run(env()) == 0

    prs.merge_pr.assert_not_called()
    prs.update_file.assert_not_called()
    final_comment = prs.comment_on_pr.call_args_list[-1].args[1]
    assert "URL inventada" in final_comment
    assert "Body too short" in final_comment


@patch("article_generator.review.PRClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_issue_without_blocking_flag_blocks(issues_cls, llm_cls, prs_cls):
    prs = setup_pr(prs_cls)
    rejected = {
        "approved": False,
        "issues": [{"category": "rigor", "detail": "dato sin contrastar"}],
    }
    setup_llms(llm_cls, reports=[rejected, rejected], fixes=[ARTICLE_BODY])

    with patch("article_generator.review.validate_body"):
        assert run(env(max_rounds="1")) == 0

    prs.merge_pr.assert_not_called()


@patch("article_generator.review.PRClient")
@patch("article_generator.review.LLMClient")
@patch("article_generator.review.IssuesClient")
def test_no_issue_number_still_merges(issues_cls, llm_cls, prs_cls):
    prs = setup_pr(prs_cls, body="Some description without Closes")
    setup_llms(llm_cls, [APPROVED])

    assert run(env()) == 0

    prs.merge_pr.assert_called_once_with(9, branch="article/issue-5")
    issues_cls.return_value.close_with_comment.assert_not_called()
