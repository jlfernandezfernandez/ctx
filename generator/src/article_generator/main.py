"""Orchestrates one generation run: pick topic -> outline -> article -> publish."""
import os
import sys
from datetime import date
from pathlib import Path

from .article import (
    ValidationError,
    make_description,
    slugify,
    validate_body,
    validate_reference_urls,
    write_article,
)
from .github_issues import SYSTEM_LABELS, IssuesClient
from .llm import LLMClient, LLMError
from .prompts import SYSTEM_PROMPT, article_prompt, metadata_prompt, outline_prompt, review_prompt

# Artifacts that GitHub issue forms inject into the body.
FORM_ARTIFACTS = ("### Notas de enfoque", "_No response_")


def clean_notes(body: str) -> str:
    for artifact in FORM_ARTIFACTS:
        body = body.replace(artifact, "")
    return body.strip()


def review_code(llm: LLMClient, body: str) -> str:
    """Second LLM pass that fixes compile errors in code blocks.

    Single-pass generation keeps producing missing imports; falls back to
    the original body if the review pass fails or mangles the article.
    """
    try:
        reviewed = llm.generate(SYSTEM_PROMPT, review_prompt(body))
        validate_body(reviewed)
    except (LLMError, ValidationError) as exc:
        print(f"Code review pass failed ({exc}); keeping original body.")
        return body
    if len(reviewed.split()) < 0.7 * len(body.split()):
        print("Code review pass shrank the article; keeping original body.")
        return body
    return reviewed


def run(env: dict) -> int:
    output_dir = env.get("OUTPUT_DIR", "site/src/content/blog")
    today = date.today()

    # One article per day, even if the workflow is dispatched again.
    existing = list(Path(output_dir).glob(f"{today.isoformat()}-*.md"))
    if existing:
        print(f"Already published today: {existing[0].name}. Nothing to do.")
        return 0

    issues = IssuesClient(repo=env["GITHUB_REPOSITORY"], token=env["GITHUB_TOKEN"])
    llm = LLMClient(
        base_url=env["LLM_BASE_URL"],
        api_key=env["LLM_API_KEY"],
        model=env["LLM_MODEL"],
    )
    site_url = env.get("SITE_URL", "").rstrip("/")

    issue = issues.next_topic()
    if issue is None:
        print("No pending topics; nothing to publish.")
        return 0

    topic = issue["title"]
    notes = clean_notes(issue.get("body") or "")
    print(f"Generating article for issue #{issue['number']}: {topic}")

    outline = llm.generate(SYSTEM_PROMPT, outline_prompt(topic, notes))
    body = llm.generate(SYSTEM_PROMPT, article_prompt(topic, notes, outline))
    validate_body(body)
    body = review_code(llm, body)
    validate_reference_urls(body)

    tags = [l["name"] for l in issue["labels"] if l["name"] not in SYSTEM_LABELS]
    summary = ""
    try:
        meta = llm.generate_json(SYSTEM_PROMPT, metadata_prompt(topic, outline))
        if isinstance(meta.get("summary"), str):
            summary = meta["summary"].strip()
        if isinstance(meta.get("tags"), list):
            for tag in meta["tags"]:
                tag = str(tag).strip().lower()
                if tag and tag not in tags:
                    tags.append(tag)
    except LLMError as exc:
        print(f"Metadata generation failed ({exc}); falling back to defaults.")

    pub_date = today
    slug = slugify(topic)
    path = write_article(
        output_dir=output_dir,
        pub_date=pub_date,
        slug=slug,
        title=topic,
        description=summary or make_description(body),
        tags=tags,
        body=body,
        summary=summary,
        issue_number=issue["number"],
        requested_by=(issue.get("user") or {}).get("login", ""),
        model=env["LLM_MODEL"],
    )
    print(f"Article written: {path}")

    link = f"{site_url}/blog/{pub_date.isoformat()}-{slug}/" if site_url else path
    issues.close_with_comment(issue["number"], f"Publicado: {link}")
    print(f"Issue #{issue['number']} closed.")
    return 0


def main() -> None:
    sys.exit(run(dict(os.environ)))
