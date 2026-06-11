"""Review loop: the reviewer judges, the writer fixes, until publishable.

Each round the reviewer reports defects with a severity. Only blocking
defects (broken code, false claims, invented references) send the article
back to the writer; suggestions are posted as a comment and never block
the merge. The loop is bounded by MAX_REVIEW_ROUNDS writer fixes so the
reviewer can't nitpick forever. If blocking defects survive the budget,
the best version is pushed and the PR is left open: an open article PR
means a human decides (merge = publish, close = discard).

The whole conversation happens in-process; PR comments and fix commits
are just the visible trail.
"""
import os
import re
import sys

from .article import split_frontmatter, validate_body, ValidationError
from .github_issues import IssuesClient
from .github_prs import PRClient
from .llm import LLMClient, LLMError
from .prompts import (
    REVIEWER_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    reviewer_prompt,
    rewrite_prompt,
)

BLOG_PREFIX = "site/src/content/blog/"


def _parse_pr_body(body: str) -> int | None:
    m = re.search(r"Closes\s+#(\d+)", body)
    return int(m.group(1)) if m else None


def _review_report(
    reviewer: LLMClient, topic: str, draft: str, previous_feedback: list[str] | None = None
) -> dict:
    fallback = {
        "approved": False,
        "issues": [
            {
                "category": "general",
                "blocking": True,
                "detail": "el revisor no devolvió un informe válido",
            }
        ],
    }
    for retry_left in (True, False):
        try:
            report = reviewer.generate_json(
                REVIEWER_SYSTEM_PROMPT, reviewer_prompt(topic, draft, previous_feedback)
            )
        except LLMError:
            if retry_left:
                continue
            return fallback
        if isinstance(report.get("approved"), bool) and isinstance(report.get("issues"), list):
            return report
        if not retry_left:
            return fallback
    return fallback


def _split_issues(report: dict) -> tuple[list[str], list[str]]:
    """(blocking, suggestions); an issue without a clear blocking flag blocks."""
    blocking, suggestions = [], []
    for issue in report["issues"]:
        line = f"[{issue.get('category', 'general')}] {issue.get('detail', '')}"
        if issue.get("blocking") is False:
            suggestions.append(line)
        else:
            blocking.append(line)
    return blocking, suggestions


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _article_link(site_url: str, path: str) -> str:
    slug = path.removeprefix(BLOG_PREFIX).removesuffix(".md")
    return f"{site_url}/blog/{slug}/" if site_url else slug


def _sign_frontmatter(frontmatter: str, reviewer_model: str) -> str:
    """Record which model reviewed the article, next to the writer's line."""
    if not frontmatter or "\nreviewer:" in frontmatter:
        return frontmatter
    escaped = reviewer_model.replace("\\", "\\\\").replace('"', '\\"')
    return frontmatter.replace("\n---", f'\nreviewer: "{escaped}"\n---', 1)


def run(env: dict) -> int:
    repo = env["GITHUB_REPOSITORY"]
    token = env["GITHUB_TOKEN"]
    pr_number = int(env["PR_NUMBER"])
    max_rounds = int(env["MAX_REVIEW_ROUNDS"])

    base_url, api_key = env["LLM_BASE_URL"], env["LLM_API_KEY"]
    reviewer_model = env["LLM_REVIEWER_MODEL"]
    reviewer = LLMClient(base_url=base_url, api_key=api_key, model=reviewer_model)
    writer = LLMClient(base_url=base_url, api_key=api_key, model=env["LLM_WRITER_MODEL"])

    issues = IssuesClient(repo=repo, token=token)
    prs = PRClient(repo=repo, token=token)

    pr = prs.get_pr(pr_number)
    issue_number = _parse_pr_body(pr.get("body") or "")
    branch = pr["head"]["ref"]
    topic = pr["title"].removeprefix("article: ").strip()

    path = prs.get_article_path(pr_number)
    # The LLMs only ever see and rewrite the body; the frontmatter is
    # machine-built metadata and must survive every round untouched.
    frontmatter, draft = split_frontmatter(prs.read_file(branch, path))
    print(f"Reviewing article for issue #{issue_number}: {topic}")

    site_url = env.get("SITE_URL", "").rstrip("/")

    def publish(fixes: int, suggestions: list[str]) -> int:
        if suggestions:
            prs.comment_on_pr(
                pr_number, f"Aprobado con sugerencias no bloqueantes:\n\n{_bullets(suggestions)}"
            )
        signed = _sign_frontmatter(frontmatter, reviewer_model)
        if signed != frontmatter:
            prs.update_file(branch, path, signed + draft, "chore: reviewer sign-off")
        prs.merge_pr(pr_number, branch=branch)
        if issue_number:
            note = " (con correcciones)" if fixes else ""
            issues.close_with_comment(
                issue_number, f"Publicado{note}: {_article_link(site_url, path)}"
            )
        # Quality log: traceable per-article stats for prompt tuning.
        log = (
            f"quality_log: issue=#{issue_number or '?'} topic={topic} "
            f"writer={env['LLM_WRITER_MODEL']} reviewer={reviewer_model} "
            f"rounds={fixes} approved=true\n"
        )
        print(log)
        return 0

    def escalate(reason: str, pending: list[str]) -> int:
        prs.comment_on_pr(
            pr_number,
            f"{reason} Defectos pendientes:\n\n{_bullets(pending)}\n\n"
            "Mergear publica el artículo; cerrar la PR lo descarta.",
        )
        print("Could not approve. PR left open for a human.")
        return 0

    previous_blocking: list[str] | None = None
    for fixes_done in range(max_rounds + 1):
        report = _review_report(reviewer, topic, draft, previous_blocking)
        blocking, suggestions = _split_issues(report)
        if not blocking:
            print(f"Approved after {fixes_done} fix(es). Merging.")
            return publish(fixes_done, suggestions)
        if fixes_done == max_rounds:
            return escalate(
                f"El reviewer sigue sin aprobar tras {max_rounds} correcciones.", blocking
            )

        round_number = fixes_done + 1
        print(f"Round {round_number}: blocking defects: {blocking}")
        prs.comment_on_pr(
            pr_number, f"Cambios solicitados (ronda {round_number}):\n\n{_bullets(blocking)}"
        )

        fixed = None
        for rewrite_attempt in range(3):
            fixed = writer.generate(
                SYSTEM_PROMPT, rewrite_prompt(topic, draft, blocking, attempt=rewrite_attempt + 1)
            )
            try:
                validate_body(fixed)
                break
            except ValidationError as exc:
                if rewrite_attempt == 2:
                    return escalate(
                        f"La corrección del writer rompió la estructura del artículo tras 3 intentos.",
                        blocking + [f"[estructura] {exc}"],
                    )
                print(f"  Rewrite attempt {rewrite_attempt + 1} broke structure ({exc}), retrying...")

        prs.update_file(
            branch, path, frontmatter + fixed, f"fix: review feedback (round {round_number})"
        )
        draft = fixed
        previous_blocking = blocking

    return 0


def main() -> None:
    sys.exit(run(dict(os.environ)))
