"""Tests for the writer-reviewer review loop."""
from unittest.mock import MagicMock, patch

from article_generator.agents.reviewer import run


def env(pr_number=9, max_rounds="2"):
    return {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_TOKEN": "tok",
        "LLM_BASE_URL": "https://llm.example/v1",
        "LLM_API_KEY": "k",
        "LLM_REVIEWER_MODEL": "reviewer-m",
        "LLM_WRITER_MODEL": "writer-m",
        "MAX_REVIEW_ROUNDS": max_rounds,
        "PR_NUMBER": str(pr_number),
        "SITE_URL": "https://owner.github.io/repo",
    }


FRONTMATTER = '---\ntitle: "Vistas"\ndate: 2026-06-11\nwriter: "writer-m"\n---\n\n'

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

APPROVED = {"issues": []}


def blocking_issue(detail="falta import de Flux"):
    return {"category": "codigo", "blocking": True, "detail": detail}


def suggestion(detail="el ejemplo 2 sería más claro con records"):
    return {"category": "legibilidad", "blocking": False, "detail": detail}


def setup_github(github_cls, body="Closes #5"):
    github = github_cls.return_value
    github.get_pr.return_value = {
        "body": body,
        "head": {"ref": "article/issue-5"},
        "title": "article: Vistas materializadas en Snowflake",
    }
    github.get_article_path.return_value = PATH
    github.read_file.return_value = FRONTMATTER + ARTICLE_BODY
    return github


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


@patch("article_generator.agents.reviewer.LLMClient")
@patch("article_generator.agents.reviewer.GitHubClient")
def test_approved_first_round_merges_and_closes_issue(github_cls, llm_cls):
    github = setup_github(github_cls)
    setup_llms(llm_cls, [APPROVED])

    assert run(env()) == 0

    github.merge_pr.assert_called_once_with(9, branch="article/issue-5")
    github.comment.assert_not_called()
    signed = github.update_file.call_args.args[2]
    assert signed.startswith("---\n")
    assert '\nreviewer: "reviewer-m"\n' in signed
    assert github.update_file.call_args.args[3] == "chore: reviewer sign-off"
    closing = github.close_with_comment.call_args.args[1]
    assert closing.endswith("/blog/2026-06-11-vistas-materializadas-en-snowflake/")


@patch("article_generator.agents.reviewer.LLMClient")
@patch("article_generator.agents.reviewer.GitHubClient")
def test_suggestions_only_merge_with_comment(github_cls, llm_cls):
    github = setup_github(github_cls)
    setup_llms(llm_cls, [{"issues": [suggestion()]}])

    assert run(env()) == 0

    github.merge_pr.assert_called_once_with(9, branch="article/issue-5")
    comment = github.comment.call_args.args[1]
    assert "sugerencias" in comment
    assert "records" in comment


@patch("article_generator.agents.reviewer.LLMClient")
@patch("article_generator.agents.reviewer.GitHubClient")
def test_blocking_defect_writer_fixes_then_merges(github_cls, llm_cls):
    github = setup_github(github_cls)
    reviewer, writer = setup_llms(
        llm_cls,
        reports=[{"issues": [blocking_issue()]}, APPROVED],
        fixes=[ARTICLE_BODY],
    )

    with patch("article_generator.agents.reviewer.validate_body"):
        assert run(env()) == 0

    writer.generate.assert_called_once()
    rewrite = writer.generate.call_args.args[1]
    assert "falta import de Flux" in rewrite
    assert "title:" not in rewrite  # the writer never sees the frontmatter
    fix_call = github.update_file.call_args_list[0]
    assert fix_call.args == (
        "article/issue-5", PATH, FRONTMATTER + ARTICLE_BODY, "fix: review feedback (round 1)"
    )
    round_comment = github.comment.call_args_list[0].args[1]
    assert "Cambios solicitados (ronda 1)" in round_comment
    github.merge_pr.assert_called_once_with(9, branch="article/issue-5")
    closing = github.close_with_comment.call_args.args[1]
    assert "con correcciones" in closing
    # Second review sees the previously reported defects.
    assert "falta import de Flux" in reviewer.generate_json.call_args.args[1]


@patch("article_generator.agents.reviewer.LLMClient")
@patch("article_generator.agents.reviewer.GitHubClient")
def test_round_budget_exhausted_leaves_pr_open(github_cls, llm_cls):
    github = setup_github(github_cls)
    rejected = {"issues": [blocking_issue("API inexistente")]}
    reviewer, writer = setup_llms(
        llm_cls,
        reports=[rejected, rejected, rejected],
        fixes=[ARTICLE_BODY, ARTICLE_BODY],
    )

    with patch("article_generator.agents.reviewer.validate_body"):
        assert run(env(max_rounds="2")) == 0

    assert writer.generate.call_count == 2  # the budget
    assert github.update_file.call_count == 2  # human sees the best version
    github.merge_pr.assert_not_called()
    github.close_with_comment.assert_not_called()
    final_comment = github.comment.call_args_list[-1].args[1]
    assert "sigue sin aprobar tras 2 correcciones" in final_comment
    assert "API inexistente" in final_comment


