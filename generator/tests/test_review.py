"""Tests for the pipeline review loop."""
from unittest.mock import MagicMock, patch

from article_generator.pipeline import run


def env(max_rounds="2"):
    return {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_TOKEN": "tok",
        "LLM_BASE_URL": "https://llm.example/v1",
        "LLM_API_KEY": "k",
        "LLM_REVIEWER_MODEL": "reviewer-m",
        "LLM_WRITER_MODEL": "writer-m",
        "MAX_REVIEW_ROUNDS": max_rounds,
        "PR_NUMBER": "9",
        "SITE_URL": "https://owner.github.io/repo",
    }


FRONTMATTER = '---\ntitle: "Vistas"\ntags: ["snowflake"]\nwriter: "writer-m"\n---\n\n'
ARTICLE_BODY = "## Contexto\n\nContenido técnico."
PATH = "site/src/content/blog/vistas.md"
APPROVED = {"issues": []}


def issue(detail="falta import de Flux", blocking=True):
    return {"category": "codigo", "blocking": blocking, "detail": detail}


def setup_github(github_cls):
    github = github_cls.return_value
    github.get_pr.return_value = {
        "body": "Closes #5",
        "head": {"ref": "article/issue-5"},
        "title": "article: Vistas",
    }
    github.get_article_path.return_value = PATH
    github.read_file.return_value = FRONTMATTER + ARTICLE_BODY
    return github


def setup_llms(llm_cls, reports, fixes=()):
    reviewer, writer = MagicMock(), MagicMock()
    reviewer.generate_json.side_effect = reports
    writer.generate.side_effect = fixes
    llm_cls.side_effect = lambda base_url, api_key, model: reviewer if model == "reviewer-m" else writer
    return reviewer, writer


@patch("article_generator.pipeline._body_defects", return_value=[])
@patch("article_generator.pipeline.LLMClient")
@patch("article_generator.pipeline.GitHubClient")
def test_approved_first_round_merges_and_closes_issue(github_cls, llm_cls, _body_defects):
    github = setup_github(github_cls)
    setup_llms(llm_cls, [APPROVED])

    assert run(env()) == 0

    github.merge_pr.assert_called_once_with(9, branch="article/issue-5")
    assert '\nreviewer: "reviewer-m"\n' in github.update_file.call_args.args[2]
    assert github.close_with_comment.call_args.args[1].endswith("/blog/vistas/")


@patch("article_generator.pipeline._body_defects", return_value=[])
@patch("article_generator.pipeline.LLMClient")
@patch("article_generator.pipeline.GitHubClient")
def test_blocking_defect_writer_fixes_then_merges(github_cls, llm_cls, _body_defects):
    github = setup_github(github_cls)
    reviewer, writer = setup_llms(
        llm_cls, [{"issues": [issue()]}, APPROVED], fixes=[ARTICLE_BODY]
    )

    assert run(env()) == 0

    assert "falta import de Flux" in writer.generate.call_args.args[1]
    assert "falta import de Flux" in reviewer.generate_json.call_args.args[1]
    github.merge_pr.assert_called_once()


@patch("article_generator.pipeline._body_defects", return_value=[])
@patch("article_generator.pipeline.LLMClient")
@patch("article_generator.pipeline.GitHubClient")
def test_round_budget_exhausted_leaves_pr_open(github_cls, llm_cls, _body_defects):
    github = setup_github(github_cls)
    rejected = {"issues": [issue("API inexistente")]}
    setup_llms(llm_cls, [rejected, rejected], fixes=[ARTICLE_BODY])

    assert run(env(max_rounds="1")) == 0

    github.merge_pr.assert_not_called()
    assert "API inexistente" in github.comment.call_args.args[1]


@patch("article_generator.pipeline._body_defects", return_value=[])
@patch("article_generator.pipeline.LLMClient")
@patch("article_generator.pipeline.GitHubClient")
def test_suggestions_do_not_block_publication(github_cls, llm_cls, _body_defects):
    github = setup_github(github_cls)
    setup_llms(llm_cls, [{"issues": [issue("mejor ejemplo", blocking=False)]}])

    assert run(env()) == 0

    assert "sugerencias" in github.comment.call_args.args[1]
    github.merge_pr.assert_called_once()


@patch("article_generator.pipeline._body_defects", return_value=[])
@patch("article_generator.pipeline.LLMClient")
@patch("article_generator.pipeline.GitHubClient")
def test_broken_reviewer_escalates_without_writer_fix(github_cls, llm_cls, _body_defects):
    from article_generator.llm import LLMError

    github = setup_github(github_cls)
    _, writer = setup_llms(llm_cls, [LLMError("down"), LLMError("down")])

    assert run(env()) == 0

    writer.generate.assert_not_called()
    github.merge_pr.assert_not_called()
    assert "no devolvió un informe válido" in github.comment.call_args.args[1]
