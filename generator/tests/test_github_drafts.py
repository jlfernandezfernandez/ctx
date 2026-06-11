"""Tests for the draft PR client."""
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
    pr.json.return_value = {"html_url": "https://github.com/owner/repo/pull/9", "number": 9}
    c.session.post.side_effect = [branch, pr]
    c.session.put.return_value = MagicMock(status_code=201)
    return c


def test_create_draft_pr_creates_branch_file_and_pr():
    c = client()
    url, number = c.create_draft_pr(
        branch="article/issue-5",
        path="site/src/content/blog/2026-06-11-tema.md",
        content="---\ntitle: x\n---\n\ncuerpo\n",
        title="article: tema",
        body="Closes #5",
    )
    assert url == "https://github.com/owner/repo/pull/9"
    assert number == 9

    c.session.get.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/git/ref/heads/main"
    )
    branch_call = c.session.post.call_args_list[0]
    assert branch_call.args == ("https://api.github.com/repos/owner/repo/git/refs",)
    assert branch_call.kwargs["json"] == {"ref": "refs/heads/article/issue-5", "sha": "abc123"}

    put_call = c.session.put.call_args
    assert put_call.args == (
        "https://api.github.com/repos/owner/repo/contents/site/src/content/blog/2026-06-11-tema.md",
    )
    sent = put_call.kwargs["json"]
    assert sent["branch"] == "article/issue-5"
    assert base64.b64decode(sent["content"]).decode() == "---\ntitle: x\n---\n\ncuerpo\n"

    pr_call = c.session.post.call_args_list[1]
    assert pr_call.args == ("https://api.github.com/repos/owner/repo/pulls",)
    assert pr_call.kwargs["json"] == {
        "title": "article: tema",
        "head": "article/issue-5",
        "base": "main",
        "body": "Closes #5",
    }


def test_create_draft_pr_fails_clearly_when_branch_exists():
    c = client()
    c.session.post.side_effect = [MagicMock(status_code=422, text="Reference already exists")]
    with pytest.raises(DraftsError, match="article/issue-5"):
        c.create_draft_pr(
            branch="article/issue-5",
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


def test_get_article_path_finds_md():
    c = DraftsClient(repo="owner/repo", token="tok")
    c.session = MagicMock()
    files_resp = MagicMock(status_code=200)
    files_resp.json.return_value = [
        {"filename": "site/src/content/blog/2026-06-11-tema.md", "status": "added"},
        {"filename": "README.md", "status": "modified"},
    ]
    c.session.get.return_value = files_resp
    assert c.get_article_path(9) == "site/src/content/blog/2026-06-11-tema.md"


def test_get_article_path_raises_when_no_md():
    c = DraftsClient(repo="owner/repo", token="tok")
    c.session = MagicMock()
    files_resp = MagicMock(status_code=200)
    files_resp.json.return_value = [{"filename": "README.md", "status": "modified"}]
    c.session.get.return_value = files_resp
    with pytest.raises(DraftsError, match="No article"):
        c.get_article_path(9)


def test_read_file_decodes_content():
    c = DraftsClient(repo="owner/repo", token="tok")
    c.session = MagicMock()
    content = base64.b64encode(b"hello world").decode()
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"content": content}
    c.session.get.return_value = resp
    assert c.read_file("main", "site/src/content/blog/test.md") == "hello world"


def test_merge_pr_sends_put():
    c = DraftsClient(repo="owner/repo", token="tok")
    c.session = MagicMock()
    c.session.put.return_value = MagicMock(status_code=200)
    c.merge_pr(9)
    c.session.put.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/pulls/9/merge",
        json={},
    )


def test_comment_on_pr_posts_comment():
    c = DraftsClient(repo="owner/repo", token="tok")
    c.session = MagicMock()
    c.session.post.return_value = MagicMock(status_code=201)
    c.comment_on_pr(9, "review comment")
    c.session.post.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/issues/9/comments",
        json={"body": "review comment"},
    )


def test_update_file_puts_new_content():
    c = DraftsClient(repo="owner/repo", token="tok")
    c.session = MagicMock()
    get_resp = MagicMock(status_code=200)
    get_resp.json.return_value = {"sha": "oldsha"}
    put_resp = MagicMock(status_code=200)
    c.session.get.return_value = get_resp
    c.session.put.return_value = put_resp

    c.update_file("article/issue-5", "site/src/content/blog/file.md", "new content", "fix: review")

    c.session.get.assert_called_once_with(
        "https://api.github.com/repos/owner/repo/contents/site/src/content/blog/file.md",
        params={"ref": "article/issue-5"},
    )
    call_json = c.session.put.call_args.kwargs["json"]
    assert call_json["sha"] == "oldsha"
    assert base64.b64decode(call_json["content"]).decode() == "new content"
    assert call_json["branch"] == "article/issue-5"