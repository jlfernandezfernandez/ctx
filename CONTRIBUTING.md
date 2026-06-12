# Contribuir a Ctx

El flujo editorial completo (triaje → votos → writer → reviewer) está documentado en el [README](README.md).

## Proponer un tema (lo más valioso)

Abre una issue con la plantilla **"Proponer tema"** y vota con 👍 las aceptadas (label `topic`):

- El **título de la issue** es el tema del artículo. Sé concreto: mejor "Kafka sin ZooKeeper: KRaft" que "Kafka".
- Las **notas de enfoque** (opcionales) se inyectan al prompt del writer: qué no entiendes, con qué compararlo, qué casos cubrir.
- Un colaborador puede añadir `priority` para saltar la cola.

## Contribuir código

Ver [README.md → Desarrollo local](README.md#desarrollo-local) para el setup.

1. Haz fork y abre una PR contra `main`.
2. Generador (`generator/`): Python, TDD. Ejecuta `pytest`; los tests deben pasar.
3. Web (`site/`): Astro. `npm run build` debe compilar.
4. Las PRs de forks **no** reciben secrets: no puedes (ni necesitas) probar contra el LLM real. Mockea como hacen los tests existentes.

## Lo que no se puede hacer

- Commitear keys o `.env` (está en `.gitignore`; los secrets viven en GitHub Actions Secrets).
- Editar artículos publicados en `site/src/content/blog/` a mano salvo errata clara.
- Lanzar workflows: solo colaboradores con permiso de escritura pueden ejecutar `workflow_dispatch`.
