# ctx

**https://jlfernandezfernandez.github.io/ctx/**

[![CI](https://github.com/jlfernandezfernandez/ctx/actions/workflows/ci.yml/badge.svg)](https://github.com/jlfernandezfernandez/ctx/actions/workflows/ci.yml)
[![Generate daily article](https://github.com/jlfernandezfernandez/ctx/actions/workflows/generate.yml/badge.svg)](https://github.com/jlfernandezfernandez/ctx/actions/workflows/generate.yml)
[![Triage proposed topic](https://github.com/jlfernandezfernandez/ctx/actions/workflows/triage-topic.yml/badge.svg)](https://github.com/jlfernandezfernandez/ctx/actions/workflows/triage-topic.yml)
[![Deploy site](https://github.com/jlfernandezfernandez/ctx/actions/workflows/deploy.yml/badge.svg)](https://github.com/jlfernandezfernandez/ctx/actions/workflows/deploy.yml)

Un deep dive técnico al día. Para vibe coders que quieren entender qué pasa por debajo.

Cada día laborable, un artículo en profundidad (~15 min, 2.500-3.500 palabras, con código ejecutable) sobre un tema propuesto y votado por el equipo. Desde cero hasta donde una newsletter generalista no llega.

## Cómo funciona

1. Propón un tema con la plantilla de issue ["Proponer tema"](../../issues/new/choose). Nace en `triage`; un modelo pequeño valida que sea técnico y reutiliza o crea su categoría.
2. **Vota con 👍**: cada noche (L-V, ~6:30 Madrid) se publica el tema aceptado más votado (empate → el más antiguo). El label `priority` salta la cola.
3. Una GitHub Action genera el artículo con un LLM (esquema → redacción → revisión → validaciones) y lo publica en la web. La issue se cierra con el link.

```
Issue (triage) → clasificación → topic + categoría → votos 👍 → artículo → GitHub Pages
```

El triaje limita cada autor a 5 propuestas por día UTC. Una respuesta ambigua o inválida
del modelo permanece en `triage`; nunca se acepta ni descarta por defecto.

## Estructura

- `generator/` — generador Python (LLM agnóstico vía API OpenAI-compatible)
- `site/` — web Astro (GitHub Pages)
- `.github/workflows/` — triaje de propuestas, generación diaria y despliegue

## Configuración (Actions)

| Dónde | Nombre | Valor actual |
|---|---|---|
| Secret | `LLM_API_KEY` | API key del proveedor |
| Variable | `LLM_BASE_URL` | `https://ollama.com/v1` (Ollama Cloud) |
| Variable | `LLM_WRITER_MODEL` | `deepseek-v4-pro` |
| Variable | `LLM_REVIEWER_MODEL` | `minimax-m3` |
| Variable | `LLM_TRIAGE_MODEL` | `deepseek-v4-flash` |

Cambiar de proveedor o modelo = cambiar esas variables, cero código. Nunca commitees keys; `.env` está en `.gitignore` y los secrets viven solo en GitHub Actions Secrets.

**Seguridad:** las PRs de forks no reciben secrets; el generador publica máximo un artículo al día aunque se relance. El clasificador trata el contenido de cada issue como datos no confiables, valida estrictamente su respuesta y usa permisos limitados a `issues: write`.

## Desarrollo local

```bash
cd generator && pip install -e '.[dev]' && pytest
cd site && npm install && npm run dev
```

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md). La forma más útil: proponer buenos temas con notas de enfoque, y votar 👍 los que te interesen.
