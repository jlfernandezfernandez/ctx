"""Builds, validates and writes the article markdown file.

Frontmatter is built programmatically (not by the LLM) so the Astro
content schema is always satisfied.
"""
import re
import unicodedata
from datetime import date
from pathlib import Path

import requests

MIN_WORDS = 1000  # target is 2500-3500; below 1000 means generation went wrong
EXPECTED_H2_COUNT = 6
REFERENCE_HEADING = re.compile(r"(para saber m[aá]s|referencias|fuentes)", re.IGNORECASE)
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\((https?://[^)\s]+)\)")
VAGUE_REFERENCE = re.compile(
    r"\b(buscar(?:lo)? en|disponible en|enlace pendiente|url pendiente)\b",
    re.IGNORECASE,
)


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

    headings = _parse_headings(body)
    _validate_headings(headings)
    _validate_code_fences(body)
    _validate_references(body, headings)


def _heading_lines(body: str) -> list[tuple[int, int, str]]:
    """(line index, level, title) for each heading outside fenced code blocks."""
    headings = []
    in_fence = False
    for index, line in enumerate(body.splitlines()):
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.+)$", line)
        if match:
            headings.append((index, len(match.group(1)), match.group(2).strip()))
    return headings


def _parse_headings(body: str) -> list[tuple[int, str]]:
    return [(level, title) for _, level, title in _heading_lines(body)]


def _validate_headings(headings: list[tuple[int, str]]) -> None:
    if any(level == 1 for level, _ in headings):
        raise ValidationError("Body must not contain an H1; the layout renders the article title")

    h2s = [title for level, title in headings if level == 2]
    if len(h2s) != EXPECTED_H2_COUNT:
        raise ValidationError(f"Body must contain exactly {EXPECTED_H2_COUNT} H2 sections")
    if any(re.match(r"^\d+[.)]\s+", title) for title in h2s):
        raise ValidationError("H2 section titles must not be numbered")

    previous_level = 1
    for level, _ in headings:
        if level > previous_level + 1:
            raise ValidationError("Heading hierarchy skips a level")
        previous_level = level


def _validate_code_fences(body: str) -> None:
    if sum(1 for line in body.splitlines() if line.strip().startswith("```")) % 2:
        raise ValidationError("Body contains an unclosed fenced code block")


def _validate_references(body: str, headings: list[tuple[int, str]]) -> None:
    h2s = [title for level, title in headings if level == 2]
    reference_index = next(
        (index for index, title in enumerate(h2s) if REFERENCE_HEADING.search(title)),
        None,
    )
    if reference_index != len(h2s) - 1:
        raise ValidationError("The final H2 section must contain references")
    references = _reference_urls(body)
    if not 3 <= len(references) <= 5:
        raise ValidationError("References section must contain 3 to 5 linked sources")
    if VAGUE_REFERENCE.search(_reference_section(body)):
        raise ValidationError("References section contains vague or incomplete references")


def _reference_section(body: str) -> str:
    h2_lines = [index for index, level, _ in _heading_lines(body) if level == 2]
    if not h2_lines:
        return body
    return "\n".join(body.splitlines()[h2_lines[-1] + 1 :])


def _reference_urls(body: str) -> list[str]:
    return list(dict.fromkeys(MARKDOWN_LINK.findall(_reference_section(body))))


def validate_reference_urls(body: str, timeout: int = 15) -> None:
    """Fail publication when a linked source cannot be reached.

    Each URL gets one retry. A persistent timeout only warns — a slow source
    must not block the daily article — but an unreachable host (likely an
    invented URL) or a 4xx still fails.
    """
    for url in _reference_urls(body):
        for retry_left in (True, False):
            try:
                response = requests.head(url, allow_redirects=True, timeout=timeout)
                if response.status_code == 405 or response.status_code >= 500:
                    response = requests.get(url, allow_redirects=True, timeout=timeout, stream=True)
            except requests.Timeout:
                if not retry_left:
                    print(f"Warning: reference URL timed out, skipping check: {url}")
                continue
            except requests.RequestException as exc:
                if not retry_left:
                    raise ValidationError(f"Reference URL is unreachable: {url}") from exc
                continue
            if response.status_code >= 400 and response.status_code not in (401, 403):
                raise ValidationError(f"Reference URL returned {response.status_code}: {url}")
            break


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
    flat = " ".join(value.split())  # newlines would break single-line YAML
    escaped = flat.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def write_article(
    output_dir: str,
    pub_date: date,
    slug: str,
    title: str,
    description: str,
    tags: list[str],
    body: str,
    summary: str = "",
    issue_number: int | None = None,
    requested_by: str = "",
    model: str = "",
) -> str:
    tags_yaml = "[" + ", ".join(_yaml_str(t) for t in tags) + "]"
    summary_line = f"summary: {_yaml_str(summary)}\n" if summary else ""
    issue_line = f"issue: {issue_number}\n" if issue_number else ""
    requested_line = f"requestedBy: {_yaml_str(requested_by)}\n" if requested_by else ""
    model_line = f"model: {_yaml_str(model)}\n" if model else ""
    frontmatter = (
        "---\n"
        f"title: {_yaml_str(title)}\n"
        f"description: {_yaml_str(description)}\n"
        f"pubDate: {pub_date.isoformat()}\n"
        f"tags: {tags_yaml}\n"
        f"{summary_line}"
        f"{issue_line}"
        f"{requested_line}"
        f"{model_line}"
        "---\n\n"
    )
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{pub_date.isoformat()}-{slug}.md"
    path.write_text(frontmatter + body.strip() + "\n", encoding="utf-8")
    return str(path)
