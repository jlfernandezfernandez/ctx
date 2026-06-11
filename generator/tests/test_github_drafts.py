"""Tests for the draft PR rescue client."""
import base64
from unittest.mock import MagicMock

import pytest

from article_generator.github_drafts import DraftsClient, DraftsError


def client():
    c = DraftsClient(repo="owner/repo", token="tok")
    c.session = MagicMock()
    ref = MagicMock(status_code=200)
    ref.json.return_value = {"object": {"sha": "abc123"}}
    c.session.get.return_value = ref
    branch = MagicMock(status_code=201)
    pr = MagicMock(status_code=201)
    pr.json.return_value = {"html_url": "https://github.com/owner/repo/pull/9"}
    c.session.post.side_effect = [branch, pr]
    c.session.put.return_value = MagicMock(status_code=201)
    return c


def test_create_draft_pr_creates_branch_file_and_pr():
    c = client()
    url = c.create_draft_pr(
        branch="draft/issue-5",
        path="site/src/content/blog/2026-06-11-tema.md",
        content="---\ntitle: x\n---\n\ncuerpo\n",
        title="draft: tema",
        body="Closes #5",
    )
    assert url == "https://github.com/owner/repo/pull/9"

    c.session.get.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/git/ref/heads/main"
    )
    branch_call = c.session.post.call_args_list[0]
    assert branch_call.args == ("https://api.github.com/repos/owner/repo/git/refs",)
    assert branch_call.kwargs["json"] == {"ref": "refs/heads/draft/issue-5", "sha": "abc123"}

    put_call = c.session.put.call_args
    assert put_call.args == (
        "https://api.github.com/repos/owner/repo/contents/site/src/content/blog/2026-06-11-tema.md",
    )
    sent = put_call.kwargs["json"]
    assert sent["branch"] == "draft/issue-5"
    assert base64.b64decode(sent["content"]).decode() == "---\ntitle: x\n---\n\ncuerpo\n"

    pr_call = c.session.post.call_args_list[1]
    assert pr_call.args == ("https://api.github.com/repos/owner/repo/pulls",)
    assert pr_call.kwargs["json"] == {
        "title": "draft: tema",
        "head": "draft/issue-5",
        "base": "main",
        "body": "Closes #5",
    }


def test_create_draft_pr_fails_clearly_when_branch_exists():
    c = client()
    c.session.post.side_effect = [MagicMock(status_code=422, text="Reference already exists")]
    with pytest.raises(DraftsError, match="draft/issue-5"):
        c.create_draft_pr(
            branch="draft/issue-5",
            path="p.md",
            content="x",
            title="t",
            body="b",
        )


def test_create_draft_pr_raises_on_ref_lookup_error():
    c = client()
    c.session.get.return_value = MagicMock(status_code=404, text="nope")
    with pytest.raises(DraftsError):
        c.create_draft_pr(branch="b", path="p.md", content="x", title="t", body="b")
