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
RATE_LIMITED_LABEL = "rate-limited"
NEEDS_HUMAN_REVIEW_LABEL = "needs-human-review"

SYSTEM_LABELS = {
    TOPIC_LABEL,
    TRIAGE_LABEL,
    PRIORITY_LABEL,
    PUBLISHED_LABEL,
    REJECTED_LABEL,
    RATE_LIMITED_LABEL,
    NEEDS_HUMAN_REVIEW_LABEL,
}

GITHUB_DEFAULT_LABELS = {
    "bug",
    "documentation",
    "duplicate",
    "enhancement",
    "good first issue",
    "help wanted",
    "invalid",
    "question",
    "wontfix",
}

NON_CATEGORY_LABELS = SYSTEM_LABELS | GITHUB_DEFAULT_LABELS

SYSTEM_LABEL_DETAILS = {
    TOPIC_LABEL: ("0e8a16", "Tema aceptado y pendiente de publicación"),
    TRIAGE_LABEL: ("fbca04", "Propuesta pendiente de clasificación o revisión"),
    PRIORITY_LABEL: ("b60205", "Publicar antes que la cola ordinaria"),
    PUBLISHED_LABEL: ("5319e7", "Artículo publicado"),
    REJECTED_LABEL: ("d93f0b", "Propuesta descartada"),
    RATE_LIMITED_LABEL: ("6e7781", "Propuesta cerrada por límite diario"),
    NEEDS_HUMAN_REVIEW_LABEL: ("e99695", "El revisor IA no aprobó el borrador; pendiente de humano"),
}


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

    def next_topic(self) -> dict | None:
        resp = self.session.get(
            f"{self.base}/issues",
            params={"state": "open", "labels": TOPIC_LABEL, "per_page": 100},
        )
        if resp.status_code != 200:
            raise GitHubError(f"GitHub API error {resp.status_code}: {resp.text[:500]}")
        issues = [
            i
            for i in resp.json()
            if "pull_request" not in i
            and not any(l["name"] == NEEDS_HUMAN_REVIEW_LABEL for l in i["labels"])
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

    def _labels(self) -> list[dict]:
        resp = self.session.get(f"{self.base}/labels", params={"per_page": 100})
        self._require(resp, (200,), "list labels")
        return resp.json()

    def category_labels(self) -> list[str]:
        return sorted(
            label["name"]
            for label in self._labels()
            if label["name"].lower() not in NON_CATEGORY_LABELS
        )

    def ensure_system_labels(self) -> None:
        existing = {label["name"].lower() for label in self._labels()}
        for name, (color, description) in SYSTEM_LABEL_DETAILS.items():
            if name in existing:
                continue
            created = self.session.post(
                f"{self.base}/labels",
                json={"name": name, "color": color, "description": description},
            )
            self._require(created, (201, 422), f"create system label {name}")

    def count_issues_by_author_since(
        self, author: str, since: str, current_number: int
    ) -> int:
        resp = self.session.get(
            f"{self.base}/issues",
            params={
                "state": "all",
                "creator": author,
                "since": since,
                "per_page": 100,
            },
        )
        self._require(resp, (200,), f"count issues created by {author}")
        issues = [
            issue
            for issue in resp.json()
            if "pull_request" not in issue and issue["created_at"] >= since
        ]
        numbers = {issue["number"] for issue in issues}
        return len(issues) + (current_number not in numbers)

    def create_category_label(self, name: str) -> None:
        resp = self.session.post(
            f"{self.base}/labels",
            json={
                "name": name,
                "color": "1f6feb",
                "description": "Categoría técnica asignada automáticamente",
            },
        )
        # Another workflow may have created the same label concurrently.
        self._require(resp, (201, 422), f"create label {name}")

    def set_labels(self, number: int, labels: list[str]) -> None:
        resp = self.session.put(
            f"{self.base}/issues/{number}/labels",
            json={"labels": labels},
        )
        self._require(resp, (200,), f"set labels on issue #{number}")

    def add_label(self, number: int, label: str) -> None:
        resp = self.session.post(
            f"{self.base}/issues/{number}/labels",
            json={"labels": [label]},
        )
        self._require(resp, (200, 201), f"add label {label} to issue #{number}")

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
