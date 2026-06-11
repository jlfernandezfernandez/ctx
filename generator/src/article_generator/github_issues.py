"""Topic queue backed by GitHub Issues.

An open issue labeled `topic` is a pending topic. `priority` jumps the
queue. Closing the issue with a link marks it published.
"""
import requests

TOPIC_LABEL = "topic"
TRIAGE_LABEL = "triage"
PRIORITY_LABEL = "priority"
PUBLISHED_LABEL = "published"
REJECTED_LABEL = "rejected"


class GitHubError(Exception):
    pass


def _votes(issue: dict) -> int:
    return issue.get("reactions", {}).get("+1", 0)


class IssuesClient:
    def __init__(self, repo: str, token: str):
        self.base = f"https://api.github.com/repos/{repo}"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def _require(self, response, expected: tuple[int, ...], action: str) -> None:
        if response.status_code not in expected:
            raise GitHubError(
                f"Failed to {action}: GitHub API error {response.status_code}: "
                f"{response.text[:500]}"
            )

    def next_topic(self, skip: set[int] = frozenset()) -> dict | None:
        """Next topic to publish; `skip` holds issues whose article PR is already open."""
        resp = self.session.get(
            f"{self.base}/issues",
            params={"state": "open", "labels": TOPIC_LABEL, "per_page": 100},
        )
        if resp.status_code != 200:
            raise GitHubError(f"GitHub API error {resp.status_code}: {resp.text[:500]}")
        issues = [
            i
            for i in resp.json()
            if "pull_request" not in i and i["number"] not in skip
        ]
        if not issues:
            return None
        priority = [
            i for i in issues
            if any(l["name"] == PRIORITY_LABEL for l in i["labels"])
        ]
        pool = priority or issues
        # Most 👍 reactions wins; ties go to the oldest issue.
        return sorted(pool, key=lambda i: (-_votes(i), i["created_at"]))[0]

    def get_issue(self, number: int) -> dict:
        resp = self.session.get(f"{self.base}/issues/{number}")
        self._require(resp, (200,), f"get issue #{number}")
        return resp.json()

    def update_issue(self, number: int, *, title: str = None, body: str = None) -> None:
        data = {}
        if title is not None:
            data["title"] = title
        if body is not None:
            data["body"] = body
        if not data:
            return
        resp = self.session.patch(
            f"{self.base}/issues/{number}",
            json=data,
        )
        self._require(resp, (200,), f"update issue #{number}")

    def set_labels(self, number: int, labels: list[str]) -> None:
        resp = self.session.put(
            f"{self.base}/issues/{number}/labels",
            json={"labels": labels},
        )
        self._require(resp, (200,), f"set labels on issue #{number}")

    def comment(self, number: int, body: str) -> None:
        resp = self.session.post(
            f"{self.base}/issues/{number}/comments",
            json={"body": body},
        )
        self._require(resp, (200, 201), f"comment on issue #{number}")

    def close(self, number: int) -> None:
        resp = self.session.patch(
            f"{self.base}/issues/{number}",
            json={"state": "closed"},
        )
        self._require(resp, (200,), f"close issue #{number}")

    def close_with_comment(self, number: int, comment: str) -> None:
        self.comment(number, comment)
        # Best effort: a missing label must not block publishing.
        resp = self.session.post(
            f"{self.base}/issues/{number}/labels", json={"labels": [PUBLISHED_LABEL]}
        )
        if resp.status_code not in (200, 201):
            print(f"Could not label issue #{number} as {PUBLISHED_LABEL}: {resp.status_code}")
        self.close(number)
