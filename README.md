# Ctx

**https://jlfernandezfernandez.github.io/ctx/**

[![CI](https://github.com/jlfernandezfernandez/ctx/actions/workflows/ci.yml/badge.svg)](https://github.com/jlfernandezfernandez/ctx/actions/workflows/ci.yml) [![Deploy site](https://github.com/jlfernandezfernandez/ctx/actions/workflows/deploy.yml/badge.svg)](https://github.com/jlfernandezfernandez/ctx/actions/workflows/deploy.yml)

Un deep dive técnico al día. Para vibe coders que quieren entender qué pasa por debajo.

Cada día laborable, un artículo en profundidad (~15 min, 2.500-3.500 palabras, con ejemplos de código completos) sobre un tema propuesto y votado por el equipo. Desde cero hasta donde una newsletter generalista no llega.

## Cómo funciona

1. Propón un tema con la plantilla de issue ["Proponer tema"](../../issues/new/choose). Un modelo pequeño valida que sea técnico y le asigna una categoría.
2. **Vota con 👍**: cada noche (L-V, ~6:30 Madrid) se elige el tema aceptado más votado (empate → el más antiguo; el label `priority` salta la cola).
3. El **writer** genera el artículo y abre una PR, igual que lo haría un compañero.
4. El **reviewer** evalúa código, rigor y legibilidad sobre esa PR, como un compañero senior: cada defecto es **bloqueante** (código que no compila, dato falso, referencia inventada) o **sugerencia** (estilo, matices — no impiden publicar).
   - Sin bloqueantes → merge automático (las sugerencias quedan como comentario), la issue se cierra con el link y la web se despliega.
   - Con bloqueantes → comenta "cambios solicitados" en la PR y se los devuelve al **writer**, que corrige y vuelve a revisión. Máximo `MAX_REVIEW_ROUNDS` correcciones para que el reviewer no saque pegas indefinidamente.
   - Si tras agotar las rondas siguen los bloqueantes, **la PR queda abierta** con la mejor versión y los defectos comentados: una PR de artículo abierta significa "decide un humano" (mergear publica, cerrar descarta). La cola no se bloquea: al día siguiente toca el siguiente tema.

Todo el flujo vive en un único workflow ([`publish.yml`](.github/workflows/publish.yml)): writer y reviewer son pasos del mismo run y la conversación entre ambos ocurre en proceso; los comentarios y commits de la PR son el rastro visible, no el mecanismo (ni labels ni coreografía entre workflows).

## Agentes

| Agente | Modelo | Qué hace |
|---|---|---|
| **Triaje** | `LLM_TRIAGE_MODEL` | Valida que la propuesta sea técnica, asigna categoría |
| **Writer** | `LLM_WRITER_MODEL` | Genera esquema + artículo, abre PR, corrige el feedback |
| **Reviewer** | `LLM_REVIEWER_MODEL` | Evalúa la PR y decide: mergea, pide cambios o escala a humano |

El writer y el reviewer usan modelos distintos para evitar que un modelo apruebe sus propios vicios. El triaje limita cada autor a 5 propuestas por día UTC.

## Estructura

- `generator/` — generador Python (LLM agnóstico vía API OpenAI-compatible)
- `site/` — web Astro (GitHub Pages)
- `.github/workflows/` — `triage-topic` (clasifica propuestas), `publish` (writer + reviewer), `deploy` (Pages), `ci` (tests y build)

## Configuración (Actions)

| Dónde | Nombre | Valor actual |
|---|---|---|
| Secret | `LLM_API_KEY` | API key del proveedor |
| Variable | `LLM_BASE_URL` | `https://ollama.com/v1` |
| Variable | `LLM_WRITER_MODEL` | `deepseek-v4-pro` |
| Variable | `LLM_REVIEWER_MODEL` | `minimax-m3` |
| Variable | `LLM_TRIAGE_MODEL` | `deepseek-v4-flash` |
| Variable | `MAX_REVIEW_ROUNDS` | `2` |

Cambiar de proveedor o modelo = cambiar esas variables, cero código.

## Desarrollo local

```bash
cd generator && pip install -e '.[dev]' && pytest
cd site && npm install && npm run dev
```

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md). La forma más útil: proponer buenos temas con notas de enfoque, y votar 👍 los que te interesan.
