# ctx

**https://jlfernandezfernandez.github.io/ctx/**

[![CI](https://github.com/jlfernandezfernandez/ctx/actions/workflows/ci.yml/badge.svg)](https://github.com/jlfernandezfernandez/ctx/actions/workflows/ci.yml) [![Deploy site](https://github.com/jlfernandezfernandez/ctx/actions/workflows/deploy.yml/badge.svg)](https://github.com/jlfernandezfernandez/ctx/actions/workflows/deploy.yml)

Un deep dive técnico al día. Para vibe coders que quieren entender qué pasa por debajo.

Cada día laborable, un artículo en profundidad (~15 min, 2.500-3.500 palabras, con código ejecutable) sobre un tema propuesto y votado por el equipo. Desde cero hasta donde una newsletter generalista no llega.

## Cómo funciona

1. Propón un tema con la plantilla de issue ["Proponer tema"](../../issues/new/choose). Nace en `triage`; un modelo pequeño valida que sea técnico y le asigna una categoría.
2. **Vota con 👍**: cada noche (L-V, ~6:30 Madrid) se publica el tema aceptado más votado (empate → el más antiguo). El label `priority` salta la cola.
3. El **writer** genera el artículo y abre una PR con label `needs-review`.
4. El **reviewer** evalúa código, rigor y legibilidad. Si aprueba → merge. Si no → corrige y vuelve a intentar. Si sigue sin aprobar → label `needs-human-review`.

## Agentes

| Agente | Modelo | Qué hace |
|---|---|---|
| **Triaje** | `LLM_TRIAGE_MODEL` | Valida que la propuesta sea técnica, asigna categoría |
| **Writer** | `LLM_WRITER_MODEL` | Genera esquema + artículo completo, abre PR |
| **Reviewer** | `LLM_REVIEWER_MODEL` | Evalúa el artículo, corrige si puede, merge o escalar |

El writer y reviewer usan modelos distintos para evitar sesgo. El triaje limita cada autor a 5 propuestas por día UTC.

## Estructura

- `generator/` — generador Python (LLM agnóstico vía API OpenAI-compatible)
- `site/` — web Astro (GitHub Pages)
- `.github/workflows/` — triaje, generación, revisión y despliegue

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