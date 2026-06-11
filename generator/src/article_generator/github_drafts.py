"""Opens and manages pull requests for article generation.

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
            json={"message": f"article: {title}", "content": encoded, "branch": branch},
        )
        self._require(put, (201,), f"create {path} on {branch}")

        pr = self.session.post(
            f"{self.base}/pulls",
            json={"title": title, "head": branch, "base": base, "body": body},
        )
        self._require(pr, (201,), "open draft pull request")
        return pr.json()["html_url"], pr.json()["number"]

    def get_pr(self, number: int) -> dict:
        resp = self.session.get(f"{self.base}/pulls/{number}")
        self._require(resp, (200,), f"get PR #{number}")
        return resp.json()

    def merge_pr(self, number: int, commit_title: str = "") -> None:
        resp = self.session.put(
            f"{self.base}/pulls/{number}/merge",
            json={"commit_title": commit_title} if commit_title else {},
        )
        self._require(resp, (200,), f"merge PR #{number}")

    def get_file(self, ref: str, dir_path: str) -> tuple[str, str] | None:
        """Get the filename and decoded content of the first .md file in the directory at the given ref."""
        resp = self.session.get(
            f"{self.base}/contents/{dir_path}",
            params={"ref": ref},
        )
        self._require(resp, (200,), f"list files in {dir_path} at {ref}")
        entries = resp.json()
        for entry in entries:
            if entry.get("name", "").endswith(".md") and entry.get("type") == "file":
                file_resp = self.session.get(entry["download_url"])
                self._require(file_resp, (200,), f"download {entry['name']}")
                return entry["name"], file_resp.text
        return None

    def update_file(self, branch: str, path: str, content: str, message: str) -> None:
        """Get the file's SHA, then update it."""
        resp = self.session.get(
            f"{self.base}/contents/{path}",
            params={"ref": branch},
        )
        self._require(resp, (200,), f"get SHA for {path}")
        sha = resp.json()["sha"]
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        put = self.session.put(
            f"{self.base}/contents/{path}",
            json={"message": message, "content": encoded, "branch": branch, "sha": sha},
        )
        self._require(put, (200,), f"update {path} on {branch}")

    def comment_on_pr(self, number: int, body: str) -> None:
        resp = self.session.post(
            f"{self.base}/issues/{number}/comments",
            json={"body": body},
        )
        self._require(resp, (200, 201), f"comment on PR #{number}")