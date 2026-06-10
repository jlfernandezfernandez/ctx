# Contribuir a Daily Journal

## Proponer un tema (lo más valioso)

Abre una issue con la plantilla **"Proponer tema"**:

- El **título de la issue** es el tema del artículo. Sé concreto: mejor "Kafka sin ZooKeeper: KRaft" que "Kafka".
- Las **notas de enfoque** (opcionales) se inyectan al prompt del generador: qué no entiendes, con qué compararlo, qué casos cubrir.
- El label `topic` se aplica solo. Añade `priority` si debe saltar la cola.
- Labels extra (`java`, `sql`, ...) se convierten en tags del artículo publicado.

Cada día laborable se publica el tema más antiguo de la cola (los `priority` primero). Al publicarse, la issue se cierra con el link.

## Contribuir código

1. Haz fork y abre una PR contra `main`.
2. Generador (`generator/`): Python, TDD. `cd generator && pip install -e '.[dev]' && pytest` — los tests deben pasar.
3. Web (`site/`): Astro. `cd site && npm install && npm run build` debe compilar.
4. Las PRs de forks **no** reciben secrets: no puedes (ni necesitas) probar contra el LLM real. Mockea como hacen los tests existentes.

## Lo que no se puede hacer

- Commitear keys o `.env` (está en `.gitignore`; los secrets viven en GitHub Actions Secrets).
- Editar artículos publicados en `site/src/content/blog/` a mano salvo errata clara.
- Lanzar workflows: solo colaboradores con permiso de escritura pueden ejecutar `workflow_dispatch`.

## Arquitectura en 30 segundos

```
Issue (label topic) → Action nocturna (L-V) → generador Python (LLM, 2 pasadas)
  → markdown en site/src/content/blog/ → commit → deploy a GitHub Pages → issue cerrada
```

Detalles en `docs/superpowers/specs/` y `README.md`.
