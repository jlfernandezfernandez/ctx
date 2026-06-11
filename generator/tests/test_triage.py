"""Tests for automatic topic proposal triage."""
import json
from unittest.mock import call, patch

import pytest

from article_generator.triage import (
    Classification,
    TriageError,
    effective_action,
    parse_classification,
    run,
)


def env(tmp_path, issue=None):
    issue = issue or {
        "number": 17,
        "title": "Índices en PostgreSQL",
        "body": "Cuándo usar B-tree y cuándo no.",
        "user": {"login": "jordi"},
    }
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"issue": issue}))
    return {
        "GITHUB_EVENT_PATH": str(event),
        "GITHUB_REPOSITORY": "owner/repo",
        "GITHUB_TOKEN": "tok",
        "LLM_BASE_URL": "https://ollama.com/v1",
        "LLM_API_KEY": "key",
        "LLM_TRIAGE_MODEL": "nemotron-3-nano:30b-cloud",
    }


def classification(action="APPROVE", category="sql", confidence=0.95, reason="Tema técnico"):
    return Classification(action, category, confidence, reason)


def test_parse_classification_accepts_strict_valid_line():
    result = parse_classification("APPROVE|sql|0.96|Tema técnico válido")
    assert result == classification(confidence=0.96, reason="Tema técnico válido")


@pytest.mark.parametrize(
    "output",
    [
        "APPROVE|sql|0.96|Tema técnico válido\nNota extra del modelo",
        "Aquí tienes la clasificación:\nAPPROVE|sql|0.96|Tema técnico válido",
        "```\nAPPROVE|sql|0.96|Tema técnico válido\n```",
        "```APPROVE|sql|0.96|Tema técnico válido```",
    ],
)
def test_parse_classification_recovers_answer_from_noisy_output(output):
    result = parse_classification(output)
    assert result == classification(confidence=0.96, reason="Tema técnico válido")


@pytest.mark.parametrize(
    "output",
    [
        "APPROVE|sql|0.9",
        "APPROVE|SQL avanzado|0.9|bad slug",
        "REJECT|sql|0.9|wrong category",
        "APPROVE|sql|1.2|bad confidence",
        "APPROVE|sql|0.9|ok\nREVIEW|none|0.5|two answer lines",
        "El tema parece técnico pero no estoy seguro.",
    ],
)
def test_parse_classification_rejects_unexpected_output(output):
    with pytest.raises(TriageError):
        parse_classification(output)


def test_effective_action_requires_more_confidence_for_new_categories():
    assert effective_action(classification(confidence=0.8), {"sql"}) == "APPROVE"
    assert effective_action(classification(category="postgresql", confidence=0.8), {"sql"}) == "REVIEW"
    assert effective_action(classification(category="postgresql", confidence=0.95), {"sql"}) == "APPROVE"


def test_effective_action_only_rejects_with_high_confidence():
    assert effective_action(classification("REJECT", "none", 0.89), {"sql"}) == "REVIEW"
    assert effective_action(classification("REJECT", "none", 0.9), {"sql"}) == "REJECT"


@patch("article_generator.triage.LLMClient")
@patch("article_generator.triage.IssuesClient")
def test_run_approves_existing_category(issues_cls, llm_cls, tmp_path):
    issues = issues_cls.return_value
    issues.count_issues_by_author_since.return_value = 1
    issues.category_labels.return_value = ["sql", "java"]
    llm_cls.return_value.generate.return_value = "APPROVE|sql|0.95|Tema técnico"

    assert run(env(tmp_path)) == 0

    issues.ensure_system_labels.assert_called_once()
    issues.create_category_label.assert_not_called()
    assert issues.set_labels.call_args_list == [
        call(17, ["triage"]),
        call(17, ["topic", "sql"]),
    ]
    issues.close.assert_not_called()
    assert llm_cls.call_args.kwargs["model"] == "nemotron-3-nano:30b-cloud"
    assert llm_cls.return_value.generate.call_args.kwargs == {
        "temperature": 0,
        "max_tokens": 100,
        "reasoning_effort": "none",
    }


@patch("article_generator.triage.LLMClient")
@patch("article_generator.triage.IssuesClient")
def test_run_creates_high_confidence_new_category(issues_cls, llm_cls, tmp_path):
    issues = issues_cls.return_value
    issues.count_issues_by_author_since.return_value = 1
    issues.category_labels.return_value = ["sql"]
    llm_cls.return_value.generate.return_value = "APPROVE|postgresql|0.95|Tema técnico"

    run(env(tmp_path))

    issues.create_category_label.assert_called_once_with("postgresql")
    assert issues.set_labels.call_args_list == [
        call(17, ["triage"]),
        call(17, ["topic", "postgresql"]),
    ]


@patch("article_generator.triage.LLMClient")
@patch("article_generator.triage.IssuesClient")
def test_run_leaves_low_confidence_new_category_for_review(issues_cls, llm_cls, tmp_path):
    issues = issues_cls.return_value
    issues.count_issues_by_author_since.return_value = 1
    issues.category_labels.return_value = ["sql"]
    llm_cls.return_value.generate.return_value = "APPROVE|postgresql|0.80|Puede ser SQL"

    run(env(tmp_path))

    issues.create_category_label.assert_not_called()
    issues.set_labels.assert_called_once_with(17, ["triage"])
    issues.close.assert_not_called()


@patch("article_generator.triage.LLMClient")
@patch("article_generator.triage.IssuesClient")
def test_run_rejects_clear_non_technical_topic(issues_cls, llm_cls, tmp_path):
    issues = issues_cls.return_value
    issues.count_issues_by_author_since.return_value = 1
    issues.category_labels.return_value = ["sql"]
    llm_cls.return_value.generate.return_value = "REJECT|none|0.99|No es técnico"

    run(env(tmp_path))

    assert issues.set_labels.call_args_list == [
        call(17, ["triage"]),
        call(17, ["rejected"]),
    ]
    issues.close.assert_called_once_with(17)


@patch("article_generator.triage.LLMClient")
@patch("article_generator.triage.IssuesClient")
def test_run_fails_safe_when_classifier_output_is_invalid(issues_cls, llm_cls, tmp_path):
    issues = issues_cls.return_value
    issues.count_issues_by_author_since.return_value = 1
    issues.category_labels.return_value = ["sql"]
    llm_cls.return_value.generate.return_value = "Claro, aquí tienes: APPROVE"

    assert run(env(tmp_path)) == 0

    issues.set_labels.assert_called_once_with(17, ["triage"])
    issues.close.assert_not_called()


@patch("article_generator.triage.LLMClient")
@patch("article_generator.triage.IssuesClient")
def test_run_rate_limits_before_calling_model(issues_cls, llm_cls, tmp_path):
    issues = issues_cls.return_value
    issues.count_issues_by_author_since.return_value = 6

    assert run(env(tmp_path)) == 0

    assert issues.set_labels.call_args_list == [
        call(17, ["triage"]),
        call(17, ["rate-limited"]),
    ]
    issues.close.assert_called_once_with(17)
    issues.category_labels.assert_not_called()
    llm_cls.assert_not_called()
