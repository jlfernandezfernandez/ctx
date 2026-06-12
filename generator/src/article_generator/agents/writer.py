"""Writer agent: creates an article and applies reviewer feedback."""
from dataclasses import dataclass

from ..article import MAX_TAGS_PER_ARTICLE, make_description, slugify
from ..llm import LLMClient, LLMError
from ..prompt import load_system_prompt


SYSTEM_PROMPT = load_system_prompt("writer")


@dataclass(frozen=True)
class Draft:
    title: str
    summary: str
    tags: list[str]
    body: str


def _notes_block(notes: str) -> str:
    if not notes.strip():
        return ""
    return f"\n\nBriefing editorial:\n<briefing>\n{notes}\n</briefing>"


def outline_prompt(topic: str, notes: str) -> str:
    return f"""Diseña el mejor esquema para un artículo técnico profundo sobre: {topic}{_notes_block(notes)}

Decide qué necesita este tema para explicarse con claridad: fundamentos, internals, trade-offs, \
ejemplos completos, trampas reales y fuentes útiles.

Devuelve SOLO el esquema con secciones y bullets concretos."""


def article_prompt(topic: str, notes: str, outline: str) -> str:
    return f"""Escribe el artículo completo sobre: {topic}{_notes_block(notes)}

Usa este esquema como guía, adaptándolo si mejora el resultado:
<esquema>
{outline}
</esquema>

Requisitos:
- Markdown puro con encabezados descriptivos y bloques de código con su lenguaje.
- Sin frontmatter YAML ni título principal: empieza por la primera sección.
- Profundidad suficiente para que un ingeniero pueda tomar decisiones técnicas.
- Incluye fuentes directas cuando aporten valor.

Devuelve SOLO el cuerpo del artículo en markdown."""


def metadata_prompt(topic: str, body: str, canonical_tags: list[str]) -> str:
    taxonomy = ", ".join(canonical_tags) if canonical_tags else "(sin tags disponibles)"
    return f"""Prepara los metadatos finales de este artículo sobre "{topic}".

<articulo>
{body}
</articulo>

Tags existentes, reutilízalos siempre que representen correctamente el tema: {taxonomy}

Devuelve SOLO un objeto JSON con:
- "title": título final concreto y descriptivo
- "summary": TL;DR técnico en 2-3 frases, sin empezar por "El artículo" o "Este artículo"
- "tags": el menor número posible de tags, normalmente uno y nunca más de \
{MAX_TAGS_PER_ARTICLE}. Crea un único tag nuevo y general solo si ninguno existente encaja"""


def rewrite_prompt(topic: str, body: str, feedback: list[str], attempt: int = 1) -> str:
    issues = "\n".join(f"- {item}" for item in feedback)
    retry = ""
    if attempt >= 2:
        retry = "\nEl intento anterior produjo Markdown inválido. Conserva intacto todo lo no afectado."
    return f"""Corrige este artículo técnico sobre: {topic}

<articulo>
{body}
</articulo>

Defectos que debes corregir:
{issues}

Corrige únicamente lo necesario para resolver todos los defectos. No añadas frontmatter ni título \
principal. Devuelve SOLO el cuerpo completo corregido en markdown.{retry}"""


def normalize_tags(raw: list[str], canonical_tags: list[str]) -> list[str]:
    canonical = set(canonical_tags)
    new_tag_added = False
    result = []
    for tag in raw:
        normalized = slugify(str(tag))
        if not normalized or normalized in result:
            continue
        if normalized not in canonical:
            if new_tag_added:
                continue
            new_tag_added = True
        result.append(normalized)
        if len(result) == MAX_TAGS_PER_ARTICLE:
            break
    return result


def write_article(llm: LLMClient, topic: str, notes: str, canonical_tags: list[str]) -> Draft:
    outline = llm.generate(SYSTEM_PROMPT, outline_prompt(topic, notes))
    body = llm.generate(SYSTEM_PROMPT, article_prompt(topic, notes, outline))
    title, summary, tags = topic, make_description(body), []
    try:
        metadata = llm.generate_json(SYSTEM_PROMPT, metadata_prompt(topic, body, canonical_tags))
        if isinstance(metadata.get("title"), str) and metadata["title"].strip():
            title = metadata["title"].strip()
        if isinstance(metadata.get("summary"), str) and metadata["summary"].strip():
            summary = metadata["summary"].strip()
        if isinstance(metadata.get("tags"), list):
            tags = normalize_tags(metadata["tags"], canonical_tags)
    except LLMError as exc:
        print(f"Metadata generation failed ({exc}); falling back to defaults.")
    return Draft(title=title, summary=summary, tags=tags, body=body)


def revise_article(
    llm: LLMClient, topic: str, body: str, feedback: list[str], attempt: int = 1
) -> str:
    return llm.generate(SYSTEM_PROMPT, rewrite_prompt(topic, body, feedback, attempt))
