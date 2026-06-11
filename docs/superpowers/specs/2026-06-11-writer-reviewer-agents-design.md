# Spec: flujo redactor–revisor con LangGraph

**Fecha**: 2026-06-11
**Estado**: aprobado para plan de implementación

## Objetivo

Sustituir la generación lineal actual (esquema → artículo → pasada de revisión de
código con el mismo modelo) por un flujo de dos agentes con modelos distintos:
un **redactor** que escribe el artículo y un **revisor** que lo evalúa y pide
cambios hasta aprobarlo. Objetivos secundarios: aprender desarrollo de agentes
con LangGraph y mejorar la calidad antes de publicar.

## Decisiones tomadas

| Decisión | Elección |
|---|---|
| Patrón de flujo | Loop con feedback (evaluator-optimizer): el revisor no edita, emite informe; el redactor reescribe. |
| Framework | LangGraph solo para orquestación (StateGraph, nodos, aristas condicionales). Los nodos son funciones Python que usan el `LLMClient` propio — sin wrappers LangChain, repo sigue provider-agnostic. |
| Modelos | Dos instancias de `LLMClient` contra Ollama Cloud: `WRITER_MODEL` (default `deepseek-v4-pro`) y `REVIEWER_MODEL` (modelo de otra familia, a elegir del catálogo). |
| Alcance del revisor | Código (imports, compilable), rigor técnico (sin inventos, referencias plausibles) y legibilidad (español natural, nivel "vibe coders"). La estructura la cubre el validador determinista. |
| Validación determinista | `validate_body()` y `validate_reference_urls()` se mantienen como gate obligatorio. Nunca se delega a LLM lo que cubre un regex. |
| Rechazo tras N iteraciones | No se publica. Se crea draft PR con el artículo + informe, label `needs-human-review` en la issue, y el run intenta el siguiente tema (máx 2 temas por run). |
| Aprobación humana | Merge del PR = publicar (cierra la issue vía "Closes #N"). Cerrar el PR = descartar. Sin workflows de aprobación custom. |

## Grafo

```
topic ──> [writer] ──> [validate] ──> [reviewer] ──> ¿aprobado?
             ↑              │              │              │
             │   falla (cuenta iteración)  │              ├─ sí ──> publish
             └──────────────┴── feedback ──┘ no, iter<MAX │
                                                          └─ no, iter=MAX ──> draft PR
```

### Estado (TypedDict)

- `topic: str`, `notes: str` — de la issue.
- `outline: str` — generado en la primera pasada del writer.
- `draft: str` — cuerpo markdown actual.
- `feedback: list[str]` — issues acumuladas (del revisor y de fallos del validador).
- `iteration: int` — incrementa en cada vuelta al writer.
- `approved: bool` — veredicto del revisor.

### Nodos

- **writer**: primera pasada = esquema + artículo (prompts actuales). Pasadas
  siguientes = reescritura con el feedback acumulado.
- **validate**: ejecuta `validate_body()`. Si falla, el error se añade a
  `feedback` y se vuelve al writer (cuenta como iteración). Si pasa, sigue al
  reviewer.
- **reviewer**: devuelve JSON estructurado
  `{"approved": bool, "issues": [{"category": "codigo|rigor|legibilidad", "detail": str}]}`.
  Sustituye al `review_code()` actual, que se elimina.

### Routing

- reviewer aprueba → fin del grafo → publicar.
- reviewer rechaza e `iteration < MAX_REVIEW_ITERATIONS` → writer.
- reviewer rechaza e `iteration == MAX_REVIEW_ITERATIONS` → fin → draft PR.

## Fuera del grafo (flujo actual intacto)

- Selección de tema (`next_topic()`, ahora excluye también `needs-human-review`).
- `validate_reference_urls()`, metadata (summary/tags), escritura del `.md`,
  commit, cierre de issue con enlace.
- Guarda de 1 artículo/día.

## Rescate por humano (rechazo tras MAX)

1. Rama `draft/issue-N`, commit del `.md` ya generado.
2. PR contra main: descripción = informe del revisor (issues pendientes) + "Closes #N".
3. Label `needs-human-review` en la issue (la saca de la cola).
4. El run intenta el siguiente tema de la cola (máximo `MAX_TOPICS_PER_RUN = 2` temas por run, para acotar coste).
5. Humano: lee el artículo renderizado en la pestaña Files del PR. Merge =
   publicar; cerrar PR = descartar (la issue queda etiquetada).

## Configuración

| Var | Tipo | Default |
|---|---|---|
| `WRITER_MODEL` | repo var | `deepseek-v4-pro` |
| `REVIEWER_MODEL` | repo var | (a elegir, familia distinta) |
| `MAX_REVIEW_ITERATIONS` | repo var | `2` |
| `MAX_TOPICS_PER_RUN` | repo var | `2` |
| `LLM_BASE_URL`, `LLM_API_KEY` | sin cambios | — |

`LLM_MODEL` queda obsoleta; se elimina tras migrar (el frontmatter `model:` pasa
a reflejar ambos modelos, p.ej. `deepseek-v4-pro + <reviewer> (reviewer)`).

## Workflows (GH Actions)

- `generate.yml`: añadir permiso `pull-requests: write` y las nuevas vars. Resto igual.
- **Deploy**: hoy escucha `workflow_run`; el merge humano de un draft PR no lo
  dispararía. Añadir trigger `push` a main con path
  `site/src/content/blog/**`. (El gotcha de GITHUB_TOKEN no aplica: el merge lo
  hace un humano.)

## Errores

- LLM caído o respuesta vacía → run falla (como hoy).
- JSON del revisor malformado → 1 retry; si persiste, se trata como "no
  aprobado" con issue genérica (no bloquea el run).
- Fallo creando el draft PR → run falla con log claro; el artículo no se pierde
  (la rama ya está pusheada antes de abrir el PR).

## Testing

- Unit: routing del grafo (aprobado/rechazado/max iteraciones), parsing del JSON
  del revisor (válido, malformado, retry), exclusión de `needs-human-review` en
  `next_topic()`, prompt de reescritura incluye feedback acumulado.
- Los nodos se testean como funciones puras con un `LLMClient` fake — otra
  ventaja de no usar wrappers.
- Smoke manual: `workflow_dispatch` con un tema de prueba.

## Fuera de alcance (YAGNI)

- Checkpointer/persistencia de LangGraph entre runs.
- Tools para los agentes (ejecutar snippets, búsqueda web).
- Más de dos agentes, streaming, memoria conversacional.
