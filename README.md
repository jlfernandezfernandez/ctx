# Ctx

**https://jlfernandezfernandez.github.io/ctx/**

[![CI](https://github.com/jlfernandezfernandez/ctx/actions/workflows/ci.yml/badge.svg)](https://github.com/jlfernandezfernandez/ctx/actions/workflows/ci.yml) [![Deploy site](https://github.com/jlfernandezfernandez/ctx/actions/workflows/deploy.yml/badge.svg)](https://github.com/jlfernandezfernandez/ctx/actions/workflows/deploy.yml)

Un deep dive técnico al día. Para vibe coders que quieren entender qué pasa por debajo.

Cada día laborable, un artículo técnico en profundidad sobre un tema propuesto y votado por el equipo. Desde cero hasta donde una newsletter generalista no llega.

## Cómo funciona

1. Propón un tema con la plantilla de issue ["Proponer tema"](../../issues/new/choose). El agente de **triaje** modera spam y convierte las notas en un briefing útil; ante la duda, decide una persona.
2. **Vota con 👍**: cada noche (L-V, ~6:30 Madrid) se elige el tema aceptado más votado (empate → el más antiguo; el label `priority` salta la cola).
3. El **writer** decide la estructura, genera título, resumen, tags y artículo, y abre una PR antes de la revisión.
4. El **reviewer** evalúa código, rigor y legibilidad sobre esa PR: cada defecto es **bloqueante** (código incorrecto, dato falso o desactualizado, referencia inventada, carencia importante) o **sugerencia** (mejora no imprescindible).
   - Sin bloqueantes → merge automático (las sugerencias quedan como comentario), la issue se cierra con el link y la web se despliega.
   - Con bloqueantes → comenta "cambios solicitados" en la PR y se los devuelve al **writer**, que corrige y vuelve a revisión. Máximo `MAX_REVIEW_ROUNDS` correcciones para que el reviewer no saque pegas indefinidamente.
   - Si tras agotar las rondas siguen los bloqueantes, **la PR queda abierta** con la mejor versión y los defectos comentados: una PR de artículo abierta significa "decide un humano" (mergear publica, cerrar descarta). La cola no se bloquea: al día siguiente toca el siguiente tema.

Todo el flujo vive en un único workflow ([`publish.yml`](.github/workflows/publish.yml)). Un pipeline Python conecta los agentes, valida contratos objetivos, gestiona GitHub y publica. Los agentes solo toman decisiones editoriales.

## Agentes

| Agente          | Modelo               | Qué hace                                                                                                                                       |
| --------------- | -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| **Triaje**   | `LLM_TRIAGE_MODEL`   | Acepta, rechaza o escala propuestas y prepara el briefing |
| **Writer**   | `LLM_WRITER_MODEL`   | Genera título, resumen, tags y artículo; corrige feedback |
| **Reviewer** | `LLM_REVIEWER_MODEL` | Evalúa calidad y devuelve defectos o sugerencias |

Cada agente tiene un único system prompt estático en `generator/src/article_generator/system_prompts/`. No se comparten ni interpolan reglas entre agentes. El writer y el reviewer usan modelos distintos para evitar que un modelo apruebe sus propios vicios.

El resto no son agentes: `pipeline.py` coordina rondas y GitHub; `article.py` valida Markdown, frontmatter y el máximo de tags.

## Estructura

- `generator/` — generador Python (LLM agnóstico vía API OpenAI-compatible)
- `site/` — web Astro (GitHub Pages)
- `.github/workflows/` — `triage-topic` (cura propuestas), `publish` (pipeline editorial), `deploy` (Pages), `ci` (tests y build)
- `site/src/data/tags.json` — taxonomía canónica: el writer reutiliza tags existentes siempre que encajen y el pipeline añade a la misma PR un tag nuevo solo cuando hace falta

Los únicos labels requeridos por el producto son `triage`, `topic`, `priority`, `published` y `rejected`.

## Configuración (Actions)

| Dónde    | Nombre               | Valor actual            |
| -------- | -------------------- | ----------------------- |
| Secret   | `LLM_API_KEY`        | API key del proveedor   |
| Variable | `LLM_BASE_URL`       | `https://ollama.com/v1` |
| Variable | `LLM_WRITER_MODEL`   | `deepseek-v4-pro`       |
| Variable | `LLM_REVIEWER_MODEL` | `minimax-m3`            |
| Variable | `LLM_TRIAGE_MODEL`   | `deepseek-v4-flash`     |
| Variable | `MAX_REVIEW_ROUNDS`  | `2`                     |

Cambiar de proveedor o modelo = cambiar esas variables, cero código.

## Desarrollo local

Requiere [Node.js](https://nodejs.org) y [uv](https://docs.astral.sh/uv/) (`brew install uv`).

### Generador (Python)

```bash
cd generator
uv run --extra dev pytest
```

### Web (Astro)

```bash
cd site
npm install
npm run dev
```

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md). La forma más útil: proponer buenos temas con notas de enfoque, y votar 👍 los que te interesan.
