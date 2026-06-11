# Contribuir a Ctx

## Proponer un tema (lo más valioso)

Abre una issue con la plantilla **"Proponer tema"**:

- El **título de la issue** es el tema del artículo. Sé concreto: mejor "Kafka sin ZooKeeper: KRaft" que "Kafka".
- Las **notas de enfoque** (opcionales) se inyectan al prompt del generador: qué no entiendes, con qué compararlo, qué casos cubrir.
- La issue nace con el label `triage`: un clasificador automático valida que sea técnica y le asigna una categoría (`java`, `sql`, ...), que se convierte en tag del artículo publicado. Si duda, queda en `triage` para revisión manual; si claramente no es técnica, se cierra como `rejected`.
- Máximo 5 propuestas por persona y día. Un colaborador puede añadir `priority` para saltar la cola.

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

## Arquitectura en 30 segundos

```
Issue (triage) → clasificador LLM → label topic + categoría → votos 👍
  → Action nocturna (L-V): writer genera artículo y abre PR
    → reviewer evalúa; si hay defectos bloqueantes, writer corrige (máx 2 rondas)
      → aprueba: merge → deploy a GitHub Pages → issue cerrada con link
      → no aprueba: PR queda abierta con los defectos comentados → decide un humano
```

Detalles en `README.md`.
