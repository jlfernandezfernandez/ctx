"""Shared plumbing for GitHub REST API clients."""
import requests

GITHUB_API_VERSION = "2022-11-28"


class GitHubClient:
    """Base client; subclasses set `error` to their exception type."""

    error: type[Exception]

    def __init__(self, repo: str, token: str):
        self.base = f"https://api.github.com/repos/{repo}"
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        })

    def _require(self, response, expected: tuple[int, ...], action: str) -> None:
        if response.status_code not in expected:
            raise self.error(
                f"Failed to {action}: GitHub API error {response.status_code}: "
                f"{response.text[:500]}"
            )

    def comment(self, number: int, body: str) -> None:
        """Comment on an issue or PR (PRs are issues in the GitHub API)."""
        resp = self.session.post(
            f"{self.base}/issues/{number}/comments",
            json={"body": body},
        )
        self._require(resp, (200, 201), f"comment on #{number}")
