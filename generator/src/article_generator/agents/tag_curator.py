"""Tag taxonomy curator: reviews and simplifies the canonical tag list.

Runs after the publish workflow merges an article. Reads tags.json plus
recent article metadata (frontmatter only, not body) and uses the triage
LLM to merge, rename or delete tags. Commits and pushes changes directly.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from ..article import parse_title_and_tags
from ..llm import LLMClient, LLMError
from .common import MAX_TAGS_PER_ARTICLE

TAGS_FILE_PATH = Path("site/src/data/tags.json")
BLOG_DIR_PATH = Path("site/src/content/blog")
MAX_RECENT_ARTICLES = 30  # enough for the curator to see patterns
MAX_TAXONOMY_TAGS = 50  # generous safety cap; the prompt drives reduction

SYSTEM_PROMPT = f"""Eres el curador de etiquetas de Ctx, un blog técnico. Simplificas \
la taxonomía de tags para que cada tag agrupe un concepto, no una librería o feature concreta. \
Solo editas la taxonomía: los artículos ya publicados conservan sus tags.

Tu objetivo es REDUCIR el número de tags siempre que puedas. Un artículo se describe con \
2-{MAX_TAGS_PER_ARTICLE} tags como mucho: si los artículos recientes necesitan más, la taxonomía es \
demasiado específica y los tags sobrantes deben absorberse en otros más genéricos.

Reglas:
- Fusiona tags equivalentes sin piedad (ej: "raft", "kraft", "controller" → solo "kafka").
- Un tag debe representar una tecnología, lenguaje o concepto transversal, nunca un \
detalle de implementación ni un feature puntual.
- Prefieres 5 tags a 15, pero no impongas un límite artificial: si el blog cubre 8 \
tecnologías distintas, 8 tags está bien.
- Mantén los nombres de tecnología/proyecto tal cual (java, kafka, snowflake, postgresql).
- Los conceptos transversales se reutilizan entre artículos (agents, llm, reactive).
- No inventes tags que no aparezcan en los artículos.

Responde únicamente con un objeto JSON:
- "tags": lista actualizada de tags canónicos"""


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
        canonical = json.loads(TAGS_FILE_PATH.read_text())
    except (OSError, ValueError):
        canonical = []

    # Gather recent article metadata (frontmatter only, cheap).
    md_files = sorted(BLOG_DIR_PATH.glob("*.md"), reverse=True)[:MAX_RECENT_ARTICLES]
    articles = []
    for f in md_files:
        title, tags = parse_title_and_tags(f.read_text(encoding="utf-8"))
        if tags:
            articles.append({"title": title or f.stem, "tags": tags})

    if not articles:
        print("No articles found; nothing to curate.")
        return 0

    llm = LLMClient(
        base_url=env["LLM_BASE_URL"],
        api_key=env["LLM_API_KEY"],
        model=env["LLM_TRIAGE_MODEL"],
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
    new_tags = new_tags[:MAX_TAXONOMY_TAGS]

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
    TAGS_FILE_PATH.write_text(json.dumps(new_tags, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", str(TAGS_FILE_PATH)], check=True)
    subprocess.run(["git", "commit", "-m", commit_msg], check=True)
    subprocess.run(["git", "push", "origin", "main"], check=True)
    return 0


def main() -> None:
    sys.exit(run(dict(os.environ)))
