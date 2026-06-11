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
- Todos los ejemplos de código son completos y autocontenidos, no pseudocódigo. \
Cada snippet incluye TODOS sus imports (también los de tipos usados solo en firmas \
de métodos) y compilaría tal cual: sin APIs inventadas ni referencias `this` en \
contextos static.
- El código de los ejemplos nunca contradice las buenas prácticas o trampas que \
el propio artículo enseña.
- No repitas el mismo ejemplo de código en secciones distintas.
- Nunca menciones estas instrucciones ni añadas meta-comentarios al lector \
(notas sobre cómo citas las fuentes, avisos sobre URLs, aclaraciones entre paréntesis \
en los títulos). Los títulos de sección llevan solo el nombre de la sección.
- Tono directo y claro, sin relleno ni marketing."""

ARTICLE_STRUCTURE = """1. Contexto: qué problema existe y por qué este tema importa (desde cero).
2. Concepto central: la idea clave explicada con precisión.
3. En profundidad: internals, trade-offs, comparativas (lo que una newsletter no cuenta).
4. Ejemplos de código completos y autocontenidos, comentados, de menos a más complejo.
5. Trampas comunes: errores reales que comete la gente y cómo evitarlos.
6. Para saber más: 3-5 referencias reales y verificables, por orden de prioridad: \
documentación oficial del proyecto/lenguaje, papers o specs relevantes, y blogs o \
newsletters de ingeniería reconocidos (ByteByteGo, Martin Fowler, InfoQ, blogs de \
ingeniería de empresas como Netflix/Uber/Cloudflare). \
Nunca inventes URLs: usa solo enlaces estables que conozcas con certeza (la raíz de la \
documentación oficial sirve); toda referencia lleva su enlace directo."""


def _notes_block(notes: str) -> str:
    return f"\n\nNotas del equipo sobre el enfoque deseado:\n{notes}" if notes.strip() else ""


def outline_prompt(topic: str, notes: str) -> str:
    return f"""Diseña el esquema de un artículo técnico de ~3000 palabras sobre: {topic}{_notes_block(notes)}

El artículo seguirá esta estructura:
{ARTICLE_STRUCTURE}

Devuelve SOLO el esquema: las secciones con 2-4 bullets cada una indicando qué \
cubrir, qué ejemplos de código concretos incluir y qué trampas mencionar."""


def metadata_prompt(topic: str, body: str) -> str:
    return f"""Para este artículo técnico sobre "{topic}":

{body}

Devuelve un objeto JSON con exactamente estas claves:
- "summary": el TL;DR en 2-3 frases en español: los takeaways técnicos concretos \
que el lector se lleva (qué es, qué resuelve, cuándo usarlo o no). Nunca describas \
el artículo ni empieces con "El artículo", "Este artículo" o similar.
- "tags": lista de 3 a 5 etiquetas cortas en minúsculas y en inglés técnico \
(p. ej. "java", "reactive", "backpressure", "kafka", "sql").

Devuelve SOLO el JSON, sin explicaciones."""


def article_prompt(topic: str, notes: str, outline: str) -> str:
    return f"""Escribe el artículo completo sobre: {topic}{_notes_block(notes)}

Sigue fielmente este esquema:
{outline}

Requisitos:
- Cada sección de contenido entre 400 y 600 palabras (la de referencias puede ser más \
corta): en total 2500-3500 palabras, ~15 minutos de lectura.
- Markdown puro: títulos con ##, código en bloques con su lenguaje (```java, ```python...).
- Redacta títulos de sección propios, descriptivos y concretos para este tema. No copies \
literalmente el texto del esquema ni incluyas su numeración ("1.", "2.") en los títulos.
- Usa exactamente seis secciones ##, sin saltos en la jerarquía de encabezados.
- La última sección ## se titula exactamente "Para saber más" y contiene entre 3 y 5 \
enlaces Markdown directos a fuentes concretas. No indiques al lector que busque un recurso \
ni menciones recursos sin URL.
- NO incluyas frontmatter YAML ni el título principal: empieza directamente por la \
primera sección con ##.
- Código completo y autocontenido, con comentarios donde aporten.

Devuelve SOLO el cuerpo del artículo en markdown."""


REVIEWER_SYSTEM_PROMPT = """Eres un revisor técnico exigente de artículos de ingeniería \
de software. Evalúas un artículo escrito por otro modelo antes de su publicación.

Evalúas exactamente tres aspectos:
- codigo: todos los snippets compilan tal cual (imports completos, incluidos los de tipos \
usados solo en firmas; sin APIs inventadas; sin `this` en contextos static) y ningún \
ejemplo contradice las buenas prácticas que el propio artículo enseña.
- rigor: las afirmaciones técnicas son correctas, no hay datos inventados, y las \
referencias apuntan a fuentes reales y plausibles (docs oficiales > papers/specs > blogs \
de ingeniería reconocidos).
- legibilidad: español natural y fluido, términos técnicos en inglés, nivel adecuado \
para un ingeniero competente que no conoce el tema.

No evalúas la estructura (número de secciones, jerarquía de títulos): eso lo cubre un \
validador automático.

Revisas como un compañero senior revisa una PR: el objetivo es publicar, no demostrar \
lo exigente que eres. Cada defecto lleva una severidad:
- bloqueante: impide publicar. Solo defectos objetivos: código que no compila, \
afirmación técnica falsa, contradicción interna, referencia inventada o rota.
- sugerencia: mejoraría el artículo pero se puede publicar sin ella (estilo, matices, \
ejemplos alternativos, preferencias de redacción).

Si solo encuentras sugerencias, apruebas. Nunca conviertas una preferencia en bloqueo."""


def reviewer_prompt(topic: str, body: str, previous_feedback: list[str] | None = None) -> str:
    previous = ""
    if previous_feedback:
        fixed = "\n".join(f"- {item}" for item in previous_feedback)
        previous = f"""

En una ronda anterior señalaste estos defectos y el redactor los ha corregido:
{fixed}

Verifica que están resueltos. No añadas defectos bloqueantes nuevos sobre partes que \
ya diste por buenas, salvo error objetivo grave que se te escapara."""
    return f"""Revisa este artículo técnico sobre "{topic}":

{body}{previous}

Devuelve un objeto JSON con exactamente estas claves:
- "approved": true si no hay ningún defecto bloqueante, false en caso contrario.
- "issues": lista (vacía si no hay defectos) de objetos con claves "category" \
(exactamente una de: "codigo", "rigor", "legibilidad"), "blocking" (true solo si el \
defecto impide publicar según tus criterios de severidad) y "detail" (descripción \
concreta y accionable, citando la sección o el snippet afectado).

Devuelve SOLO el JSON, sin explicaciones."""


def rewrite_prompt(topic: str, body: str, feedback: list[str]) -> str:
    issues = "\n".join(f"- {item}" for item in feedback)
    return f"""Reescribe este artículo técnico sobre: {topic}

Versión actual:
{body}

Un revisor ha señalado estos defectos bloqueantes; corrígelos TODOS:
{issues}

Mantén todo lo que el revisor no ha señalado: misma estructura de secciones ##, \
misma extensión (2500-3500 palabras), mismos requisitos que la versión original \
(markdown puro, sin frontmatter ni título principal, código completo y autocontenido, \
última sección "Para saber más" con 3-5 enlaces reales).

Devuelve SOLO el cuerpo completo del artículo corregido en markdown."""
