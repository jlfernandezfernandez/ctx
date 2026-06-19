"""Writer agent: creates an article and applies reviewer feedback."""
from dataclasses import dataclass

from ..article import MAX_TAGS_PER_ARTICLE, slugify
from ..llm import LLMClient
from ..prompt import load_system_prompt


SYSTEM_PROMPT = load_system_prompt("writer")


METADATA_SCHEMA = {
    "title": "article_metadata",
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["title", "summary", "tags"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Draft:
    title: str
    summary: str
    tags: list[str]
    body: str


def _notes_block(notes: str) -> str:
    if not notes.strip():
        return ""
    return f"\n\nBriefing editorial:\n<briefing>\n{notes}</briefing>"


def outline_prompt(topic: str, notes: str) -> str:
    return f"""Diseña el mejor esquema para un artículo técnico profundo sobre: {topic}{_notes_block(notes)}

Formula la pregunta central que resolverá el artículo y la tesis que defenderá. Decide qué conceptos \
necesita el lector para seguir el argumento y qué detalles, ejemplos y trade-offs aportan criterio. \
Descarta los subtemas que solo convertirían el texto en un catálogo.

Devuelve SOLO la tesis y el esquema con secciones y bullets concretos."""


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
- Desarrolla un argumento coherente; no recorras mecánicamente una lista de características.
- Explica los conceptos del ecosistema que sean necesarios para entender el tema.
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
- "tags": entre 1 y {MAX_TAGS_PER_ARTICLE} tags que representen ejes centrales del artículo. \
Incluye cada tag solo si alguien interesado en él agradecería encontrar este artículo. \
Crea como máximo un tag nuevo, general y reutilizable, solo cuando ningún tag existente \
represente ese eje central"""


def rewrite_prompt(topic: str, body: str, feedback: list[str], attempt: int = 1) -> str:
    issues = "\n".join(f"- {item}" for item in feedback)
    retry = "\nEl intento anterior produjo Markdown inválido. Conserva intacto todo lo no afectado." if attempt >= 2 else ""
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


def write_article(
    chat_llm: LLMClient,
    json_llm: LLMClient,
    topic: str,
    notes: str,
    canonical_tags: list[str],
) -> Draft:
    outline = chat_llm.generate(SYSTEM_PROMPT, outline_prompt(topic, notes))
    body = chat_llm.generate(SYSTEM_PROMPT, article_prompt(topic, notes, outline))
    metadata = json_llm.generate_structured(
        SYSTEM_PROMPT, metadata_prompt(topic, body, canonical_tags), METADATA_SCHEMA
    )
    title = metadata["title"].strip()
    summary = metadata["summary"].strip()
    tags = normalize_tags(metadata["tags"], canonical_tags)
    return Draft(title=title, summary=summary, tags=tags, body=body)


def revise_article(
    llm: LLMClient, topic: str, body: str, feedback: list[str], attempt: int = 1
) -> str:
    return llm.generate(SYSTEM_PROMPT, rewrite_prompt(topic, body, feedback, attempt))
