"""Topic queue backed by GitHub Issues.

An open issue labeled `topic` is a pending topic. `priority` jumps the
queue. Closing the issue with a link marks it published.
"""
import requests

TOPIC_LABEL = "topic"
PRIORITY_LABEL = "priority"


class GitHubError(Exception):
    pass


class IssuesClient:
    def __init__(self, repo: str, token: str):
        self.base = f"https://api.github.com/repos/{repo}"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        })

    def next_topic(self) -> dict | None:
        resp = self.session.get(
            f"{self.base}/issues",
            params={"state": "open", "labels": TOPIC_LABEL, "per_page": 100},
        )
        if resp.status_code != 200:
            raise GitHubError(f"GitHub API error {resp.status_code}: {resp.text[:500]}")
        issues = [i for i in resp.json() if "pull_request" not in i]
        if not issues:
            return None
        priority = [
            i for i in issues
            if any(l["name"] == PRIORITY_LABEL for l in i["labels"])
        ]
        pool = priority or issues
        return min(pool, key=lambda i: i["created_at"])

    def close_with_comment(self, number: int, comment: str) -> None:
        resp = self.session.post(f"{self.base}/issues/{number}/comments", json={"body": comment})
        if resp.status_code not in (200, 201):
            raise GitHubError(f"Failed to comment on issue #{number}: {resp.status_code}")
        resp = self.session.patch(f"{self.base}/issues/{number}", json={"state": "closed"})
        if resp.status_code != 200:
            raise GitHubError(f"Failed to close issue #{number}: {resp.status_code}")
