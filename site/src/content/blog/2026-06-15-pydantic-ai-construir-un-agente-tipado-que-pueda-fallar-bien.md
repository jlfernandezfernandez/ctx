---
title: "Pydantic AI: Construir un agente tipado que pueda fallar bien"
description: "Pydantic AI aplica tipado fuerte en cada frontera del agente —respuesta, herramientas, dependencias— para convertir fallos del LLM y de las herramientas en datos estructurados y procesables. El artículo detalla cómo diseñar uniones de respuesta, manejar errores con ModelRetry, aislar dependencias sensibles y añadir observabilidad, logrando que el agente falle de forma controlada en lugar de lanzar excepciones o silencios."
date: 2026-06-15
tags: ["typed-agents"]
summary: "Pydantic AI aplica tipado fuerte en cada frontera del agente —respuesta, herramientas, dependencias— para convertir fallos del LLM y de las herramientas en datos estructurados y procesables. El artículo detalla cómo diseñar uniones de respuesta, manejar errores con ModelRetry, aislar dependencias sensibles y añadir observabilidad, logrando que el agente falle de forma controlada en lugar de lanzar excepciones o silencios."
issue: 27
requestedBy: "jlfernandezfernandez"
writer: "deepseek-v4-pro"
reviewer: "minimax-m3"
---

## El problema: fallos que el sistema no ve venir

Un agente LLM que llama a una API interna, recibe un JSON del modelo y lo reenvía a otro servicio está operando con tres fuentes de error que rara vez se declaran:

1. El modelo puede devolver JSON malformado o con campos inventados.
2. La herramienta puede recibir argumentos incorrectos y fallar con una excepción.
3. El output final puede tener la forma correcta pero el contenido equivocado (una alucinación semántica).

En un SDK de proveedor típico, estos fallos se manifiestan como excepciones genéricas, strings corruptos o silencios que rompen el pipeline aguas abajo. El desarrollador escribe validación manual, reintentos ad-hoc y logs de texto que requieren lectura humana para diagnosticar qué pasó.

La pregunta no es cómo evitar que un LLM falle —porque va a fallar— sino cómo hacer que cada fallo se manifieste como un **dato tipado** que el sistema pueda procesar, registrar y recuperar sin intervención manual.

Pydantic AI aborda esto con una decisión de diseño fundamental: todo lo que entra y sale del agente —la respuesta final, los argumentos de las herramientas, los resultados de las herramientas, las dependencias de negocio— debe tener un tipo explícito. El framework valida en cada frontera y, cuando algo no encaja, no lanza una excepción y abandona: reintroduce el error en el loop de ejecución para que el LLM pueda corregirlo, o lo convierte en un estado de fallo tipado que el caller puede manejar.

El resultado no es un agente que nunca falla, sino uno que **falla bien**: cada fallo tiene un tipo, una causa registrada y un camino de recuperación o degradación controlada.

## El tipo de respuesta como contrato de fallo

El primer punto de control es `result_type`. En lugar de pedirle al LLM "un JSON con estos campos" mediante instrucciones en el prompt, se le pasa un modelo Pydantic. El framework genera el JSON Schema correspondiente, lo inyecta en la llamada al modelo y, cuando la respuesta llega, la valida antes de devolverla al caller.

La diferencia con `response_format` de OpenAI es que el proveedor solo garantiza que el JSON sea sintácticamente válido y que cumpla el schema a nivel de tipos JSON. No valida restricciones de negocio como rangos, formatos de string o coherencia entre campos. Pydantic AI añade una capa de validación completa post-llamada y reintentos automáticos si el JSON no conforma el schema.

Pero el verdadero salto está en diseñar el tipo de respuesta para que represente **todos los estados posibles del agente**, no solo el éxito. Un `Union` discriminado permite que el modelo exprese incertidumbre, solicite aclaraciones o informe de un fallo en una herramienta sin romper el contrato:

```python
from pydantic import BaseModel, Field
from typing import Union, Literal

class Success(BaseModel):
    status: Literal["success"] = "success"
    account_id: str
    balance: float
    currency: str = Field(description="Código ISO 4217, ej. USD")

class ClarificationNeeded(BaseModel):
    status: Literal["clarification_needed"] = "clarification_needed"
    question: str = Field(description="Pregunta concreta al usuario")
    missing_field: str = Field(description="Qué campo falta o es ambiguo")

class ToolFailure(BaseModel):
    status: Literal["tool_failure"] = "tool_failure"
    tool_name: str
    error_detail: str
    fallback_action: str = Field(
        description="Qué puede hacer el usuario mientras tanto"
    )

AgentResponse = Union[Success, ClarificationNeeded, ToolFailure]
```

