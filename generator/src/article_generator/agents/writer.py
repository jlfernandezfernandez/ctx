"""Writer agent: creates an article and applies reviewer feedback."""
from dataclasses import dataclass

from ..article import MAX_TAGS_PER_ARTICLE, slugify
from ..llm import LLMClient
from ..prompt import load_system_prompt


SYSTEM_PROMPT = load_system_prompt("writer")


# Everything the JSON agent derives from the body in one structured call:
# metadata (title/summary/tags) + quiz, plus room for future fields.
# ponytail: quiz is generated from the FIRST body, before review. If the reviewer
# rewrites the body heavily the quiz can drift. Upgrade path if that bites:
# move this call into _review_draft, post-approval, over the final body.
EXTRAS_SCHEMA = {
    "title": "article_extras",
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "tags": {
            "type": "array",
            "items": {"type": "string"},
        },
        "quiz": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "options": {
                        "type": "array",
                        "minItems": 4,
                        "maxItems": 4,
                        "items": {"type": "string"},
                    },
                    "correct": {"type": "integer", "minimum": 0, "maximum": 3},
                    "explanation": {"type": "string"},
                },
                "required": ["question", "options", "correct", "explanation"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["title", "summary", "tags", "quiz"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Draft:
    title: str
    summary: str
    tags: list[str]
    body: str
    quiz: list[dict]


def _notes_block(notes: str) -> str:
    if not notes.strip():
        return ""
    return f"\n\nBriefing editorial:\n<briefing>\n{notes}</briefing>"


def article_prompt(topic: str, notes: str) -> str:
    return f"""Escribe el artículo completo sobre: {topic}{_notes_block(notes)}

Formula una pregunta central y una tesis útil. Decide qué conceptos necesita el lector para seguir \
el argumento y qué detalles, ejemplos y trade-offs aportan criterio. Descarta los subtemas que solo \
convertirían el texto en un catálogo.

Requisitos:
- Markdown puro con encabezados descriptivos y bloques de código con su lenguaje.
- Sin frontmatter YAML ni título principal: empieza por la primera sección.
- 800-1200 palabras (techo duro 1300). Densidad antes que extensión.
- Profundidad suficiente para que un ingeniero pueda tomar decisiones técnicas.
- Desarrolla un argumento coherente; no recorras mecánicamente una lista de características.
- Explica los conceptos del ecosistema que sean necesarios para entender el tema.
- Incluye fuentes directas cuando aporten valor.

Devuelve SOLO el cuerpo del artículo en markdown."""


def extras_prompt(topic: str, body: str, canonical_tags: list[str]) -> str:
    taxonomy = ", ".join(canonical_tags) if canonical_tags else "(sin tags disponibles)"
    return f"""Prepara los metadatos y el quiz finales de este artículo sobre "{topic}".

<articulo>
{body}
</articulo>

Tags existentes para reutilizar: {taxonomy}

Devuelve SOLO un objeto JSON con:
- "title": título final concreto y descriptivo
- "summary": TL;DR técnico en 2-3 frases, sin empezar por "El artículo" o "Este artículo"
- "tags": entre 1 y {MAX_TAGS_PER_ARTICLE} tags
- "quiz": array de exactamente 3 objetos {{"question": "...", "options": ["...", "...", "...", "..."], "correct": 0, "explanation": "..."}}. Las preguntas exigen haber entendido el artículo y los distractores son plausibles."""


def rewrite_prompt(topic: str, body: str, feedback: list[str]) -> str:
    issues = "\n".join(f"- {item}" for item in feedback)
    return f"""Corrige este artículo técnico sobre: {topic}

<articulo>
{body}
</articulo>

Defectos que debes corregir:
{issues}

Corrige únicamente lo necesario para resolver todos los defectos. No añadas frontmatter ni título \
principal. Devuelve SOLO el cuerpo completo corregido en markdown."""


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
    body = chat_llm.generate(SYSTEM_PROMPT, article_prompt(topic, notes))
    extras = json_llm.generate_structured(
        SYSTEM_PROMPT, extras_prompt(topic, body, canonical_tags), EXTRAS_SCHEMA
    )
    title = extras["title"].strip()
    summary = extras["summary"].strip()
    tags = normalize_tags(extras["tags"], canonical_tags)
    return Draft(title=title, summary=summary, tags=tags, body=body, quiz=extras["quiz"])


def revise_article(
    llm: LLMClient, topic: str, body: str, feedback: list[str]
) -> str:
    return llm.generate(SYSTEM_PROMPT, rewrite_prompt(topic, body, feedback))
