---
title: "Pydantic AI: Construir un agente tipado que pueda fallar bien"
description: "Pydantic AI modela los fallos de agentes de IA como estados tipados, permitiendo manejo de errores predecible, reintentos y observabilidad nativa. A diferencia de SDKs nativos o LangGraph, cada interacción produce un resultado tipado que el programa puede inspeccionar, facilitando pruebas y resiliencia en producción."
date: 2026-06-17
tags: ["ai-agents"]
summary: "Pydantic AI modela los fallos de agentes de IA como estados tipados, permitiendo manejo de errores predecible, reintentos y observabilidad nativa. A diferencia de SDKs nativos o LangGraph, cada interacción produce un resultado tipado que el programa puede inspeccionar, facilitando pruebas y resiliencia en producción."
issue: 27
requestedBy: "jlfernandezfernandez"
writer: "deepseek-v4-pro"
---

Los agentes de IA en producción se enfrentan a una realidad incómoda: los modelos de lenguaje son inherentemente estocásticos. Un *tool call* malformado, un JSON que no respeta el esquema prometido o una alucinación en los parámetros pueden descarrilar un flujo de trabajo sin previo aviso. Los SDK nativos de los proveedores delegan en el desarrollador la responsabilidad de detectar, tipificar y recuperar estos fallos, lo que suele traducirse en bloques *try/except* frágiles, reintentos manuales y una ausencia total de contratos programáticos. En el otro extremo, frameworks de orquestación como LangGraph ofrecen grafos potentes pero opacos: los errores se propagan por nodos y aristas sin una representación explícita, y depurar un fallo en producción se convierte en arqueología de trazas.

Pydantic AI adopta una estrategia distinta. En lugar de tratar los fallos como excepciones que interrumpen el flujo, los modela como **estados tipados** que el programa puede inspeccionar, clasificar y manejar con lógica ordinaria. El resultado es un agente donde cada interacción con el modelo —ya sea una respuesta estructurada, una llamada a herramienta o un error de validación— produce un valor predecible. Esa previsibilidad es la base para construir sistemas de IA testables, observables y resilientes.

## Modelar el éxito y el fracaso con tipos

El punto de partida es la generación estructurada. Pydantic AI permite definir la salida esperada del agente mediante un modelo de Pydantic o una simple firma de función tipada. El *runtime* del agente inyecta el esquema en la llamada al LLM y, cuando la respuesta llega, la valida automáticamente.

```python
from pydantic import BaseModel
from pydantic_ai import Agent

class WeatherReport(BaseModel):
    temperature_celsius: float
    conditions: str
    humidity_percent: float

weather_agent = Agent(
    "openai:gpt-4o",
    output_type=WeatherReport,
    system_prompt="Devuelve un informe meteorológico estructurado."
)
```

Si el modelo devuelve un JSON que no respeta el esquema —por ejemplo, omite el campo `humidity_percent` o asigna un string a `temperature_celsius`— Pydantic AI no lanza una excepción genérica. En lugar de eso, el objeto `RunResult` que retorna `weather_agent.run()` encapsula el fallo de validación como parte de su estado. El desarrollador decide si reintentar, derivar a un *fallback* o devolver un resultado parcial.

El tipo `RunResult` es el contenedor central de la librería. Cada ejecución del agente produce una instancia con:

- `data`: el modelo Pydantic validado, o `None` si la validación falló.
- `all_messages()`: la historia completa de mensajes intercambiados con el LLM, incluyendo los *tool calls* y sus resultados.
- `usage()`: consumo de tokens y número de peticiones realizadas.
- Métodos como `new_messages()` para obtener solo los mensajes generados en la última ejecución y continuar una conversación.

Esta estructura obliga a manejar explícitamente el caso de fallo. No hay excepciones ocultas: si `result.data` es `None`, el desarrollador debe decidir qué hacer. El tipado estático de Python (con `mypy` o `pyright`) refuerza esta disciplina en tiempo de desarrollo.

## Herramientas que fallan bien

