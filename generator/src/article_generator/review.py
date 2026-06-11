"""Reviews an article PR: reads the draft, runs the reviewer model, and either
pushes a fix and auto-merges or adds the 'needs-human-review' label.

Triggered by the 'needs-review' label on a pull request.
"""
import os
import re
import sys

from .article import validate_body, ValidationError
from .github_drafts import DraftsClient
from .github_issues import NEEDS_HUMAN_REVIEW_LABEL, IssuesClient
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
    drafts = DraftsClient(repo=repo, token=token)

    pr = drafts.get_pr(pr_number)
    issue_number = _parse_pr_body(pr.get("body") or "")
    branch = pr["head"]["ref"]
    topic = pr["title"].removeprefix("article: ").strip()

    path = drafts.get_article_path(pr_number)
    draft = drafts.read_file(branch, path)
    print(f"Reviewing article for issue #{issue_number}: {topic}")

    report = _review_report(reviewer, topic, draft)

    site_url = env.get("SITE_URL", "").rstrip("/")

    if report["approved"]:
        print("Reviewer approved. Auto-merging.")
        drafts.merge_pr(pr_number)
        if issue_number:
            issues.close_with_comment(issue_number, f"Publicado: {_article_link(site_url, path)}")
        return 0

    issues_list = [f"[{i.get('category', 'general')}] {i.get('detail', '')}" for i in report["issues"]]
    print(f"Rejected. Issues: {issues_list}")

    fixed = reviewer.generate(
        REVIEWER_SYSTEM_PROMPT,
        rewrite_prompt(topic, "", draft, issues_list),
    )

    try:
        validate_body(fixed)
    except ValidationError as exc:
        print(f"Fixed version still has issues ({exc}). Needs human review.")
        if issue_number:
            issues.add_label(issue_number, NEEDS_HUMAN_REVIEW_LABEL)
        comments = "\n".join(f"- {i}" for i in issues_list)
        drafts.comment_on_pr(pr_number, f"Revisor no aprobó tras corrección. Defectos pendientes:\n\n{comments}")
        return 0

    print("Fixed version passes validation. Pushing fix.")
    drafts.update_file(branch, path, fixed, "fix: address review feedback")
    drafts.merge_pr(pr_number)
    if issue_number:
        issues.close_with_comment(issue_number, f"Publicado (con correcciones): {_article_link(site_url, path)}")
    return 0


def main() -> None:
    sys.exit(run(dict(os.environ)))