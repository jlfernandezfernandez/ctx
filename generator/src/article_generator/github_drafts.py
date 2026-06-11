"""Opens a pull request with a rejected article so a human can rescue it.

Uses the GitHub contents API instead of local git: the run must not leave
uncommitted files behind for the publish step, and merging the PR is the
human approval mechanism (merge = publish, close = discard).
"""
import base64

import requests


class DraftsError(Exception):
    pass


class DraftsClient:
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
            raise DraftsError(
                f"Failed to {action}: GitHub API error {response.status_code}: "
                f"{response.text[:500]}"
            )

    def create_draft_pr(
        self, branch: str, path: str, content: str, title: str, body: str, base: str = "main"
    ) -> str:
        ref = self.session.get(f"{self.base}/git/ref/heads/{base}")
        self._require(ref, (200,), f"resolve {base} ref")
        sha = ref.json()["object"]["sha"]

        created = self.session.post(
            f"{self.base}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
        )
        if created.status_code == 422:
            raise DraftsError(
                f"Branch {branch} already exists; close or delete the previous draft PR first"
            )
        self._require(created, (201,), f"create branch {branch}")

        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        put = self.session.put(
            f"{self.base}/contents/{path}",
            json={"message": f"draft: {title}", "content": encoded, "branch": branch},
        )
        self._require(put, (201,), f"create {path} on {branch}")

        pr = self.session.post(
            f"{self.base}/pulls",
            json={"title": title, "head": branch, "base": base, "body": body},
        )
        self._require(pr, (201,), "open draft pull request")
        return pr.json()["html_url"]