Las herramientas son la principal fuente de errores en un agente: APIs externas que no responden, parámetros inválidos, *rate limiting*. El patrón tradicional de lanzar excepciones rompe el flujo del LLM y dificulta la recuperación automática. Pydantic AI permite que las herramientas devuelvan información estructurada sobre el fallo, de modo que el error sea un valor más en el diálogo. Una forma eficaz es definir un modelo de respuesta que encapsule tanto el éxito como el fracaso.

```python
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
import httpx

class ToolResponse(BaseModel):
    success: bool
    data: str | None = None
    error_type: str | None = None
    error_message: str | None = None

class SupportDeps(BaseModel):
    client_id: str
    api_key: str

async def search_knowledge_base(
    ctx: RunContext[SupportDeps], query: str
) -> ToolResponse:
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.empresa.com/kb/search",
                params={"q": query},
                headers={"Authorization": f"Bearer {ctx.deps.api_key}"},
                timeout=5.0
            )
            response.raise_for_status()
            data = response.json()
            return ToolResponse(success=True, data=data["answer"])
    except httpx.TimeoutException:
        return ToolResponse(
            success=False,
            error_type="timeout",
            error_message="La búsqueda excedió el tiempo límite."
        )
    except httpx.HTTPStatusError as e:
        return ToolResponse(
            success=False,
            error_type="upstream_error",
            error_message=f"Error del servicio: {e.response.status_code}"
        )
```

El agente recibe el `ToolResponse` como parte del historial de mensajes. Si `success=False`, el LLM puede interpretar el error y decidir reintentar, usar otra herramienta o pedir ayuda al usuario. El contrato tipado de la herramienta (`ToolResponse`) garantiza que el agente siempre recibe una respuesta con la misma forma, ya sea un éxito o un fallo estructurado. Alternativamente, para errores que deben forzar un reintento inmediato, se puede lanzar `ModelRetry` desde la herramienta, lo que indica al runtime que reintente la llamada al modelo con un mensaje de error.

## Estrategias de recuperación tipadas

Pydantic AI ofrece reintentos configurables a nivel de agente para fallos de validación, pero el verdadero valor está en la capacidad de implementar lógica de recuperación basada en el tipo de error, no en heurísticas frágiles.

Cuando una herramienta devuelve `ToolResponse(success=False, error_type="timeout")`, el agente puede decidir reintentar automáticamente porque el error es transitorio. Si el error es `"upstream_error"` con código 403, probablemente sea permanente y requiera un *fallback*.

```python
from pydantic_ai import Agent

support_agent = Agent(
    "openai:gpt-4o",
    deps_type=SupportDeps,
    output_type=SupportResponse,
    tools=[search_knowledge_base, create_ticket],
    retries=2  # reintentos ante fallo de validación del output_type
)
```

El parámetro `retries` controla cuántas veces el agente reintenta automáticamente cuando el modelo produce una respuesta que no pasa la validación Pydantic. Para errores de herramienta, la decisión de reintentar recae en el LLM, que ve el `ToolResponse` fallido y puede invocar la herramienta de nuevo con parámetros ajustados. Esto evita reintentos ciegos que consumen tokens sin sentido.

Para fallos permanentes, se pueden definir *fallbacks* declarativos. Un agente de soporte puede escalar de una FAQ a una búsqueda en base de conocimiento y, si ambas fallan, crear un ticket para un operador humano:

```python
async def faq_lookup(ctx: RunContext[SupportDeps], question: str) -> ToolResponse:
    # ...

async def kb_search(ctx: RunContext[SupportDeps], query: str) -> ToolResponse:
    # ...

async def escalate_to_human(ctx: RunContext[SupportDeps], summary: str) -> ToolResponse:
    # siempre éxito, crea ticket
    return ToolResponse(success=True, data=f"Ticket creado: {ticket_id}")

support_agent = Agent(
    "openai:gpt-4o",
    deps_type=SupportDeps,
    tools=[faq_lookup, kb_search, escalate_to_human],
    output_type=SupportResponse
)
```

