"""Builds, validates and writes the article markdown file.

Frontmatter is built programmatically (not by the LLM) so the Astro
content schema is always satisfied.
"""
import re
import unicodedata
from datetime import date

MAX_TAGS_PER_ARTICLE = 3
MAX_WORDS_PER_ARTICLE = 1300

_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_WORD = re.compile(r"\w+")


FRONTMATTER = re.compile(r"\A(---\n.*?\n---\n+)", re.DOTALL)
_TITLE_LINE = re.compile(r'^title:\s*"(.+)"$', re.MULTILINE)
_TAGS_LINE = re.compile(r"^tags:\s*\[(.+)\]$", re.MULTILINE)


class ValidationError(Exception):
    pass


def split_frontmatter(content: str) -> tuple[str, str]:
    """(frontmatter block, body); empty frontmatter when there is none."""
    match = FRONTMATTER.match(content)
    if not match:
        return "", content
    return match.group(1), content[match.end():]


def parse_title_and_tags(content: str) -> tuple[str, list[str]]:
    """(title, tags) from the frontmatter; empty values when missing."""
    frontmatter, _ = split_frontmatter(content)
    title_match = _TITLE_LINE.search(frontmatter)
    title = title_match.group(1) if title_match else ""
    tags_match = _TAGS_LINE.search(frontmatter)
    tags = []
    if tags_match:
        tags = [t.strip().strip('"') for t in tags_match.group(1).split(",") if t.strip()]
    return title, tags


def sign_reviewer(frontmatter: str, reviewer_model: str) -> str:
    """Record which model reviewed the article, next to the writer's line."""
    if not frontmatter or "\nreviewer:" in frontmatter:
        return frontmatter
    return frontmatter.replace("\n---", f"\nreviewer: {_yaml_str(reviewer_model)}\n---", 1)


def slugify(title: str) -> str:
    norm = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    norm = re.sub(r"[^a-z0-9]+", "-", norm.lower())
    return norm.strip("-")


def validate_body(body: str) -> None:
    if body.lstrip().startswith("---"):
        raise ValidationError("Body contains leftover frontmatter")
    if not body.strip():
        raise ValidationError("Body is empty")

    _validate_headings(_heading_lines(body))
    if sum(1 for line in body.splitlines() if line.strip().startswith("```")) % 2:
        raise ValidationError("Body contains an unclosed fenced code block")


def word_count(markdown: str) -> int:
    """Count prose words in markdown, excluding frontmatter and fenced code blocks."""
    _, body = split_frontmatter(markdown)
    prose = _FENCED_CODE.sub("", body)
    return len(_WORD.findall(prose))


def _heading_lines(body: str) -> list[tuple[int, str]]:
    """(level, title) for each heading outside fenced code blocks."""
    headings = []
    in_fence = False
    for line in body.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if match:
            headings.append((len(match.group(1)), match.group(2).strip()))
    return headings


def _validate_headings(headings: list[tuple[int, str]]) -> None:
    if any(level == 1 for level, _ in headings):
        raise ValidationError("Body must not contain an H1; the layout renders the article title")

    previous_level = 1
    for level, _ in headings:
        if level > previous_level + 1:
            raise ValidationError("Heading hierarchy skips a level")
        previous_level = level


def _yaml_str(value: str) -> str:
    flat = " ".join(value.split())  # newlines would break single-line YAML
    escaped = flat.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_article(
    pub_date: date,
    title: str,
    description: str,
    tags: list[str],
    body: str,
    issue_number: int | None = None,
    requested_by: str = "",
    writer: str = "",
) -> str:
    tags_yaml = "[" + ", ".join(_yaml_str(t) for t in tags) + "]"
    issue_line = f"issue: {issue_number}\n" if issue_number else ""
    requested_line = f"requestedBy: {_yaml_str(requested_by)}\n" if requested_by else ""
    writer_line = f"writer: {_yaml_str(writer)}\n" if writer else ""
    frontmatter = (
        "---\n"
        f"title: {_yaml_str(title)}\n"
        f"description: {_yaml_str(description)}\n"
        f"date: {pub_date.isoformat()}\n"
        f"tags: {tags_yaml}\n"
        f"{issue_line}"
        f"{requested_line}"
        f"{writer_line}"
        "---\n\n"
    )
    return frontmatter + body.strip() + "\n"