@patch("article_generator.agents.reviewer.LLMClient")
@patch("article_generator.agents.reviewer.GitHubClient")
def test_fix_breaking_structure_escalates(github_cls, llm_cls):
    from article_generator.article import ValidationError

    github = setup_github(github_cls)
    setup_llms(
        llm_cls,
        reports=[{"issues": [blocking_issue("URL inventada")]}],
        fixes=["too short"] * 3,
    )

    # The initial draft is valid; every rewrite breaks the structure.
    broken = [None, ValidationError("Body too short"), ValidationError("Body too short"),
              ValidationError("Body too short")]
    with patch("article_generator.agents.reviewer.validate_body", side_effect=broken):
        assert run(env()) == 0

    github.merge_pr.assert_not_called()
    github.update_file.assert_not_called()
    final_comment = github.comment.call_args_list[-1].args[1]
    assert "URL inventada" in final_comment
    assert "Body too short" in final_comment
    assert "3 intentos" in final_comment


@patch("article_generator.agents.reviewer.LLMClient")
@patch("article_generator.agents.reviewer.GitHubClient")
def test_invalid_draft_gets_structure_fix_before_reviewer(github_cls, llm_cls):
    github = setup_github(github_cls)
    github.read_file.return_value = FRONTMATTER + "## Solo una sección\n\ndemasiado corto"
    reviewer, writer = setup_llms(llm_cls, reports=[APPROVED], fixes=[ARTICLE_BODY])

    assert run(env()) == 0

    # The validator, not the reviewer, demands the structure fix.
    round_comment = github.comment.call_args_list[0].args[1]
    assert "[estructura]" in round_comment
    writer.generate.assert_called_once()
    reviewer.generate_json.assert_called_once()  # only sees the fixed draft
    assert "ronda anterior" not in reviewer.generate_json.call_args.args[1]
    github.merge_pr.assert_called_once_with(9, branch="article/issue-5")


@patch("article_generator.agents.reviewer.LLMClient")
@patch("article_generator.agents.reviewer.GitHubClient")
def test_broken_reviewer_escalates_without_writer_fixes(github_cls, llm_cls):
    from article_generator.llm import LLMError

    github = setup_github(github_cls)
    reviewer, writer = setup_llms(llm_cls, reports=[LLMError("down"), LLMError("down")])

    assert run(env()) == 0

    writer.generate.assert_not_called()
    github.merge_pr.assert_not_called()
    final_comment = github.comment.call_args_list[-1].args[1]
    assert "no devolvió un informe válido" in final_comment


@patch("article_generator.agents.reviewer.LLMClient")
@patch("article_generator.agents.reviewer.GitHubClient")
def test_report_without_issues_list_escalates(github_cls, llm_cls):
    github = setup_github(github_cls)
    bad_shape = {"issues": "no es una lista"}
    reviewer, writer = setup_llms(llm_cls, reports=[bad_shape, bad_shape])

    assert run(env()) == 0

    writer.generate.assert_not_called()
    github.merge_pr.assert_not_called()
    final_comment = github.comment.call_args_list[-1].args[1]
    assert "no devolvió un informe válido" in final_comment


@patch("article_generator.agents.reviewer.LLMClient")
@patch("article_generator.agents.reviewer.GitHubClient")
def test_issue_without_blocking_flag_blocks(github_cls, llm_cls):
    github = setup_github(github_cls)
    rejected = {"issues": [{"category": "rigor", "detail": "dato sin contrastar"}]}
    setup_llms(llm_cls, reports=[rejected, rejected], fixes=[ARTICLE_BODY])

    with patch("article_generator.agents.reviewer.validate_body"):
        assert run(env(max_rounds="1")) == 0

    github.merge_pr.assert_not_called()


@patch("article_generator.agents.reviewer.LLMClient")
@patch("article_generator.agents.reviewer.GitHubClient")
def test_no_issue_number_still_merges(github_cls, llm_cls):
    github = setup_github(github_cls, body="Some description without Closes")
    setup_llms(llm_cls, [APPROVED])

    assert run(env()) == 0

    github.merge_pr.assert_called_once_with(9, branch="article/issue-5")
    github.close_with_comment.assert_not_called()
