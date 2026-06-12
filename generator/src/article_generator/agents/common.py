"""Shared constants used across agents."""

# Tags per article: single source for the writer cap and the tag-curator prompt.
MAX_TAGS_PER_ARTICLE = 3

# Title rules shared by the writer (metadata prompt) and the triage agent so
# both improve titles with the same criteria.
TITLE_RULES = """- Si es muy corto o genérico ("Pydantic AI"), añade un subtítulo descriptivo tras ": " \
que adelante el enfoque (ej: "Introducción a Pydantic AI: structured output para LLMs").
- Si es comparativo ("X vs Y"), añade el criterio de decisión ("X vs Y: cuándo usar cada uno").
- Si es un listado ("Novedades de Java 21 a 25"), concreta los temas principales tras ": ".
- Corrige capitalización y puntuación, pero no traduzcas términos técnicos.
- Preserva la intención original; no cambies el tema.
- Si ya es bueno, devuélvelo sin cambios."""