El JSON Schema generado por Pydantic para este `Union` incluye una propiedad `status` con valores fijos que el LLM puede usar como ancla. El modelo no necesita "entender" el concepto de fallo; solo necesita ver que hay tres formas válidas de responder y elegir la que corresponda según el contexto. Las descripciones en `Field` guían esa elección sin instrucciones frágiles en el prompt del sistema.

Un trade-off importante: schemas demasiado estrictos provocan alucinaciones de campos. Si el modelo no tiene información para rellenar un campo requerido, puede inventarla. La defensa está en usar `Optional` con defaults sensatos y describir en `Field` cuándo es aceptable omitir un valor:

```python
from pydantic import BaseModel, Field
from typing import Union, Literal, Optional

class Success(BaseModel):
    status: Literal["success"] = "success"
    account_id: str
    balance: float
    pending_transactions: Optional[int] = Field(
        default=None,
        description="Número de transacciones pendientes. Omitir si el sistema "
                    "de transacciones no respondió o el dato no está disponible."
    )
```

El modelo, al ver que `pending_transactions` puede ser `null` y leer la descripción, tiene permiso explícito para omitirlo en lugar de inventar un número.

## Dependencias tipadas: el contexto que el LLM no debe tocar

Un agente de producción necesita datos reales: conexiones a bases de datos, clientes de APIs, configuración sensible. Pasarlos por prompt es un riesgo de seguridad y una fuente de alucinaciones. Pydantic AI introduce `deps_type`: un contenedor tipado que se inyecta en el agente y está disponible para las herramientas y funciones del sistema, pero **nunca se serializa en el prompt** que ve el LLM.

```python
from dataclasses import dataclass
from sqlalchemy.ext.asyncio import AsyncSession

@dataclass(frozen=True)
class Deps:
    db: AsyncSession
    account_service: "AccountServiceClient"
    config: "AppConfig"
```

La inmutabilidad (`frozen=True`) es deliberada: las herramientas no deben modificar las dependencias, solo leerlas. Esto evita efectos secundarios entre llamadas y simplifica el testing.

Cuando una herramienta necesita acceder a la base de datos, recibe `deps` como parámetro. El LLM decide **si** llamar a la herramienta y **con qué argumentos**, pero nunca ve los datos que la herramienta obtiene de `deps`:

```python
from pydantic_ai import Agent, RunContext

agent = Agent(
    "openai:gpt-4o",
    deps_type=Deps,
    output_type=AgentResponse,
)

@agent.tool
async def get_account(ctx: RunContext[Deps], account_id: str) -> dict:
    result = await ctx.deps.account_service.fetch(account_id)
    if result is None:
        return {"found": False, "detail": "Account not found"}
    return {"found": True, "balance": result.balance, "currency": result.currency}
```

El `RunContext[Deps]` es genérico: el tipo `Deps` viaja por todo el sistema sin que el desarrollador tenga que hacer casting. En tests, basta con construir un `Deps` con mocks y pasarlo al agente; no hay variables globales ni singletons que parchear.

## Herramientas que declaran sus errores

En el SDK de OpenAI, una function call fallida —por ejemplo, porque el LLM pasó un string donde la función esperaba un int— produce una excepción en tiempo de ejecución que el desarrollador debe capturar y mapear manualmente a un mensaje para el modelo. No hay reintento automático ni validación previa de argumentos.

Pydantic AI invierte el orden: **valida los argumentos antes de ejecutar la herramienta**. El LLM propone una llamada con ciertos parámetros; el framework los valida contra el schema Pydantic de la tool. Si no conforman, el error se convierte en un mensaje que vuelve al LLM para que corrija los argumentos, sin que la función llegue a ejecutarse.

Pero incluso con argumentos válidos, una herramienta puede fallar: la API externa no responde, la base de datos devuelve una inconsistencia, el dato solicitado no existe. Aquí hay dos caminos:

**`ModelRetry`**: la herramienta lanza esta excepción con un mensaje descriptivo. El framework captura el mensaje, lo inyecta en el historial de la conversación como un resultado de tool fallido, y devuelve el control al LLM para que intente otra estrategia (corregir argumentos, llamar a otra herramienta, pedir aclaración al usuario).

