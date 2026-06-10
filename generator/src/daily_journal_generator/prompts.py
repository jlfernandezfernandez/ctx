"""Prompt builders for the two-pass article generation.

Pass 1 (outline) keeps long articles structured; single-pass long-form
output tends to lose structure and produce generic examples.
"""

SYSTEM_PROMPT = """Eres un ingeniero de software senior que escribe artículos técnicos \
en profundidad para un equipo de desarrollo experimentado pero nuevo en cada tema.

Reglas:
- Escribes en español, con los términos técnicos en inglés (no traduzcas \
"backpressure", "event loop", "consumer group", etc.).
- Partes de cero: el lector no conoce el tema, pero es un ingeniero competente.
- Llegas a profundidad real, más allá de una newsletter generalista: internals, \
trade-offs, comparativas y casos límite.
- Todos los ejemplos de código son completos y ejecutables, no pseudocódigo.
- Tono directo y claro, sin relleno ni marketing."""

ARTICLE_STRUCTURE = """1. Contexto: qué problema existe y por qué este tema importa (desde cero).
2. Concepto central: la idea clave explicada con precisión.
3. En profundidad: internals, trade-offs, comparativas (lo que una newsletter no cuenta).
4. Ejemplos de código ejecutables, comentados, de menos a más complejo.
5. Trampas comunes: errores reales que comete la gente y cómo evitarlos.
6. Para saber más: 3-5 referencias concretas (docs oficiales, papers, posts de calidad)."""


def outline_prompt(topic: str, notes: str) -> str:
    notes_block = f"\n\nNotas del equipo sobre el enfoque deseado:\n{notes}" if notes.strip() else ""
    return f"""Diseña el esquema de un artículo técnico de ~3000 palabras sobre: {topic}{notes_block}

El artículo seguirá esta estructura:
{ARTICLE_STRUCTURE}

Devuelve SOLO el esquema: las secciones con 2-4 bullets cada una indicando qué \
cubrir, qué ejemplos de código concretos incluir y qué trampas mencionar."""


def metadata_prompt(topic: str, outline: str) -> str:
    return f"""Para un artículo técnico sobre "{topic}" con este esquema:

{outline}

Devuelve un objeto JSON con exactamente estas claves:
- "summary": resumen del artículo en 2-3 frases en español (el TL;DR que se muestra al inicio).
- "tags": lista de 3 a 5 etiquetas cortas en minúsculas y en inglés técnico \
(p. ej. "java", "reactive", "backpressure", "kafka", "sql").

Devuelve SOLO el JSON, sin explicaciones."""


def article_prompt(topic: str, notes: str, outline: str) -> str:
    notes_block = f"\n\nNotas del equipo sobre el enfoque deseado:\n{notes}" if notes.strip() else ""
    return f"""Escribe el artículo completo sobre: {topic}{notes_block}

Sigue fielmente este esquema:
{outline}

Requisitos:
- Entre 2500 y 3500 palabras (~15 minutos de lectura).
- Markdown puro: títulos con ##, código en bloques con su lenguaje (```java, ```python...).
- NO incluyas frontmatter YAML ni el título principal: empieza directamente por la \
primera sección con ##.
- Código completo y ejecutable, con comentarios donde aporten.

Devuelve SOLO el cuerpo del artículo en markdown."""
