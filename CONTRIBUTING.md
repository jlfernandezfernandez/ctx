# Contribuir a Ctx

## Proponer un tema (lo más valioso)

Abre una issue con la plantilla **"Proponer tema"**:

- El **título de la issue** es el tema del artículo. Sé concreto: mejor "Kafka sin ZooKeeper: KRaft" que "Kafka".
- Las **notas de enfoque** (opcionales) se inyectan al prompt del generador: qué no entiendes, con qué compararlo, qué casos cubrir.
- La issue nace con el label `triage`: un curador automático corrige errores obvios del título y valida que sea técnica. Si duda, queda en `triage` para revisión manual; si es claramente spam o no técnica, se cierra como `rejected`.
- Un colaborador puede añadir `priority` para saltar la cola.

**Vota con 👍** las issues aceptadas (label `topic`): cada día laborable se publica la más votada (empate → la más antigua; `priority` siempre primero). Al publicarse, la issue se cierra con el link.

## Contribuir código

1. Haz fork y abre una PR contra `main`.
2. Generador (`generator/`): Python, TDD. `cd generator && pip install -e '.[dev]' && pytest` — los tests deben pasar.
3. Web (`site/`): Astro. `cd site && npm install && npm run build` debe compilar.
4. Las PRs de forks **no** reciben secrets: no puedes (ni necesitas) probar contra el LLM real. Mockea como hacen los tests existentes.

## Lo que no se puede hacer

- Commitear keys o `.env` (está en `.gitignore`; los secrets viven en GitHub Actions Secrets).
- Editar artículos publicados en `site/src/content/blog/` a mano salvo errata clara.
- Lanzar workflows: solo colaboradores con permiso de escritura pueden ejecutar `workflow_dispatch`.

La arquitectura y el flujo editorial están documentados en [README.md](README.md).
