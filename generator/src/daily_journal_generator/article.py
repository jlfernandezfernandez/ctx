"""Builds, validates and writes the article markdown file.

Frontmatter is built programmatically (not by the LLM) so the Astro
content schema is always satisfied.
"""
import re
import unicodedata
from datetime import date
from pathlib import Path

MIN_WORDS = 1000  # target is 2500-3500; below 1000 means generation went wrong


class ValidationError(Exception):
    pass


def slugify(title: str) -> str:
    norm = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    norm = re.sub(r"[^a-z0-9]+", "-", norm.lower())
    return norm.strip("-")


def validate_body(body: str) -> None:
    if body.lstrip().startswith("---"):
        raise ValidationError("Body contains leftover frontmatter")
    words = len(body.split())
    if words < MIN_WORDS:
        raise ValidationError(f"Body too short: {words} words (min {MIN_WORDS})")


def make_description(body: str) -> str:
    for paragraph in body.split("\n\n"):
        text = paragraph.strip()
        if not text or text.startswith("#") or text.startswith("```"):
            continue
        text = re.sub(r"[*_`]", "", text)
        text = re.sub(r"\s+", " ", text)
        return text[:200].strip()
    return ""


def _yaml_str(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_article(
    output_dir: str,
    pub_date: date,
    slug: str,
    title: str,
    description: str,
    tags: list[str],
    body: str,
) -> str:
    tags_yaml = "[" + ", ".join(_yaml_str(t) for t in tags) + "]"
    frontmatter = (
        "---\n"
        f"title: {_yaml_str(title)}\n"
        f"description: {_yaml_str(description)}\n"
        f"pubDate: {pub_date.isoformat()}\n"
        f"tags: {tags_yaml}\n"
        "---\n\n"
    )
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{pub_date.isoformat()}-{slug}.md"
    path.write_text(frontmatter + body.strip() + "\n", encoding="utf-8")
    return str(path)
