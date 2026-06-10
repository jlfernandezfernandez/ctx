# Daily Journal

Cada día laborable, un artículo técnico en profundidad (~15 min) sobre un tema propuesto por el equipo.

## Cómo funciona

1. Propón un tema: abre una issue con el label `topic` (el cuerpo admite notas de enfoque). Label `priority` salta la cola.
2. Cada noche (L–V) una GitHub Action genera el artículo con un LLM y lo publica en la web (GitHub Pages).
3. La issue se cierra con el link al artículo.

## Estructura

- `generator/` — generador Python (LLM agnóstico, API OpenAI-compatible)
- `site/` — web Astro (GitHub Pages)
- `.github/workflows/` — generación nocturna y deploy

## Configuración (Actions)

- Secret `LLM_API_KEY` — API key del proveedor LLM
- Variable `LLM_BASE_URL` — p. ej. `https://ollama.com/v1`
- Variable `LLM_MODEL` — p. ej. `gpt-oss:120b`

Cambiar de proveedor = cambiar esas tres. Nunca commitees keys; `.env` está en `.gitignore`.

## Desarrollo local

```bash
cd generator && pip install -e .[dev] && pytest
cd site && npm install && npm run dev
```
