"""Writer step: pick topic -> write article -> open PR.

Exports the PR number via GITHUB_OUTPUT so the reviewer step in the same
workflow can pick it up. Topics that already have an open article PR are
skipped, so a PR waiting for a human never blocks the queue.
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

from .article import (
    make_description,
    render_article,
    slugify,
    validate_body,
    ValidationError,
)
from .github_issues import IssuesClient
from .github_prs import PRClient
from .llm import LLMClient, LLMError
from .prompts import SYSTEM_PROMPT, article_prompt, metadata_prompt, outline_prompt

FORM_ARTIFACTS = ("### Notas de enfoque", "_No response_")
TAGS_FILE = "site/src/data/tags.json"
MAX_TAGS = 5


def load_canonical_tags() -> list[str]:
    try:
        data = json.loads(Path(TAGS_FILE).read_text())
        return [t for t in data if isinstance(t, str)]
    except (OSError, ValueError):
        return []


def normalize_tags(raw: list[str]) -> list[str]:
    seen = set()
    result = []
    for tag in raw:
        tag = slugify(tag)
        if not tag or tag in seen:
            continue
        result.append(tag)
        seen.add(tag)
        if len(result) >= MAX_TAGS:
            break
    return result


def clean_notes(body: str) -> str:
    for artifact in FORM_ARTIFACTS:
        body = body.replace(artifact, "")
    return body.strip()


def collect_metadata(llm: LLMClient, topic: str, body: str, existing_tags: list[str]) -> tuple[str, str, list[str]]:
    title = topic
    tags = []
    summary = ""
    try:
        meta = llm.generate_json(SYSTEM_PROMPT, metadata_prompt(topic, body, existing_tags))
        if isinstance(meta.get("title"), str) and meta["title"].strip():
            title = meta["title"].strip()
        if isinstance(meta.get("summary"), str):
            summary = meta["summary"].strip()
        if isinstance(meta.get("tags"), list):
            for tag in meta["tags"]:
                tag = str(tag).strip().lower()
                if tag and tag not in tags:
                    tags.append(tag)
    except LLMError as exc:
        print(f"Metadata generation failed ({exc}); falling back to defaults.")
    return title, summary, tags


def export_output(env: dict, name: str, value: str) -> None:
    output_path = env.get("GITHUB_OUTPUT")
    if output_path:
        with open(output_path, "a", encoding="utf-8") as fh:
            fh.write(f"{name}={value}\n")


def run(env: dict) -> int:
    today = date.today()
    issues = IssuesClient(repo=env["GITHUB_REPOSITORY"], token=env["GITHUB_TOKEN"])
    prs = PRClient(repo=env["GITHUB_REPOSITORY"], token=env["GITHUB_TOKEN"])

    writer_model = env["LLM_WRITER_MODEL"]
    writer = LLMClient(base_url=env["LLM_BASE_URL"], api_key=env["LLM_API_KEY"], model=writer_model)

    issue = issues.next_topic(skip=prs.open_article_issue_numbers())
    if issue is None:
        print("No pending topics; nothing to publish.")
        return 0

    topic = issue["title"]
    notes = clean_notes(issue.get("body") or "")
    print(f"Generating article for issue #{issue['number']}: {topic}")

    outline = writer.generate(SYSTEM_PROMPT, outline_prompt(topic, notes))
    draft = writer.generate(SYSTEM_PROMPT, article_prompt(topic, notes, outline))

    try:
        validate_body(draft)
    except ValidationError as exc:
        print(f"Structure validation failed ({exc}); opening PR anyway for the reviewer.")

    canonical_tags = load_canonical_tags()
    title, summary, raw_tags = collect_metadata(writer, topic, draft, canonical_tags)
    tags = normalize_tags(raw_tags)
    slug = slugify(title)
    content = render_article(
        pub_date=today,
        title=title,
        description=summary or make_description(draft),
        tags=tags,
        body=draft,
        summary=summary,
        issue_number=issue["number"],
        requested_by=(issue.get("user") or {}).get("login", ""),
        writer=writer_model,
    )
    url, pr_number = prs.open_pr(
        branch=f"article/issue-{issue['number']}",
        path=f"site/src/content/blog/{today.isoformat()}-{slug}.md",
        content=content,
        title=f"article: {title}",
        body=f"Closes #{issue['number']}",
    )
    export_output(env, "pr_number", str(pr_number))
    print(f"PR #{pr_number} opened for issue #{issue['number']}: {url}")
    print(f"quality_log: issue=#{issue['number']} topic={topic} writer={writer_model} tags={tags}")
    return 0


def main() -> None:
    sys.exit(run(dict(os.environ)))