**Excepción no controlada**: si la herramienta lanza cualquier otra excepción, el run se aborta y la excepción se propaga al caller. Esto es adecuado para fallos que el LLM no puede razonablemente corregir (ej. la base de datos está caída y reintentar con otros argumentos no ayudará).

```python
from pydantic_ai import ModelRetry

class TransferResult(BaseModel):
    status: Literal["completed", "insufficient_funds", "account_closed"]
    transaction_id: Optional[str] = None
    detail: Optional[str] = None

@agent.tool
async def transfer(
    ctx: RunContext[Deps],
    from_account: str,
    to_account: str,
    amount: float,
) -> TransferResult:
    if amount <= 0:
        raise ModelRetry("Amount must be positive. Please correct the amount.")
    
    try:
        result = await ctx.deps.account_service.transfer(
            from_account, to_account, amount
        )
    except InsufficientFundsError as e:
        return TransferResult(
            status="insufficient_funds",
            detail=str(e.available_balance),
        )
    except AccountClosedError:
        return TransferResult(
            status="account_closed",
            detail="The source account is closed.",
        )
    
    return TransferResult(
        status="completed",
        transaction_id=result.transaction_id,
    )
```

`ModelRetry` se usa para errores corregibles (argumentos inválidos que el LLM puede ajustar). Los errores de dominio que el LLM no puede resolver —fondos insuficientes, cuenta cerrada— se devuelven como datos tipados para que el agente los incorpore en su respuesta final (probablemente un `ToolFailure`).

## El loop de ejecución bajo control

El ciclo de un run en Pydantic AI sigue esta secuencia:

1. El LLM recibe el prompt del sistema, el historial y los schemas de herramientas. Decide si responder directamente o emitir tool calls.
2. Si hay tool calls, Pydantic AI valida los argumentos contra el schema de cada tool. Si falla la validación, genera un mensaje de error y vuelve al paso 1 (sin ejecutar la tool).
3. Si los argumentos son válidos, ejecuta las tools. Cada resultado se valida contra el tipo de retorno declarado.
4. Si una tool lanza `ModelRetry` o su resultado no conforma el tipo de retorno, el error se serializa como mensaje y vuelve al paso 1.
5. Si todas las tools se ejecutan sin `ModelRetry`, el LLM recibe los resultados y genera una respuesta final.
6. La respuesta final se valida contra `result_type`. Si no conforma, se reintroduce como error y vuelve al paso 1.

`max_retries` (por defecto 1, configurable al instanciar el `Agent`) controla cuántas iteraciones de este ciclo se permiten antes de lanzar `UnexpectedModelBehavior`. Cuando se agotan los reintentos, el framework levanta esta excepción, que contiene el historial completo de mensajes del run.

La decisión de diseño clave es qué hacer con `UnexpectedModelBehavior`. Propagarla como excepción rompe el contrato tipado que hemos construido. La alternativa es un wrapper que capture la excepción y la convierta en una variante más del tipo de respuesta:

```python
class PermanentFailure(BaseModel):
    status: Literal["permanent_failure"] = "permanent_failure"
    reason: str
    retries_exhausted: int

AgentResponse = Union[Success, ClarificationNeeded, ToolFailure, PermanentFailure]

async def run_agent(deps: Deps, user_input: str) -> AgentResponse:
    with agent.capture_run_messages() as messages:
        try:
            result = await agent.run(user_input, deps=deps)
            return result.data
        except UnexpectedModelBehavior:
            logger.error("Agent run exhausted retries", extra={
                "messages": messages,
                "retries": agent.max_retries,
            })
            return PermanentFailure(
                reason="El agente no pudo generar una respuesta válida "
                       "después de varios intentos.",
                retries_exhausted=agent.max_retries,
            )
```

El caller de `run_agent` siempre recibe un objeto de tipo `AgentResponse`, nunca una excepción. Puede hacer pattern matching sobre `status` para decidir qué hacer: devolver `Success` al usuario, mostrar `ClarificationNeeded.question`, registrar `ToolFailure` y ofrecer un fallback, o escalar `PermanentFailure`.

`capture_run_messages` merece atención aparte. Activarlo en todos los runs tiene un coste de memoria y almacenamiento innecesario para el 95% de ejecuciones que terminan en éxito. La práctica recomendada es no capturar mensajes por defecto y hacerlo solo cuando se detecta un error:

