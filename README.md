# ctx

**https://jlfernandezfernandez.github.io/ctx/**

Un deep dive técnico al día. Para vibe coders que quieren entender qué pasa por debajo.

Cada día laborable, un artículo en profundidad (~15 min, 2.500-3.500 palabras, con código ejecutable) sobre un tema propuesto y votado por el equipo. Desde cero hasta donde una newsletter generalista no llega.

## Cómo funciona

1. Propón un tema con la plantilla de issue ["Proponer tema"](../../issues/new/choose) — el label `topic` se aplica solo.
2. **Vota con 👍**: cada noche (L-V, ~6:30 Madrid) se publica el tema más votado (empate → el más antiguo). El label `priority` salta la cola.
3. Una GitHub Action genera el artículo con un LLM (esquema → redacción → metadata con TL;DR y tags) y lo publica en la web. La issue se cierra con el link.

```
Issue (topic) + votos 👍 → Action nocturna → generador Python → markdown → GitHub Pages
```

## Estructura

- `generator/` — generador Python (LLM agnóstico vía API OpenAI-compatible)
- `site/` — web Astro (GitHub Pages)
- `.github/workflows/` — `generate.yml` (cron L-V + manual) y `deploy.yml`

## Configuración (Actions)

| Dónde | Nombre | Valor actual |
|---|---|---|
| Secret | `LLM_API_KEY` | API key del proveedor |
| Variable | `LLM_BASE_URL` | `https://ollama.com/v1` (Ollama Cloud) |
| Variable | `LLM_MODEL` | `deepseek-v4-flash` |

Cambiar de proveedor o modelo = cambiar esas variables, cero código. Nunca commitees keys; `.env` está en `.gitignore` y los secrets viven solo en GitHub Actions Secrets.

**Seguridad:** los workflows solo los lanzan colaboradores con write; las PRs de forks no reciben secrets; el generador publica máximo un artículo al día aunque se relance.

## Desarrollo local

```bash
cd generator && pip install -e '.[dev]' && pytest   # 37 tests
cd site && npm install && npm run dev
```

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md). La forma más útil: proponer buenos temas con notas de enfoque, y votar 👍 los que te interesen.
