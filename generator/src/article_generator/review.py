"""Reviewer step: read the article PR, judge it, and decide.

Approve -> merge and close the topic issue with the published link.
Reject -> rewrite once, re-review the fix; if it passes, push and merge.
Otherwise push the best version, comment the remaining defects and leave
the PR open: an open article PR is the signal that a human has to decide
(merge = publish, close = discard).
"""
import os
import re
import sys

from .article import validate_body, ValidationError
from .github_issues import IssuesClient
from .github_prs import PRClient
from .llm import LLMClient, LLMError
from .prompts import REVIEWER_SYSTEM_PROMPT, rewrite_prompt, reviewer_prompt

BLOG_PREFIX = "site/src/content/blog/"


def _parse_pr_body(body: str) -> int | None:
    m = re.search(r"Closes\s+#(\d+)", body)
    return int(m.group(1)) if m else None


def _review_report(reviewer: LLMClient, topic: str, draft: str) -> dict:
    fallback = {
        "approved": False,
        "issues": [{"category": "general", "detail": "el revisor no devolvió un informe válido"}],
    }
    for retry_left in (True, False):
        try:
            report = reviewer.generate_json(REVIEWER_SYSTEM_PROMPT, reviewer_prompt(topic, draft))
        except LLMError:
            if retry_left:
                continue
            return fallback
        if isinstance(report.get("approved"), bool) and isinstance(report.get("issues"), list):
            return report
        if not retry_left:
            return fallback
    return fallback


def _format_issues(report: dict) -> list[str]:
    return [f"[{i.get('category', 'general')}] {i.get('detail', '')}" for i in report["issues"]]


def _article_link(site_url: str, path: str) -> str:
    blog_path = path.removeprefix(BLOG_PREFIX)
    return f"{site_url}/blog/{blog_path}" if site_url else blog_path


def run(env: dict) -> int:
    repo = env["GITHUB_REPOSITORY"]
    token = env["GITHUB_TOKEN"]
    pr_number = int(env["PR_NUMBER"])

    reviewer_model = env["LLM_REVIEWER_MODEL"]
    reviewer = LLMClient(base_url=env["LLM_BASE_URL"], api_key=env["LLM_API_KEY"], model=reviewer_model)

    issues = IssuesClient(repo=repo, token=token)
    prs = PRClient(repo=repo, token=token)

    pr = prs.get_pr(pr_number)
    issue_number = _parse_pr_body(pr.get("body") or "")
    branch = pr["head"]["ref"]
    topic = pr["title"].removeprefix("article: ").strip()

    path = prs.get_article_path(pr_number)
    draft = prs.read_file(branch, path)
    print(f"Reviewing article for issue #{issue_number}: {topic}")

    site_url = env.get("SITE_URL", "").rstrip("/")

    def publish(note: str = "") -> int:
        prs.merge_pr(pr_number, branch=branch)
        if issue_number:
            issues.close_with_comment(issue_number, f"Publicado{note}: {_article_link(site_url, path)}")
        return 0

    report = _review_report(reviewer, topic, draft)
    if report["approved"]:
        print("Reviewer approved. Merging.")
        return publish()

    defects = _format_issues(report)
    print(f"Rejected. Issues: {defects}")

    fixed = reviewer.generate(REVIEWER_SYSTEM_PROMPT, rewrite_prompt(topic, draft, defects))

    def escalate(remaining: list[str]) -> int:
        pending = "\n".join(f"- {item}" for item in remaining)
        prs.comment_on_pr(
            pr_number,
            "El revisor no aprobó tras corregir. Defectos pendientes:\n\n"
            f"{pending}\n\nMergear publica el artículo; cerrar la PR lo descarta.",
        )
        print("Could not approve after fixing. PR left open for a human.")
        return 0

    try:
        validate_body(fixed)
    except ValidationError as exc:
        return escalate(defects + [f"[estructura] {exc}"])

    second_report = _review_report(reviewer, topic, fixed)
    prs.update_file(branch, path, fixed, "fix: address review feedback")
    if second_report["approved"]:
        print("Fix approved on second review. Merging.")
        return publish(note=" (con correcciones)")
    return escalate(_format_issues(second_report))


def main() -> None:
    sys.exit(run(dict(os.environ)))
