"""Tests for the generation orchestration."""
from unittest.mock import MagicMock, patch

from article_generator.main import run


def env():
    return {
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_TOKEN": "tok",
        "LLM_BASE_URL": "https://llm.example/v1",
        "LLM_API_KEY": "k",
        "LLM_MODEL": "m",
        "OUTPUT_DIR": "/tmp/out",
        "SITE_URL": "https://owner.github.io/repo",
    }


def topic_issue():
    return {
        "number": 5,
        "title": "Project Reactor",
        "body": "no entendemos el paradigma",
        "created_at": "2026-06-01T00:00:00Z",
        "labels": [{"name": "topic"}, {"name": "java"}],
        "user": {"login": "jordi"},
    }


@patch("article_generator.main.write_article", return_value="/tmp/out/2026-06-10-project-reactor.md")
@patch("article_generator.main.validate_body")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_generates_validates_writes_and_closes(issues_cls, llm_cls, validate, write):
    issues = issues_cls.return_value
    issues.next_topic.return_value = topic_issue()
    llm = llm_cls.return_value
    llm.generate.side_effect = ["the outline", "palabra " * 1200, "revisada " * 1200]
    llm.generate_json.return_value = {"summary": "El TL;DR.", "tags": ["reactive", "java"]}

    assert run(env()) == 0

    assert llm.generate.call_count == 3  # outline, article, code review pass
    write.assert_called_once()
    kwargs = write.call_args.kwargs
    assert kwargs["slug"] == "project-reactor"
    assert kwargs["body"] == "revisada " * 1200
    assert kwargs["summary"] == "El TL;DR."
    assert kwargs["description"] == "El TL;DR."
    assert kwargs["tags"] == ["java", "reactive"]  # issue labels first, LLM tags appended, deduped
    assert kwargs["issue_number"] == 5
    assert kwargs["requested_by"] == "jordi"
    assert kwargs["model"] == "m"
    issues.close_with_comment.assert_called_once()
    comment = issues.close_with_comment.call_args.args[1]
    assert "https://owner.github.io/repo/blog/" in comment
    assert "-project-reactor/" in comment


@patch("article_generator.main.write_article", return_value="/tmp/out/x.md")
@patch("article_generator.main.validate_body")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_falls_back_when_metadata_call_fails(issues_cls, llm_cls, validate, write):
    from article_generator.llm import LLMError

    issues = issues_cls.return_value
    issues.next_topic.return_value = topic_issue()
    llm = llm_cls.return_value
    body = "Primer párrafo del artículo.\n\n" + "palabra " * 1200
    llm.generate.side_effect = ["outline", body, body]
    llm.generate_json.side_effect = LLMError("bad json")

    assert run(env()) == 0

    kwargs = write.call_args.kwargs
    assert kwargs["summary"] == ""
    assert kwargs["description"] == "Primer párrafo del artículo."
    assert kwargs["tags"] == ["java"]
    issues.close_with_comment.assert_called_once()


@patch("article_generator.main.write_article", return_value="/tmp/out/x.md")
@patch("article_generator.main.validate_body")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_strips_issue_form_artifacts_from_notes(issues_cls, llm_cls, validate, write):
    issue = topic_issue()
    issue["body"] = "### Notas de enfoque\n\n_No response_"
    issues_cls.return_value.next_topic.return_value = issue
    llm = llm_cls.return_value
    llm.generate.side_effect = ["outline", "palabra " * 1200, "palabra " * 1200]

    run(env())

    outline_user_prompt = llm.generate.call_args_list[0].args[1]
    assert "Notas del equipo" not in outline_user_prompt
    assert "_No response_" not in outline_user_prompt


@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_skips_when_article_already_published_today(issues_cls, llm_cls, tmp_path):
    from datetime import date

    (tmp_path / f"{date.today().isoformat()}-cualquier-tema.md").write_text("x")
    e = env()
    e["OUTPUT_DIR"] = str(tmp_path)

    assert run(e) == 0

    issues_cls.return_value.next_topic.assert_not_called()
    llm_cls.return_value.generate.assert_not_called()


@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_exits_zero_when_no_topics(issues_cls, llm_cls):
    issues_cls.return_value.next_topic.return_value = None
    assert run(env()) == 0
    llm_cls.return_value.generate.assert_not_called()


@patch("article_generator.main.write_article", return_value="/tmp/out/x.md")
@patch("article_generator.main.validate_body")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_keeps_original_body_when_review_pass_fails(issues_cls, llm_cls, validate, write):
    from article_generator.llm import LLMError

    issues_cls.return_value.next_topic.return_value = topic_issue()
    llm = llm_cls.return_value
    body = "palabra " * 1200
    llm.generate.side_effect = ["outline", body, LLMError("review boom")]

    assert run(env()) == 0

    assert write.call_args.kwargs["body"] == body


@patch("article_generator.main.write_article", return_value="/tmp/out/x.md")
@patch("article_generator.main.validate_body")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_keeps_original_body_when_review_pass_shrinks_article(issues_cls, llm_cls, validate, write):
    issues_cls.return_value.next_topic.return_value = topic_issue()
    llm = llm_cls.return_value
    body = "palabra " * 1200
    llm.generate.side_effect = ["outline", body, "palabra " * 100]

    assert run(env()) == 0

    assert write.call_args.kwargs["body"] == body


@patch("article_generator.main.write_article")
@patch("article_generator.main.LLMClient")
@patch("article_generator.main.IssuesClient")
def test_run_does_not_close_issue_if_validation_fails(issues_cls, llm_cls, write):
    issues = issues_cls.return_value
    issues.next_topic.return_value = topic_issue()
    llm_cls.return_value.generate.side_effect = ["outline", "too short"]

    try:
        run(env())
        raised = False
    except Exception:
        raised = True

    assert raised
    write.assert_not_called()
    issues.close_with_comment.assert_not_called()
