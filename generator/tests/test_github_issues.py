"""Tests for the topic queue backed by GitHub Issues."""
from unittest.mock import MagicMock

import pytest

from article_generator.github_issues import IssuesClient, GitHubError


def issue(number, created, labels, title="t", votes=0):
    return {
        "number": number,
        "title": title,
        "body": "notes",
        "created_at": created,
        "labels": [{"name": name} for name in labels],
        "reactions": {"+1": votes},
    }


def client_with(issues_payload, status=200):
    c = IssuesClient(repo="owner/repo", token="tok")
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = issues_payload
    resp.text = "err"
    c.session = MagicMock()
    c.session.get.return_value = resp
    c.session.post.return_value = MagicMock(status_code=201)
    c.session.put.return_value = MagicMock(status_code=200)
    c.session.patch.return_value = MagicMock(status_code=200)
    return c


def test_next_topic_returns_oldest():
    c = client_with([
        issue(2, "2026-06-02T00:00:00Z", ["topic"]),
        issue(1, "2026-06-01T00:00:00Z", ["topic"]),
    ])
    assert c.next_topic()["number"] == 1


def test_next_topic_priority_jumps_queue():
    c = client_with([
        issue(1, "2026-06-01T00:00:00Z", ["topic"]),
        issue(2, "2026-06-02T00:00:00Z", ["topic", "priority"]),
    ])
    assert c.next_topic()["number"] == 2


def test_next_topic_most_voted_wins():
    c = client_with([
        issue(1, "2026-06-01T00:00:00Z", ["topic"], votes=1),
        issue(2, "2026-06-02T00:00:00Z", ["topic"], votes=5),
    ])
    assert c.next_topic()["number"] == 2


def test_next_topic_votes_tie_falls_back_to_oldest():
    c = client_with([
        issue(2, "2026-06-02T00:00:00Z", ["topic"], votes=3),
        issue(1, "2026-06-01T00:00:00Z", ["topic"], votes=3),
    ])
    assert c.next_topic()["number"] == 1


def test_next_topic_priority_beats_votes():
    c = client_with([
        issue(1, "2026-06-01T00:00:00Z", ["topic"], votes=99),
        issue(2, "2026-06-02T00:00:00Z", ["topic", "priority"], votes=0),
    ])
    assert c.next_topic()["number"] == 2


def test_next_topic_none_when_empty():
    assert client_with([]).next_topic() is None


def test_next_topic_skips_pull_requests():
    pr = issue(3, "2026-05-01T00:00:00Z", ["topic"])
    pr["pull_request"] = {"url": "x"}
    c = client_with([pr, issue(1, "2026-06-01T00:00:00Z", ["topic"])])
    assert c.next_topic()["number"] == 1


def test_next_topic_raises_on_api_error():
    with pytest.raises(GitHubError):
        client_with([], status=500).next_topic()


def test_close_with_comment_comments_labels_then_closes():
    c = client_with([])
    c.close_with_comment(7, "done")
    posts = c.session.post.call_args_list
    assert posts[0].args == ("https://api.github.com/repos/owner/repo/issues/7/comments",)
    assert posts[0].kwargs == {"json": {"body": "done"}}
    assert posts[1].args == ("https://api.github.com/repos/owner/repo/issues/7/labels",)
    assert posts[1].kwargs == {"json": {"labels": ["published"]}}
    c.session.patch.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/issues/7",
        json={"state": "closed"},
    )


def test_close_with_comment_tolerates_label_failure():
    c = client_with([])
    ok = MagicMock(status_code=201)
    label_fail = MagicMock(status_code=404)
    c.session.post.side_effect = [ok, label_fail]
    c.close_with_comment(7, "done")  # must not raise
    c.session.patch.assert_called_once()


def test_count_issues_by_author_since_filters_old_issues_and_adds_current():
    c = client_with([
        {**issue(1, "2026-06-11T08:00:00Z", []), "user": {"login": "jordi"}},
        {**issue(2, "2026-06-10T08:00:00Z", []), "user": {"login": "jordi"}},
    ])
    assert c.count_issues_by_author_since("jordi", "2026-06-11T00:00:00Z", 3) == 2
    assert c.session.get.call_args.kwargs["params"]["creator"] == "jordi"


def test_category_labels_excludes_queue_labels():
    c = client_with([
        {"name": "topic"},
        {"name": "triage"},
        {"name": "enhancement"},
        {"name": "java"},
        {"name": "sql"},
    ])
    assert c.category_labels() == ["java", "sql"]


def test_ensure_system_labels_creates_only_missing_labels():
    c = client_with([{"name": "topic"}, {"name": "triage"}])
    c.ensure_system_labels()
    created = [call.kwargs["json"]["name"] for call in c.session.post.call_args_list]
    assert "topic" not in created
    assert "triage" not in created
    assert "rejected" in created
    assert "rate-limited" in created


def test_set_labels_replaces_all_issue_labels():
    c = client_with([])
    c.set_labels(7, ["topic", "java"])
    c.session.put.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/issues/7/labels",
        json={"labels": ["topic", "java"]},
    )
