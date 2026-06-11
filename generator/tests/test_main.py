"""Tests for the generation orchestration."""
from unittest.mock import MagicMock, patch

import pytest

from article_generator.main import run


@pytest.fixture(autouse=True)
def avoid_reference_network():
    with patch("article_generator.main.validate_reference_urls"):
        yield


def env():
    return {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_TOKEN": "tok",
        "LLM_BASE_URL": "https://llm.example/v1",
        "LLM_API_KEY": "k",
        "WRITER_MODEL": "writer-m",
        "REVIEWER_MODEL": "reviewer-m",
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


def graph_state(approved, body="palabra " * 1200, feedback=None):
    return {
        "approved": approved,
        "draft": body,
        "feedback": feedback or [],
        "outline": "outline",
        "iteration": 2,
        "valid": True,
        "topic": "Project Reactor",
        "notes": "no entendemos el paradigma",
    }


@patch("article_generator.main.write_article", return_value="/tmp/out/2026-06-10-project-reactor.md")
@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_approved_article_is_published_and_issue_closed(
    issues_cls, llm_cls, drafts_cls, build_graph, write
):
    issues = issues_cls.return_value
    issues.next_topic.return_value = topic_issue()
    graph = build_graph.return_value
    graph.invoke.return_value = graph_state(approved=True)
    llm_cls.return_value.generate_json.return_value = {
        "summary": "El TL;DR.",
        "tags": ["reactive", "java"],
    }

    assert run(env()) == 0

    kwargs = write.call_args.kwargs
    assert kwargs["slug"] == "project-reactor"
    assert kwargs["body"] == "palabra " * 1200
    assert kwargs["summary"] == "El TL;DR."
    assert kwargs["tags"] == ["java", "reactive"]
    assert kwargs["model"] == "writer-m + reviewer-m (reviewer)"
    assert kwargs["issue_number"] == 5
    assert kwargs["requested_by"] == "jordi"
    issues.close_with_comment.assert_called_once()
    comment = issues.close_with_comment.call_args.args[1]
    assert "https://owner.github.io/repo/blog/" in comment
    drafts_cls.return_value.create_draft_pr.assert_not_called()
    issues.next_topic.assert_called_once()


@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_two_models_and_max_iterations_from_env(issues_cls, llm_cls, drafts_cls, build_graph):
    issues_cls.return_value.next_topic.return_value = None
    e = env()
    e["MAX_REVIEW_ITERATIONS"] = "3"

    assert run(e) == 0

    models = [call.kwargs["model"] for call in llm_cls.call_args_list]
    assert models == ["writer-m", "reviewer-m"]
    assert build_graph.call_args.args[2] == 3


@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_writer_model_falls_back_to_legacy_llm_model(issues_cls, llm_cls, drafts_cls, build_graph):
    issues_cls.return_value.next_topic.return_value = None
    e = env()
    del e["WRITER_MODEL"]
    e["LLM_MODEL"] = "legacy-m"

    assert run(e) == 0

    assert llm_cls.call_args_list[0].kwargs["model"] == "legacy-m"


@patch("article_generator.main.write_article", return_value="/tmp/out/x.md")
@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_rejected_article_becomes_draft_pr_then_next_topic_published(
    issues_cls, llm_cls, drafts_cls, build_graph, write
):
    issues = issues_cls.return_value
    issues.next_topic.side_effect = [topic_issue(5), topic_issue(6, title="Kafka")]
    graph = build_graph.return_value
    graph.invoke.side_effect = [
        graph_state(approved=False, feedback=["[codigo] falta import"]),
        graph_state(approved=True),
    ]
    llm_cls.return_value.generate_json.return_value = {"summary": "s", "tags": []}
    drafts = drafts_cls.return_value
    drafts.create_draft_pr.return_value = "https://github.com/owner/repo/pull/9"

    assert run(env()) == 0

    kwargs = drafts.create_draft_pr.call_args.kwargs
    assert kwargs["branch"] == "draft/issue-5"
    assert kwargs["path"].startswith("site/src/content/blog/")
    assert kwargs["path"].endswith("-project-reactor.md")
    assert "Closes #5" in kwargs["body"]
    assert "[codigo] falta import" in kwargs["body"]
    assert "title: " in kwargs["content"]  # rendered frontmatter
    issues.add_label.assert_called_once_with(5, "needs-human-review")
    issues.close_with_comment.assert_called_once()  # only the published one (#6)
    assert write.call_args.kwargs["slug"] == "kafka"


@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_stops_after_max_topics_rejections(issues_cls, llm_cls, drafts_cls, build_graph):
    issues = issues_cls.return_value
    issues.next_topic.side_effect = [topic_issue(5), topic_issue(6), topic_issue(7)]
    build_graph.return_value.invoke.return_value = graph_state(approved=False)
    llm_cls.return_value.generate_json.return_value = {"summary": "", "tags": []}

    assert run(env()) == 0

    assert issues.next_topic.call_count == 2  # MAX_TOPICS_PER_RUN default
    assert drafts_cls.return_value.create_draft_pr.call_count == 2
    issues.close_with_comment.assert_not_called()


@patch("article_generator.main.write_article", return_value="/tmp/out/x.md")
@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_metadata_failure_falls_back_to_first_paragraph(
    issues_cls, llm_cls, drafts_cls, build_graph, write
):
    from article_generator.llm import LLMError

    issues_cls.return_value.next_topic.return_value = topic_issue()
    body = "Primer párrafo del artículo.\n\n" + "palabra " * 1200
    build_graph.return_value.invoke.return_value = graph_state(approved=True, body=body)
    llm_cls.return_value.generate_json.side_effect = LLMError("bad json")

    assert run(env()) == 0

    kwargs = write.call_args.kwargs
    assert kwargs["summary"] == ""
    assert kwargs["description"] == "Primer párrafo del artículo."
    assert kwargs["tags"] == ["java"]


@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_strips_issue_form_artifacts_from_notes(issues_cls, llm_cls, drafts_cls, build_graph):
    issue = topic_issue()
    issue["body"] = "### Notas de enfoque\n\n_No response_"
    issues = issues_cls.return_value
    issues.next_topic.return_value = issue
    graph = build_graph.return_value
    graph.invoke.return_value = graph_state(approved=True)
    llm_cls.return_value.generate_json.return_value = {"summary": "s", "tags": []}

    with patch("article_generator.main.write_article", return_value="/tmp/out/x.md"):
        run(env())

    state = graph.invoke.call_args.args[0]
    assert state["notes"] == ""


@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_skips_when_article_already_published_today(issues_cls, llm_cls, tmp_path):
    from datetime import date

    (tmp_path / f"{date.today().isoformat()}-cualquier-tema.md").write_text("x")
    e = env()
    e["OUTPUT_DIR"] = str(tmp_path)

    assert run(e) == 0

    issues_cls.return_value.next_topic.assert_not_called()


@patch("article_generator.main.build_graph")
@patch("article_generator.main.DraftsClient")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_exits_zero_when_no_topics(issues_cls, llm_cls, drafts_cls, build_graph):
    issues_cls.return_value.next_topic.return_value = None
    assert run(env()) == 0
    build_graph.return_value.invoke.assert_not_called()
