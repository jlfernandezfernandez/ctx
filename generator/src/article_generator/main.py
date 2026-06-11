"""Orchestrates one generation run: pick topic -> writer-reviewer graph -> publish.

An approved article is published directly. A rejected one becomes a draft
PR (merge = publish, close = discard) and the run moves on to the next
topic, up to MAX_TOPICS_PER_RUN.
"""
import os
import sys
from datetime import date
from pathlib import Path

from .article import (
    make_description,
    render_article,
    slugify,
    validate_reference_urls,
    write_article,
)
from .github_drafts import DraftsClient
from .github_issues import NEEDS_HUMAN_REVIEW_LABEL, SYSTEM_LABELS, IssuesClient
from .graph import build_graph, initial_state
from .llm import LLMClient, LLMError
from .prompts import SYSTEM_PROMPT, metadata_prompt

# Artifacts that GitHub issue forms inject into the body.
FORM_ARTIFACTS = ("### Notas de enfoque", "_No response_")


def clean_notes(body: str) -> str:
    for artifact in FORM_ARTIFACTS:
        body = body.replace(artifact, "")
    return body.strip()


def collect_metadata(llm: LLMClient, issue: dict, topic: str, body: str) -> tuple[str, list[str]]:
    """Summary and tags; issue labels first, LLM tags appended, deduped."""
    tags = [l["name"] for l in issue["labels"] if l["name"] not in SYSTEM_LABELS]
    summary = ""
    try:
        meta = llm.generate_json(SYSTEM_PROMPT, metadata_prompt(topic, body))
        if isinstance(meta.get("summary"), str):
            summary = meta["summary"].strip()
        if isinstance(meta.get("tags"), list):
            for tag in meta["tags"]:
                tag = str(tag).strip().lower()
                if tag and tag not in tags:
                    tags.append(tag)
    except LLMError as exc:
        print(f"Metadata generation failed ({exc}); falling back to defaults.")
    return summary, tags


def publish(issues, writer, issue, body, output_dir, site_url, today, model_stamp) -> None:
    topic = issue["title"]
    validate_reference_urls(body)
    summary, tags = collect_metadata(writer, issue, topic, body)
    slug = slugify(topic)
    path = write_article(
        output_dir=output_dir,
        pub_date=today,
        slug=slug,
        title=topic,
        description=summary or make_description(body),
        tags=tags,
        body=body,
        summary=summary,
        issue_number=issue["number"],
        requested_by=(issue.get("user") or {}).get("login", ""),
        model=model_stamp,
    )
    print(f"Article written: {path}")
    link = f"{site_url}/blog/{today.isoformat()}-{slug}/" if site_url else path
    issues.close_with_comment(issue["number"], f"Publicado: {link}")
    print(f"Issue #{issue['number']} closed.")


def open_draft_pr(drafts, issues, writer, issue, body, feedback, today, model_stamp) -> None:
    topic = issue["title"]
    summary, tags = collect_metadata(writer, issue, topic, body)
    slug = slugify(topic)
    content = render_article(
        pub_date=today,
        title=topic,
        description=summary or make_description(body),
        tags=tags,
        body=body,
        summary=summary,
        issue_number=issue["number"],
        requested_by=(issue.get("user") or {}).get("login", ""),
        model=model_stamp,
    )
    issues_list = "\n".join(f"- {item}" for item in feedback) or "- (sin detalle)"
    pr_body = (
        f"Closes #{issue['number']}\n\n"
        f"El revisor (`{model_stamp}`) no aprobó el artículo. Defectos pendientes:\n\n"
        f"{issues_list}\n\n"
        "**Merge** = publicar tal cual (el deploy se dispara con el push a main). "
        "**Cerrar el PR** = descartar el borrador."
    )
    url = drafts.create_draft_pr(
        branch=f"draft/issue-{issue['number']}",
        path=f"site/src/content/blog/{today.isoformat()}-{slug}.md",
        content=content,
        title=f"draft: {topic}",
        body=pr_body,
    )
    issues.add_label(issue["number"], NEEDS_HUMAN_REVIEW_LABEL)
    print(f"Draft PR opened for issue #{issue['number']}: {url}")


def run(env: dict) -> int:
    output_dir = env.get("OUTPUT_DIR", "site/src/content/blog")
    today = date.today()

    # One article per day, even if the workflow is dispatched again.
    existing = list(Path(output_dir).glob(f"{today.isoformat()}-*.md"))
    if existing:
        print(f"Already published today: {existing[0].name}. Nothing to do.")
        return 0

    issues = IssuesClient(repo=env["GITHUB_REPOSITORY"], token=env["GITHUB_TOKEN"])
    drafts = DraftsClient(repo=env["GITHUB_REPOSITORY"], token=env["GITHUB_TOKEN"])
    site_url = env.get("SITE_URL", "").rstrip("/")

    # Unset workflow vars arrive as empty strings, hence `or` over defaults.
    writer_model = env.get("WRITER_MODEL") or env.get("LLM_MODEL") or "deepseek-v4-pro"
    reviewer_model = env.get("REVIEWER_MODEL") or "minimax-m3"
    max_iterations = int(env.get("MAX_REVIEW_ITERATIONS") or 2)
    max_topics = int(env.get("MAX_TOPICS_PER_RUN") or 2)

    writer = LLMClient(base_url=env["LLM_BASE_URL"], api_key=env["LLM_API_KEY"], model=writer_model)
    reviewer = LLMClient(base_url=env["LLM_BASE_URL"], api_key=env["LLM_API_KEY"], model=reviewer_model)
    graph = build_graph(writer, reviewer, max_iterations)
    model_stamp = f"{writer_model} + {reviewer_model} (reviewer)"

    for _ in range(max_topics):
        issue = issues.next_topic()
        if issue is None:
            print("No pending topics; nothing to publish.")
            return 0

        topic = issue["title"]
        notes = clean_notes(issue.get("body") or "")
        print(f"Generating article for issue #{issue['number']}: {topic}")

        state = graph.invoke(initial_state(topic, notes))

        if state["approved"]:
            publish(issues, writer, issue, state["draft"], output_dir, site_url, today, model_stamp)
            return 0

        print(f"Reviewer did not approve issue #{issue['number']}; opening draft PR.")
        open_draft_pr(drafts, issues, writer, issue, state["draft"], state["feedback"], today, model_stamp)

    print("No topic was approved this run.")
    return 0


def main() -> None:
    sys.exit(run(dict(os.environ)))
