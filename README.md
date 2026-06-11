# Ctx

**https://jlfernandezfernandez.github.io/ctx/**

[![CI](https://github.com/jlfernandezfernandez/ctx/actions/workflows/ci.yml/badge.svg)](https://github.com/jlfernandezfernandez/ctx/actions/workflows/ci.yml) [![Deploy site](https://github.com/jlfernandezfernandez/ctx/actions/workflows/deploy.yml/badge.svg)](https://github.com/jlfernandezfernandez/ctx/actions/workflows/deploy.yml)

Un deep dive técnico al día. Para vibe coders que quieren entender qué pasa por debajo.

Cada día laborable, un artículo en profundidad (~15 min, 2.500-3.500 palabras, con código ejecutable) sobre un tema propuesto y votado por el equipo. Desde cero hasta donde una newsletter generalista no llega.

## Cómo funciona

1. Propón un tema con la plantilla de issue ["Proponer tema"](../../issues/new/choose). Un modelo pequeño valida que sea técnico y le asigna una categoría.
2. **Vota con 👍**: cada noche (L-V, ~6:30 Madrid) se elige el tema aceptado más votado (empate → el más antiguo; el label `priority` salta la cola).
3. El **writer** genera el artículo y abre una PR, igual que lo haría un compañero.
4. El **reviewer** evalúa código, rigor y legibilidad sobre esa PR:
   - Aprueba → merge automático, la issue se cierra con el link y la web se despliega.
   - Rechaza → corrige el artículo y lo vuelve a revisar. Si la corrección tampoco pasa, comenta los defectos pendientes y **deja la PR abierta**: una PR de artículo abierta significa "decide un humano" (mergear publica, cerrar descarta). Mientras tanto la cola no se bloquea: al día siguiente toca el siguiente tema.

Todo el flujo vive en un único workflow ([`publish.yml`](.github/workflows/publish.yml)): writer y reviewer son dos pasos del mismo run, así que no hay coreografía entre workflows ni labels de control.

## Agentes

| Agente | Modelo | Qué hace |
|---|---|---|
| **Triaje** | `LLM_TRIAGE_MODEL` | Valida que la propuesta sea técnica, asigna categoría |
| **Writer** | `LLM_WRITER_MODEL` | Genera esquema + artículo completo, abre PR |
| **Reviewer** | `LLM_REVIEWER_MODEL` | Evalúa la PR, corrige si puede, mergea o escala a humano |

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

Cambiar de proveedor o modelo = cambiar esas variables, cero código.

## Desarrollo local

```bash
cd generator && pip install -e '.[dev]' && pytest
cd site && npm install && npm run dev
```

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md). La forma más útil: proponer buenos temas con notas de enfoque, y votar 👍 los que te interesan.