El *system prompt* puede instruir al modelo para que intente primero `faq_lookup`, luego `kb_search` y finalmente `escalate_to_human`. Como cada herramienta devuelve un `ToolResponse` con información de error, el LLM tiene contexto suficiente para decidir la escalación sin lógica adicional en código.

## Observabilidad: fallos visibles y trazables

En producción, un agente que falla silenciosamente es un riesgo. Pydantic AI se integra con Logfire —una capa de observabilidad basada en OpenTelemetry— para exponer trazas detalladas de cada paso: llamadas al modelo, ejecuciones de herramientas, validaciones y reintentos.

```python
import logfire

logfire.instrument_pydantic_ai()
```

Cada ejecución genera una traza con spans para:
- La llamada al LLM (incluyendo tokens consumidos y modelo usado).
- Cada *tool call* (con parámetros y resultado, éxito o fallo).
- La validación del resultado estructurado (con detalles del error de validación si ocurre).
- Los reintentos automáticos por `ModelRetry` o por fallo de validación.

Los errores de herramienta aparecen como eventos dentro del span de la herramienta, con atributos `error_type` y `error_message` si se utiliza un modelo como `ToolResponse`. Esto permite construir dashboards que monitoricen tasas de fallo por tipo de error, latencia de herramientas y frecuencia de reintentos, sin necesidad de parsear logs informales.

Además, el objeto `RunResult` puede inspeccionarse directamente para diagnóstico *post-mortem*. `result.all_messages()` devuelve la conversación completa, incluyendo las respuestas fallidas de las herramientas, lo que facilita entender por qué el agente tomó una decisión equivocada.

## Pruebas que abrazan el fallo

Probar agentes de IA es notoriamente difícil por el no determinismo de los LLM. Pydantic AI proporciona `TestModel`, un modelo determinista que permite simular respuestas específicas del LLM, incluyendo salidas malformadas, *tool calls* erróneos y fallos de validación.

```python
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

test_model = TestModel()
agent = Agent("openai:gpt-4o", model=test_model, output_type=WeatherReport)

# Simular una respuesta que falla la validación
test_model.custom_output_text = (
    '{"temperature_celsius": "veinte", "conditions": "soleado"}'
)

result = await agent.run("¿Qué tiempo hace en Madrid?")
assert result.data is None
# El agente habrá reintentado según la configuración; podemos verificarlo
assert result.usage().request_count > 1
```

Para probar herramientas con dependencias, se inyectan dobles de prueba:

```python
async def test_kb_search_timeout():
    deps = SupportDeps(client_id="test", api_key="fake")
    # Configurar httpx mock para simular timeout
    result = await search_knowledge_base(RunContext(deps), "consulta")
    assert result.success is False
    assert result.error_type == "timeout"
```

Las pruebas de integración pueden verificar caminos de recuperación completos. Por ejemplo, se puede simular que `faq_lookup` falla con `ToolResponse(success=False, error_type="not_found")` y verificar que el agente escala correctamente a `kb_search` y finalmente a `escalate_to_human`, validando el `SupportResponse` final.

La evaluación sistemática con datasets de casos de fallo —preguntas ambiguas, dependencias caídas, *rate limits*— se convierte en una práctica de CI. Al no depender de un LLM real, las pruebas son rápidas, repetibles y no consumen tokens.

## Comparación con SDKs nativos y LangGraph

Para apreciar el valor de los fallos tipados, conviene contrastar con los enfoques alternativos.

**SDKs nativos (OpenAI, Anthropic, etc.)**  
Ofrecen acceso directo a la API, pero delegan todo el manejo de errores al desarrollador. El *function calling* devuelve un blob JSON que hay que parsear manualmente. Si el modelo alucina un argumento, se obtiene una excepción en tiempo de ejecución. Implementar reintentos requiere lógica *ad-hoc* que inspeccione el mensaje de error y decida si reintentar. No hay contratos tipados: la forma de los datos es un acuerdo verbal entre el *system prompt* y la esperanza. En producción, esto se traduce en código frágil y difícil de mantener.

