"""Tests for automatic topic proposal curation."""
import json
from unittest.mock import call, patch

import pytest

from article_generator.triage import Classification, TriageError, parse_classification, run


def env(tmp_path, issue=None):
    issue = issue or {
        "number": 17,
        "title": "pydantic ai",
        "body": "Cómo crear agentes tipados.",
        "user": {"login": "jordi"},
        "labels": [{"name": "triage"}],
    }
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"issue": issue}))
    return {
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_TOKEN": "tok",
        "LLM_BASE_URL": "https://ollama.com/v1",
        "LLM_API_KEY": "key",
        "LLM_TRIAGE_MODEL": "curator-model",
    }


def test_parse_classification_accepts_valid_response():
    assert parse_classification({
        "action": "approve",
        "title": " Pydantic AI ",
        "reason": " Tema técnico válido ",
    }) == Classification("APPROVE", "Pydantic AI", "Tema técnico válido")


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"action": "MAYBE", "title": "X", "reason": "Duda"},
        {"action": "APPROVE", "title": "", "reason": "Duda"},
        {"action": "APPROVE", "title": "X", "reason": ""},
    ],
)
def test_parse_classification_rejects_invalid_response(data):
    with pytest.raises(TriageError):
        parse_classification(data)


@patch("article_generator.triage.LLMClient")
@patch("article_generator.triage.IssuesClient")
def test_run_approves_and_normalizes_title(issues_cls, llm_cls, tmp_path):
    issues = issues_cls.return_value
    llm_cls.return_value.generate_json.return_value = {
        "action": "APPROVE",
        "title": "Pydantic AI",
        "reason": "Tema técnico válido",
    }

    assert run(env(tmp_path)) == 0

    issues.update_title.assert_called_once_with(17, "Pydantic AI")
    issues.set_labels.assert_called_once_with(17, ["topic"])
    issues.close.assert_not_called()
    assert llm_cls.call_args.kwargs["model"] == "curator-model"


@patch("article_generator.triage.LLMClient")
@patch("article_generator.triage.IssuesClient")
def test_run_rejects_clear_spam(issues_cls, llm_cls, tmp_path):
    issues = issues_cls.return_value
    llm_cls.return_value.generate_json.return_value = {
        "action": "REJECT",
        "title": "Compra seguidores",
        "reason": "Spam sin contenido técnico",
    }

    run(env(tmp_path))

    assert issues.set_labels.call_args_list == [call(17, ["rejected"])]
    issues.comment.assert_called_once_with(17, "Propuesta descartada: Spam sin contenido técnico")
    issues.close.assert_called_once_with(17)


@patch("article_generator.triage.LLMClient")
@patch("article_generator.triage.IssuesClient")
def test_run_leaves_doubtful_topic_for_review(issues_cls, llm_cls, tmp_path):
    issues = issues_cls.return_value
    llm_cls.return_value.generate_json.return_value = {
        "action": "REVIEW",
        "title": "Una propuesta ambigua",
        "reason": "No queda claro el enfoque",
    }

    run(env(tmp_path))

    issues.set_labels.assert_called_once_with(17, ["triage"])
    issues.comment.assert_called_once_with(
        17, "Curación automática pendiente de revisión: No queda claro el enfoque"
    )
    issues.close.assert_not_called()


@patch("article_generator.triage.LLMClient")
@patch("article_generator.triage.IssuesClient")
def test_run_fails_safe_when_curator_response_is_invalid(issues_cls, llm_cls, tmp_path):
    issues = issues_cls.return_value
    llm_cls.return_value.generate_json.return_value = {"action": "APPROVE"}

    assert run(env(tmp_path)) == 0

    issues.set_labels.assert_called_once_with(17, ["triage"])
    issues.comment.assert_called_once()
    issues.close.assert_not_called()


@patch("article_generator.triage.LLMClient")
@patch("article_generator.triage.IssuesClient")
def test_manual_run_fetches_requested_issue(issues_cls, llm_cls, tmp_path):
    issue = {
        "number": 3,
        "title": "SSE vs HTTP clásico",
        "body": "",
        "user": {"login": "jordi"},
        "labels": [{"name": "triage"}, {"name": "priority"}],
    }
    issues = issues_cls.return_value
    issues.get_issue.return_value = issue
    llm_cls.return_value.generate_json.return_value = {
        "action": "APPROVE",
        "title": issue["title"],
        "reason": "Tema técnico",
    }

    run({**env(tmp_path), "TRIAGE_ISSUE_NUMBER": "3"})

    issues.get_issue.assert_called_once_with(3)
    issues.set_labels.assert_called_once_with(3, ["topic", "priority"])