```python
# En el wrapper, antes de re-lanzar o convertir:
with agent.capture_run_messages() as messages:
    try:
        result = await agent.run(user_input, deps=deps)
    except UnexpectedModelBehavior:
        # messages contiene el historial completo
        store_for_diagnosis(messages)
        raise
```

## Observabilidad para depurar fallos en producción

Cuando un agente falla en producción, la pregunta no es "¿qué dijo el LLM?" sino "¿en qué paso del loop se rompió el contrato y por qué?". Las métricas deben contar esa historia sin obligar a leer transcripciones.

Pydantic AI se integra con OpenTelemetry y Logfire. Los spans capturan automáticamente: duración total del run, tokens consumidos (prompt y completion), número de tool calls, y errores de validación. Pero la instrumentación por defecto no distingue entre un `ModelRetry` recuperable y un `UnexpectedModelBehavior` terminal. Esa distinción hay que añadirla:

```python
from pydantic_ai import Agent
import logfire

agent = Agent(...)

# Logfire se configura una vez a nivel de aplicación
logfire.configure(
    service_name="account-agent",
    send_to_logfire=True,  # o exportador OTLP para OpenTelemetry
)

@agent.tool
async def transfer(ctx: RunContext[Deps], ...) -> TransferResult:
    with logfire.span("tool:transfer", amount=amount):
        try:
            result = await ctx.deps.account_service.transfer(...)
        except InsufficientFundsError:
            logfire.info("transfer:insufficient_funds", from_account=from_account)
            return TransferResult(status="insufficient_funds", ...)
        # ...
```

Las métricas que importan para iterar sobre el diseño del agente:

- **Tasa de `ModelRetry` por herramienta**: si `transfer` provoca `ModelRetry` en el 15% de las llamadas, el schema de argumentos o la descripción de la tool necesitan ajuste.
- **Distribución de variantes de `AgentResponse`**: un 30% de `ClarificationNeeded` sugiere que el prompt del sistema no está dando suficiente contexto o que el schema de entrada del usuario es ambiguo.
- **Latencia p99 en runs con reintentos**: un run que agota 3 reintentos puede consumir 4 llamadas al LLM. Si la p99 se dispara, hay que ajustar `max_retries` o hacer que las herramientas fallen más rápido (timeouts, circuit breakers).
- **Tasa de `UnexpectedModelBehavior`**: cualquier valor por encima del 0.5% merece una auditoría de los schemas y un muestreo de historiales completos para encontrar el patrón.

El historial de mensajes solo se almacena en caso de `UnexpectedModelBehavior` o cuando una variante de error lo justifica. Almacenar todas las conversaciones con el LLM es caro y rara vez útil.

## Pruebas que simulan el caos del LLM

Probar un agente implica tres niveles:

**Tests unitarios de herramientas y dependencias**: no involucran al LLM. Se construye un `Deps` con mocks, se llama a la función de la tool directamente y se verifica que devuelve el tipo correcto o lanza `ModelRetry` según corresponda.

```python
import pytest
from unittest.mock import AsyncMock

@pytest.mark.asyncio
async def test_transfer_insufficient_funds():
    mock_service = AsyncMock()
    mock_service.transfer.side_effect = InsufficientFundsError(available=50.0)
    deps = Deps(db=AsyncMock(), account_service=mock_service, config=...)
    ctx = RunContext(deps=deps, model=None, usage=None, prompt="")
    
    result = await transfer(ctx, "A", "B", 100.0)
    
    assert result.status == "insufficient_funds"
    assert "50.0" in result.detail
```

**Tests de integración con `FunctionModel`**: Pydantic AI proporciona modelos simulados que devuelven exactamente lo que el test especifica, sin llamar a un LLM real. Esto permite inyectar respuestas malformadas, tool calls con argumentos inválidos o JSON que no cumple el schema, y verificar que el agente responde con el estado de error correcto.

```python
from pydantic_ai.models.function import FunctionModel, AgentInfo
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ModelMessage

@pytest.mark.asyncio
async def test_agent_handles_malformed_tool_call():
    # Simular un LLM que devuelve una tool call con amount negativo
    def bad_response(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="transfer",
                    args={"from_account": "A", "to_account": "B", "amount": -50},
                )
            ]
        )
    
    test_agent = Agent(
        FunctionModel(bad_response),
        deps_type=Deps,
        output_type=AgentResponse,
        tools=[transfer],
    )
    
    deps = Deps(...)  # con mocks que nunca deberían ser llamados
    result = await test_agent.run("Transfer -50 from A to B", deps=deps)
    
    # ModelRetry debería activarse; el agente reintentará.
    # Con max_retries=1, si el modelo simulado persiste en el error,
    # obtendremos UnexpectedModelBehavior
```