**LangGraph**  
LangGraph permite construir agentes como grafos dirigidos, con nodos que representan pasos y aristas que modelan transiciones. Es potente para flujos complejos, pero los errores quedan atrapados en la topología del grafo. Un fallo en un nodo puede requerir lógica condicional para redirigir el flujo, y el estado del error no está tipado de forma uniforme. La depuración se basa en inspeccionar el estado del grafo, que suele ser un diccionario opaco. La observabilidad depende de *callbacks* y logging manual. La resiliencia se construye caso a caso, sin un modelo de fallo reutilizable.

**Pydantic AI**  
Trata los errores como ciudadanos de primera clase. Cada interacción produce un resultado tipado que el programa puede examinar. La validación de salidas es automática y está integrada en el ciclo de vida del agente. Las herramientas pueden devolver modelos estructurados como `ToolResponse`, encapsulando el éxito y el fracaso en un mismo tipo. Los reintentos y *fallbacks* se expresan con políticas declarativas (`retries`) o lógica ordinaria, no con malabares de excepciones. La observabilidad es nativa y estructurada a través de Logfire. El *trade-off* es una capa de abstracción adicional, pero elimina el *boilerplate* repetitivo que los SDK nativos exigen y reduce la superficie de error que LangGraph oculta.

## De prototipo a producción

Llevar un agente a producción exige algo más que manejar errores: requiere configuración externalizada, métricas de salud y degradación *graceful*. Pydantic AI facilita estas prácticas mediante su sistema de dependencias y su modelo de ejecución.

Las dependencias se inyectan en el agente y en cada herramienta a través de `RunContext`, lo que permite pasar configuración, clientes HTTP, conexiones a bases de datos o cualquier recurso que deba variar entre entornos (desarrollo, staging, producción) sin cambiar el código del agente.

```python
class ProductionDeps(BaseModel):
    db_connection_str: str
    api_key: str
    log_level: str

prod_deps = ProductionDeps(
    db_connection_str=os.environ["DB_URL"],
    api_key=os.environ["API_KEY"],
    log_level="INFO"
)

result = await support_agent.run(user_query, deps=prod_deps)
```

Para observabilidad continua, además de las trazas de Logfire, conviene emitir métricas de negocio: tasa de fallos por tipo de error, latencia de herramientas, porcentaje de escalaciones a operador humano. Estas métricas pueden calcularse a partir de los `ToolResponse` y `RunResult` producidos, y exponerse vía Prometheus o similar.

La degradación *graceful* es la propiedad de que el agente siempre devuelve una respuesta útil, incluso cuando algunas herramientas fallan. El tipo `SupportResponse` puede incluir un campo `fallback_used: bool` y un mensaje que informe al usuario de que la respuesta es parcial. El *system prompt* puede instruir al modelo para que, ante fallos irrecuperables, genere una respuesta honesta en lugar de alucinar.

```python
class SupportResponse(BaseModel):
    answer: str
    sources: list[str]
    fallback_used: bool = False
    escalated_to_human: bool = False
```

El agente, con sus herramientas que fallan bien y su política de reintentos, produce este resultado estructurado incluso cuando la base de conocimiento está caída: `fallback_used=True`, `escalated_to_human=True` y un `answer` que explica la situación al usuario.

## El tipo como ancla de fiabilidad

La tesis central de Pydantic AI es que, en un mundo de modelos no deterministas, los tipos son la base de sistemas de IA confiables. Al modelar explícitamente el éxito y el fracaso, la librería transforma los fallos impredecibles en estados manejables mediante lógica de programación ordinaria. La testabilidad, la observabilidad y la resiliencia no son características añadidas, sino propiedades emergentes de un diseño donde cada valor tiene un tipo y cada error es un dato, no una excepción.

Para el ingeniero que construye agentes en producción, esto significa menos tiempo depurando *tracebacks* opacos y más tiempo diseñando comportamientos recuperables. El resultado es un sistema que, incluso cuando falla, falla bien.