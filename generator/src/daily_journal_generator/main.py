"""Orchestrates one generation run: pick topic -> outline -> article -> publish."""
import os
import sys
from datetime import date

from .article import make_description, slugify, validate_body, write_article
from .github_issues import PRIORITY_LABEL, TOPIC_LABEL, IssuesClient
from .llm import LLMClient
from .prompts import SYSTEM_PROMPT, article_prompt, outline_prompt

QUEUE_LABELS = {TOPIC_LABEL, PRIORITY_LABEL}


def run(env: dict) -> int:
    issues = IssuesClient(repo=env["GITHUB_REPOSITORY"], token=env["GITHUB_TOKEN"])
    llm = LLMClient(
        base_url=env["LLM_BASE_URL"],
        api_key=env["LLM_API_KEY"],
        model=env["LLM_MODEL"],
    )
    output_dir = env.get("OUTPUT_DIR", "site/src/content/blog")
    site_url = env.get("SITE_URL", "").rstrip("/")

    issue = issues.next_topic()
    if issue is None:
        print("No pending topics; nothing to publish.")
        return 0

    topic = issue["title"]
    notes = issue.get("body") or ""
    print(f"Generating article for issue #{issue['number']}: {topic}")

    outline = llm.generate(SYSTEM_PROMPT, outline_prompt(topic, notes))
    body = llm.generate(SYSTEM_PROMPT, article_prompt(topic, notes, outline))
    validate_body(body)

    pub_date = date.today()
    slug = slugify(topic)
    tags = [l["name"] for l in issue["labels"] if l["name"] not in QUEUE_LABELS]
    path = write_article(
        output_dir=output_dir,
        pub_date=pub_date,
        slug=slug,
        title=topic,
        description=make_description(body),
        tags=tags,
        body=body,
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
