"""Orchestrates one generation run: pick topic -> outline -> article -> publish."""
import os
import sys
from datetime import date
from pathlib import Path

from .article import make_description, slugify, validate_body, write_article
from .github_issues import PRIORITY_LABEL, TOPIC_LABEL, IssuesClient
from .llm import LLMClient, LLMError
from .prompts import SYSTEM_PROMPT, article_prompt, metadata_prompt, outline_prompt

QUEUE_LABELS = {TOPIC_LABEL, PRIORITY_LABEL}

# Artifacts that GitHub issue forms inject into the body.
FORM_ARTIFACTS = ("### Notas de enfoque", "_No response_")


def clean_notes(body: str) -> str:
    for artifact in FORM_ARTIFACTS:
        body = body.replace(artifact, "")
    return body.strip()


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

    tags = [l["name"] for l in issue["labels"] if l["name"] not in QUEUE_LABELS]
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
    )
    print(f"Article written: {path}")

    if site_url:
        link = f"{site_url}/blog/{pub_date.isoformat()}-{slug}/"
    else:
        link = path
    issues.close_with_comment(issue["number"], f"Publicado: {link}")
    print(f"Issue #{issue['number']} closed.")
    return 0


def main() -> None:
    sys.exit(run(dict(os.environ)))