Para probar que el agente agota reintentos y termina en `PermanentFailure`, se puede usar un `FunctionModel` que devuelve repetidamente JSON inválido:

```python
@pytest.mark.asyncio
async def test_exhausts_retries_on_invalid_output():
    call_count = 0
    
    def stubborn_model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        # Devuelve siempre un JSON que no cumple el schema
        return ModelResponse(
            parts=[TextPart(content='{"status": "unknown_variant"}')]
        )
    
    test_agent = Agent(
        FunctionModel(stubborn_model),
        deps_type=Deps,
        output_type=AgentResponse,
        max_retries=2,
    )
    
    with pytest.raises(UnexpectedModelBehavior):
        await test_agent.run("test", deps=Deps(...))
    
    assert call_count == 3  # intento inicial + 2 reintentos
```

**Tests end-to-end con LLM real**: se reservan para validar la calidad de las respuestas en casos representativos (ej. 20 escenarios curados), no para cada variante de error. Estos tests son lentos, caros y no deterministas; su valor está en detectar regresiones en la calidad semántica, no en la lógica de control de errores.

## Cuándo Pydantic AI es la herramienta correcta

Pydantic AI no es un framework de orquestación multi-agente ni un gestor de flujos conversacionales complejos. Su núcleo es el **tipado fuerte en cada frontera del agente** y un loop de ejecución que trata los errores de validación como parte del flujo normal.

Usa Pydantic AI cuando:

- El output del agente se integra con sistemas tipados (APIs, bases de datos, colas de mensajes) y un error de parsing silencioso tiene consecuencias en producción.
- Necesitas que los errores del LLM y de las herramientas sean **procesables por código** (alertas, métricas, flujos de degradación), no solo legibles por humanos en un dashboard.
- El equipo valora la trazabilidad: poder responder "¿por qué falló este run?" consultando métricas y spans, no leyendo logs de texto.
- Las herramientas acceden a recursos de negocio (bases de datos, APIs internas) que no deben exponerse al prompt del LLM.

El SDK nativo del proveedor (OpenAI, Anthropic) es preferible cuando:

- Necesitas control granular sobre el prompt y el formato de salida sin capas intermedias.
- El streaming es prioritario y el post-procesamiento tipado añade latencia innecesaria.
- El equipo ya tiene una capa de validación y reintento propia que funciona bien.

LangGraph ocupa un espacio distinto: agentes multi-step con estado persistente, ramificaciones condicionales complejas y memoria a largo plazo. Un nodo de un grafo de LangGraph puede usar internamente Pydantic AI para el paso que requiere validación fuerte de output; no son excluyentes.

La decisión no es "Pydantic AI vs. LangGraph" sino "¿en qué pasos de mi sistema necesito validación tipada en tiempo real y recuperación automática de errores de forma?".

## Principios para un agente que falla bien

Construir un agente con Pydantic AI no elimina los fallos del LLM. Los hace visibles, tipados y recuperables. Los principios que sostienen ese resultado son:

1. **Todo output posible del agente está en el tipo union de respuesta.** Si un fallo no tiene su variante en `AgentResponse`, se manifestará como excepción no controlada o silencio.
2. **Las herramientas declaran sus modos de fallo en el tipo de retorno o mediante `ModelRetry`.** La diferencia es si el LLM puede corregir el error (argumentos) o debe aceptarlo e informar al usuario (fondos insuficientes).
3. **Las dependencias tipadas aíslan el contexto fiable del texto generado.** El LLM decide qué herramientas llamar, pero nunca ve los datos sensibles ni puede alucinarlos.
4. **Los reintentos son finitos y los fallos terminales se convierten en datos.** `UnexpectedModelBehavior` nunca debe propagarse al caller final; un wrapper la transforma en una variante más del union.
5. **La observabilidad responde "¿por qué falló este run?" sin leer logs del LLM.** Métricas de `ModelRetry`, distribución de variantes y latencia con reintentos cuentan la historia completa.

El resultado es un agente que puede integrarse en pipelines de producción con la misma confianza tipada que el resto del sistema, no como una caja negra que a veces devuelve texto y a veces lanza excepciones.