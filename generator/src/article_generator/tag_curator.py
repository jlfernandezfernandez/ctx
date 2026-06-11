"""Tag taxonomy curator: reviews and simplifies the canonical tag list.

Runs after the publish workflow merges an article. Reads tags.json plus
recent article metadata (frontmatter only, not body) and uses the triage
LLM to merge, rename or delete tags. Commits and pushes changes directly.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .llm import LLMClient, LLMError

TAGS_FILE = Path("site/src/data/tags.json")
BLOG_DIR = Path("site/src/content/blog")
MAX_RECENT = 10  # only the last N articles' metadata for token budget
MAX_TAGS = 40  # hard cap for the taxonomy

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---", re.DOTALL)
TAGS_LINE = re.compile(r'^tags:\s*\[(.+)\]$', re.MULTILINE)

SYSTEM_PROMPT = """Eres el curador de etiquetas de Ctx (ctx), un blog técnico. Simplificas \
la taxonomía de tags del blog para que sea útil al buscar y no se disperse.

Reglas:
- Fusiona tags semánticamente equivalentes en uno solo (ej: "apache-kafka" → "kafka").
- Elimina tags demasiado específicos si otro más genérico los cubre bien.
- No sobre-generalices: mantén tags que representen conceptos de búsqueda distintos.
- Mantén los nombres de tecnología/proyecto tal cual (java, kafka, snowflake, postgresql).
- Devuelve entre 15 y 40 tags como máximo.
- No inventes tags que no aparezcan en los artículos.

Responde únicamente con un objeto JSON:
- "tags": lista actualizada de tags canónicos"""


def _parse_tags_from_article(path: Path) -> tuple[str, list[str]]:
    text = path.read_text(encoding="utf-8")
    m = FRONTMATTER.search(text)
    if not m:
        return "", []
    fm = m.group(1)
    title_match = re.search(r'^title:\s*"(.+)"$', fm, re.MULTILINE)
    title = title_match.group(1) if title_match else path.stem
    tag_match = TAGS_LINE.search(fm)
    tags = []
    if tag_match:
        tags = [t.strip().strip('"') for t in tag_match.group(1).split(",") if t.strip()]
    return title, tags


def _build_prompt(canonical: list[str], articles: list[dict]) -> str:
    current = ", ".join(canonical) if canonical else "(ninguno)"
    lines = []
    for a in articles:
        lines.append(f'- "{a["title"]}": [{", ".join(a["tags"])}]')
    article_list = "\n".join(lines)
    return f"""Tags canónicos actuales: {current}

Tags usados en los últimos artículos:
{article_list}

Simplifica la taxonomía de tags. Devuelve SOLO el JSON."""


def run(env: dict) -> int:
    try:
        canonical = json.loads(TAGS_FILE.read_text())
    except (OSError, ValueError):
        canonical = []

    # Gather recent article metadata (frontmatter only, cheap).
    md_files = sorted(BLOG_DIR.glob("*.md"), reverse=True)[:MAX_RECENT]
    articles = []
    for f in md_files:
        title, tags = _parse_tags_from_article(f)
        if tags:
            articles.append({"title": title, "tags": tags})

    if not articles:
        print("No articles found; nothing to curate.")
        return 0

    llm = LLMClient(
        base_url=env["LLM_BASE_URL"],
        api_key=env["LLM_API_KEY"],
        model=env.get("LLM_TRIAGE_MODEL", env.get("LLM_WRITER_MODEL", "")),
        timeout=60,
    )

    try:
        result = llm.generate_json(SYSTEM_PROMPT, _build_prompt(canonical, articles))
    except LLMError as exc:
        print(f"Tag curator LLM error: {exc}")
        return 0

    new_tags = result.get("tags")
    if not isinstance(new_tags, list):
        print("Tag curator returned invalid response; skipping.")
        return 0

    new_tags = sorted(set(t.strip().lower() for t in new_tags if isinstance(t, str) and t.strip()))
    new_tags = new_tags[:MAX_TAGS]

    if new_tags == sorted(canonical):
        print("Tag taxonomy unchanged.")
        return 0

    added = set(new_tags) - set(canonical)
    removed = set(canonical) - set(new_tags)
    msg_parts = []
    if added:
        msg_parts.append(f"+{len(added)} tags ({', '.join(sorted(added))})")
    if removed:
        msg_parts.append(f"-{len(removed)} tags ({', '.join(sorted(removed))})")
    print(f"Tag taxonomy updated: {'; '.join(msg_parts)}")

    # Commit and push directly to main: pull first, write, then push.
    commit_msg = f"chore: curate tags ({'; '.join(msg_parts)})"
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
    subprocess.run(["git", "config", "user.email", "github-actions[bot]@users.noreply.github.com"], check=True)
    subprocess.run(["git", "pull", "origin", "main", "--rebase"], check=True)
    TAGS_FILE.write_text(json.dumps(new_tags, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", str(TAGS_FILE)], check=True)
    subprocess.run(["git", "commit", "-m", commit_msg], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)
    return 0


def main() -> None:
    sys.exit(run(dict(os.environ)))
