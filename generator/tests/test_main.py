"""Tests for the end-to-end editorial pipeline."""
from unittest.mock import MagicMock, patch

from article_generator.pipeline import run


def env(pr_number=""):
    return {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_TOKEN": "tok",
        "LLM_BASE_URL": "https://llm.example/v1",
        "LLM_API_KEY": "k",
        "LLM_WRITER_MODEL": "writer-m",
        "LLM_REVIEWER_MODEL": "reviewer-m",
        "MAX_REVIEW_ROUNDS": "2",
        "PR_NUMBER": pr_number,
        "SITE_URL": "https://owner.github.io/repo",
    }


def topic_issue():
    return {
        "number": 5,
        "title": "Project Reactor",
        "body": "Explica backpressure y trade-offs.",
        "user": {"login": "jordi"},
    }


def setup_llms(llm_cls):
    writer = MagicMock()
    writer.generate.side_effect = ["outline", "## Contexto\n\nArtículo.", "## Contexto\n\nCorregido."]
    writer.generate_json.return_value = {
        "title": "Project Reactor y backpressure",
        "summary": "Cómo funciona el control de demanda.",
        "tags": ["auth"],
    }
    reviewer = MagicMock()
    reviewer.generate_json.return_value = {"issues": []}
    llm_cls.side_effect = lambda base_url, api_key, model: reviewer if model == "reviewer-m" else writer
    return writer, reviewer


@patch("article_generator.pipeline._body_defects", return_value=[])
@patch("article_generator.pipeline._canonical_tags", return_value=["reactive"])
@patch("article_generator.pipeline.LLMClient")
@patch("article_generator.pipeline.GitHubClient")
def test_pipeline_opens_draft_pr_before_review_and_merges(
    github_cls, llm_cls, _canonical_tags, _body_defects
):
    github = github_cls.return_value
    github.article_exists_for_date.return_value = False
    github.next_topic.return_value = topic_issue()
    github.open_article_issue_numbers.return_value = set()
    github.open_pr.return_value = ("https://github.com/owner/repo/pull/9", 9)
    github.get_pr.return_value = {
        "body": "Closes #5",
        "head": {"ref": "article/issue-5"},
        "title": "article: Project Reactor y backpressure",
    }
    github.get_article_path.return_value = "site/src/content/blog/reactor.md"
    github.read_file.return_value = (
        '---\ntitle: "Project Reactor y backpressure"\ntags: ["auth"]\nwriter: "writer-m"\n---\n\n'
        "## Contexto\n\nArtículo."
    )
    setup_llms(llm_cls)

    assert run(env()) == 0

    github.open_pr.assert_called_once()
    created = github.open_pr.call_args.kwargs["content"]
    assert 'tags: ["auth"]' in created
    taxonomy_update = next(
        call for call in github.update_file.call_args_list if call.args[1] == "site/src/data/tags.json"
    )
    assert taxonomy_update.args[2] == '[\n  "auth",\n  "reactive"\n]\n'
    calls = [method[0] for method in github.method_calls]
    assert calls.index("open_pr") < calls.index("get_pr")
    github.merge_pr.assert_called_once_with(9, branch="article/issue-5")


@patch("article_generator.pipeline._body_defects", return_value=[])
@patch("article_generator.pipeline._canonical_tags", return_value=["reactive"])
@patch("article_generator.pipeline.LLMClient")
@patch("article_generator.pipeline.GitHubClient")
def test_pipeline_does_not_update_taxonomy_when_writer_reuses_tag(
    github_cls, llm_cls, _canonical_tags, _body_defects
):
    github = github_cls.return_value
    github.article_exists_for_date.return_value = False
    github.next_topic.return_value = topic_issue()
    github.open_article_issue_numbers.return_value = set()
    github.open_pr.return_value = ("https://github.com/owner/repo/pull/9", 9)
    github.get_pr.return_value = {
        "body": "Closes #5",
        "head": {"ref": "article/issue-5"},
        "title": "article: Project Reactor",
    }
    github.get_article_path.return_value = "site/src/content/blog/reactor.md"
    github.read_file.return_value = (
        '---\ntitle: "Project Reactor"\ntags: ["reactive"]\nwriter: "writer-m"\n---\n\n'
        "## Contexto\n\nArtículo."
    )
    writer, _ = setup_llms(llm_cls)
    writer.generate_json.return_value["tags"] = ["reactive"]

    assert run(env()) == 0

    taxonomy_updates = [
        call for call in github.update_file.call_args_list if call.args[1] == "site/src/data/tags.json"
    ]
    assert taxonomy_updates == []


@patch("article_generator.pipeline.LLMClient")
@patch("article_generator.pipeline.GitHubClient")
def test_pipeline_skips_when_queue_is_empty(github_cls, llm_cls):
    github_cls.return_value.article_exists_for_date.return_value = False
    github_cls.return_value.next_topic.return_value = None

    assert run(env()) == 0

    llm_cls.assert_not_called()


@patch("article_generator.pipeline.LLMClient")
@patch("article_generator.pipeline.GitHubClient")
def test_pipeline_skips_when_article_already_published_today(github_cls, llm_cls):
    github_cls.return_value.article_exists_for_date.return_value = True

    assert run(env()) == 0

    github_cls.return_value.next_topic.assert_not_called()
    llm_cls.assert_not_called()


@patch("article_generator.pipeline._review_draft", return_value=0)
@patch("article_generator.pipeline.GitHubClient")
def test_manual_run_reviews_existing_pr(github_cls, review):
    assert run(env("17")) == 0
    review.assert_called_once_with(env("17"), github_cls.return_value, 17)
