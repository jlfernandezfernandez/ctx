# Daily Journal — Diseño MVP

**Fecha:** 2026-06-10
**Estado:** aprobado

## Problema

Equipo de desarrollo que quiere aprender un concepto técnico al día (~15 min de lectura) sin depender de newsletters genéricas que nunca se leen. Los temas los propone el propio equipo y los artículos profundizan más que una newsletter generalista: parten de cero, llegan a conceptos avanzados e incluyen ejemplos de código.

## Decisiones de producto

- **Formato:** un artículo al día, ~15 min de lectura (2.500–3.500 palabras), en español con términos técnicos en inglés.
- **Cadencia:** lunes a viernes. Fines de semana no se publica (hábito ligado a jornada laboral).
- **Temas:** los propone el equipo (o cualquier contribuidor externo). Ejemplos: Java 21/25, Project Reactor, WebFlux, SSE vs HTTP, vistas materializadas en Snowflake, Kafka sin ZooKeeper, patrones, LeetCode, data engineering.
- **Sin tracking de lectura en el MVP** (v2).
- **Repo y web públicos.** Plan GitHub gratis: Pages requiere repo público. El contenido no es sensible y lo público habilita contribución externa.

## Arquitectura

Tres piezas, cero servidores, coste cero:

```
GitHub Issues (label "topic")            ← el equipo propone temas
        │
GitHub Action nocturna (cron L-V, ~6:00 Europe/Madrid)
  └─ generador Python:
       1. coge la issue con label "topic" más antigua (label "priority" salta cola)
       2. genera el artículo vía LLM en dos pasadas (esquema → redacción)
       3. valida el resultado (frontmatter, longitud mínima)
       4. escribe content/articles/YYYY-MM-DD-slug.md
       5. commit + push, cierra la issue con link al artículo
        │
Astro build → GitHub Pages               ← web estática del equipo
```

## Componentes

### 1. Generador (`generator/`, Python)

- **Capa LLM agnóstica:** interfaz mínima propia (`generate(prompt) -> str`) con un adaptador para API OpenAI-compatible. Ollama Cloud, OpenAI, Anthropic (vía gateway), etc. exponen este formato → cambiar de proveedor = cambiar `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` en los secrets del repo. Sin LiteLLM ni LangChain: es una llamada HTTP.
- **Generación en dos pasadas:**
  1. *Esquema:* el LLM produce la estructura del artículo (secciones, ejemplos a incluir, trampas comunes).
  2. *Redacción:* el LLM escribe el artículo completo siguiendo el esquema.
  Motivo: artículos largos en una sola pasada pierden estructura y los ejemplos se vuelven genéricos.
- **Estructura fija del artículo:** contexto desde cero → concepto central → profundidad (más allá de newsletter generalista) → ejemplos de código ejecutables → trampas comunes → referencias para profundizar.
- **Notas de enfoque:** el cuerpo de la issue se inyecta en el prompt (p. ej. "no entendemos el paradigma reactivo, compáralo con código imperativo").
- **Validación antes de publicar:** frontmatter completo (título, fecha, tema, tags) y longitud mínima. Si falla: la Action falla visiblemente, no se publica nada y la issue queda abierta para reintento.

### 2. Web (`site/`, Astro)

- Partir del starter de blog oficial de Astro; sin diseño a medida en el MVP.
- Portada = artículo de hoy. Archivo navegable por fecha y tags.
- Syntax highlighting con Shiki (nativo de Astro).
- Deploy a GitHub Pages mediante Action en cada push a `main`.

### 3. Cola de temas (GitHub Issues)

- Issue con label `topic` = tema pendiente. Label `priority` = saltar cola.
- Issue cerrada con link al artículo = publicado.
- Temas grandes: el equipo los parte a mano en varias issues ("Reactor I: paradigma", "Reactor II: operadores"). Sin series automáticas.
- Sin temas pendientes: el job termina sin publicar (no es error).

### 4. Workflow (`.github/workflows/`)

- `generate.yml`: cron L-V + `workflow_dispatch` para lanzamiento manual (pruebas, regenerar, recuperar un día fallido).
- `deploy.yml`: build de Astro y publicación en Pages en cada push a `main`.

## Seguridad (repo público)

- `LLM_API_KEY` y demás credenciales **solo** en GitHub Actions Secrets. Nunca en código, commits ni archivos del repo.
- `.env` en `.gitignore` para desarrollo local.
- Los workflows disparados por PRs de forks no reciben secrets (comportamiento por defecto de GitHub): los contribuidores externos no pueden exfiltrar la key.
- No imprimir la key en logs (GitHub además la enmascara).

## Manejo de errores

| Fallo | Comportamiento |
|---|---|
| LLM no responde / error HTTP | Action falla, issue queda abierta, reintento al día siguiente o manual |
| Artículo inválido (validación) | Igual: no se publica basura |
| Sin temas en cola | Job termina OK sin publicar |
| Build de Astro falla | Deploy no se ejecuta; el artículo ya commiteado se publica al arreglar |

## Testing

- Generador: tests unitarios de selección de issue, validación de artículo y construcción de prompts (LLM mockeado).
- Adaptador LLM: test contra respuesta OpenAI-compatible simulada.
- Web: build de Astro en CI como smoke test.

## Fuera del MVP (v2+)

- Tracking de lectura ("lo estudié") y vista de equipo.
- Quiz de comprensión generado por LLM.
- Playground de código ejecutable.
- Aviso diario por Slack/email con link al artículo.
- Formulario web para proponer temas.
- Multi-equipo / multi-tenant.
- El LLM propone temas cuando la cola está vacía.
