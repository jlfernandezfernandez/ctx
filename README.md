# Daily Journal

**https://jlfernandezfernandez.github.io/daily-journal/**

Cada día laborable, un artículo técnico en profundidad (~15 min, 2.500-3.500 palabras, con código ejecutable) sobre un tema propuesto por el equipo. Desde cero hasta donde una newsletter generalista no llega.

## Cómo funciona

1. Propón un tema con la plantilla de issue ["Proponer tema"](../../issues/new/choose) — el label `topic` se aplica solo. `priority` salta la cola.
2. Cada noche (L-V, ~6:30 Madrid) una GitHub Action coge el tema más antiguo, genera el artículo con un LLM (dos pasadas: esquema → redacción) y lo publica en la web.
3. La issue se cierra con el link al artículo.

```
Issue (topic) → Action nocturna → generador Python → markdown → GitHub Pages
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
cd generator && pip install -e '.[dev]' && pytest   # 27 tests
cd site && npm install && npm run dev
```

## Contribuir

Ver [CONTRIBUTING.md](CONTRIBUTING.md). La forma más útil: proponer buenos temas con notas de enfoque.
