---
title: "Pydantic AI"
description: "Pydantic AI garantiza salidas estructuradas y validadas de LLMs usando modelos Pydantic, con reintentos automáticos ante fallos de validación. Elimina el boilerplate de parsing y es adecuado para sistemas de producción donde la integridad de los datos es crítica, aunque esquemas muy estrictos pueden limitar la creatividad del LLM. Su enfoque narrow pero profundo contrasta con frameworks generalistas como LangChain."
date: 2026-06-11
tags: ["structured-output", "pydantic", "llm", "function-calling", "validation"]
summary: "Pydantic AI garantiza salidas estructuradas y validadas de LLMs usando modelos Pydantic, con reintentos automáticos ante fallos de validación. Elimina el boilerplate de parsing y es adecuado para sistemas de producción donde la integridad de los datos es crítica, aunque esquemas muy estrictos pueden limitar la creatividad del LLM. Su enfoque narrow pero profundo contrasta con frameworks generalistas como LangChain."
issue: 12
requestedBy: "jlfernandezfernandez"
writer: "deepseek-v4-pro"
---

## El problema de la salida no estructurada en LLMs

Los modelos de lenguaje (LLMs) han revolucionado la forma de construir software, pero integrarlos en pipelines de producción sigue siendo un desafío. El problema fundamental no es la calidad del texto generado, sino su forma: los LLMs devuelven cadenas de caracteres libres, sin estructura predecible. Para una aplicación que espera un JSON con campos tipados, esa libertad se convierte en fragilidad. Un simple error de formato, una clave omitida o un valor del tipo incorrecto puede romper todo el flujo downstream.

Los primeros intentos de domar esta variabilidad se basaron en prompts con instrucciones explícitas: "responde siempre en JSON con los campos X, Y, Z". Esta técnica funciona en casos sencillos, pero no ofrece garantías. El modelo puede alucinar campos, anidar incorrectamente o devolver texto plano si el prompt es ambiguo. Además, el desarrollador debe escribir parsers ad‑hoc, lógica de validación y reintentos, lo que infla el boilerplate y dificulta el mantenimiento.

La llegada del function calling nativo en proveedores como OpenAI y Anthropic supuso un avance significativo. Ahora el modelo puede recibir un esquema JSON‑Schema y se le instruye para que devuelva una llamada a función estructurada. Sin embargo, la integración sigue siendo manual: hay que definir el schema, invocar la API, validar la respuesta, manejar errores y, a menudo, reintentar. Además, el function calling está pensado para que el modelo decida *cuándo* llamar a una herramienta, no para garantizar que la respuesta final cumpla un esquema.

En aplicaciones de producción —agentes autónomos, pipelines de extracción de datos, asistentes que alimentan bases de datos— la validación estricta de la salida es un requisito no negociable. Un campo mal tipado puede corromper una base de datos, y un error de parsing puede detener un flujo automatizado. Se necesita un framework que imponga un contrato de datos fiable, con reintentos automáticos y validación tipada, sin sacrificar la flexibilidad del LLM.

Pydantic AI surge precisamente para cubrir ese vacío. Construido sobre Pydantic V2, el estándar de facto para validación de datos en Python, ofrece un modelo de programación donde el agente se define alrededor de un esquema de salida tipado. El framework se encarga de traducir ese esquema a function calling, ejecutar reintentos cuando la respuesta no cumple la validación, y exponer herramientas (tools) con sus propios modelos. El resultado es una integración robusta que elimina el boilerplate de parsing y validación, permitiendo al desarrollador centrarse en la lógica de negocio.

## Cómo Pydantic AI estructura la interacción con LLMs

Pydantic AI gira en torno a un concepto sencillo: el agente se construye sobre un modelo Pydantic que define la forma exacta de la respuesta esperada. El framework se encarga de forzar al LLM a producir una salida que cumpla ese contrato, reintentando automáticamente si la validación falla. Esto transforma la salida impredecible del LLM en un objeto tipado, validado y listo para usar en el resto de la aplicación.

Los componentes principales son:

- **Agent**: la unidad central que encapsula el modelo de resultado, el system prompt, las tools disponibles y las dependencias. Se instancia con un modelo Pydantic como tipo de retorno y, opcionalmente, un tipo para las dependencias inyectables.
- **Tool**: funciones Python decoradas con `@agent.tool` que el LLM puede invocar. Cada tool define su propio modelo Pydantic para los argumentos, garantizando que el LLM las llame con los parámetros correctos. Las tools pueden recibir el `RunContext` para acceder a dependencias.
- **RunContext**: objeto que transporta las dependencias tipadas a lo largo de la ejecución. Se inyecta en tools y en funciones auxiliares, proporcionando acceso seguro a recursos como conexiones de base de datos, configuraciones o estado compartido.
- **Result**: tipo genérico que encapsula tanto el modelo de datos validado (`result.data`) como el historial completo de mensajes (`result.all_messages`), permitiendo auditoría y depuración.

El flujo típico es: se define un modelo Pydantic para la salida deseada, se crea un `Agent` con ese modelo y un system prompt, se invoca `agent.run_sync` (o `agent.run`) con el input del usuario, y Pydantic AI se encarga de todo lo demás. Internamente, el framework convierte el modelo en un esquema JSON‑Schema, lo pasa al LLM como parte de la definición de function calling, y espera una respuesta que invoque la función con los datos estructurados. Si la respuesta no valida, se reintenta automáticamente, enviando al LLM el error de validación para que corrija.

Este diseño permite que el desarrollador trabaje con objetos Python fuertemente tipados desde el primer momento. No hay que escribir lógica de parsing, ni manejar excepciones de validación manualmente. El system prompt sigue siendo relevante para guiar el comportamiento del LLM, pero la garantía de estructura recae en el framework.

## Bajo el capó: internals, trade‑offs y comparativa con LangChain

### Internals

Cuando se ejecuta `agent.run_sync(user_prompt)`, Pydantic AI realiza varios pasos. Primero, serializa el modelo de resultado a JSON‑Schema utilizando las capacidades de Pydantic V2. Este schema se inyecta en la llamada a la API del LLM como una función disponible (function calling). El system prompt y el user prompt se envían junto con la definición de la función. El LLM puede responder con un mensaje normal o con una invocación a la función. Si el LLM devuelve texto en lugar de una llamada estructurada, el framework puede reintentar (según la configuración) o lanzar una excepción.

Cuando el LLM invoca la función, los argumentos se validan contra el modelo Pydantic. Si la validación falla, Pydantic AI construye un mensaje de error detallado (con la ubicación exacta del fallo) y lo reenvía al LLM en un nuevo turno de conversación, pidiéndole que corrija la llamada. Este ciclo se repite hasta que se obtiene una respuesta válida o se alcanza el límite de reintentos (`max_retries`). Una vez validado, el resultado se devuelve como un objeto `Result[Modelo]`, donde `result.data` es la instancia del modelo.

Las tools siguen un mecanismo similar: cada tool se registra con su propio modelo de argumentos, que también se expone como function calling. El LLM decide si llamar a una tool; cuando lo hace, el framework ejecuta la función Python, valida los argumentos y devuelve el resultado al LLM para que continúe. Las dependencias se resuelven a través de `RunContext`, que se inyecta automáticamente en las tools que lo declaran en su firma.

### Trade‑offs

La principal ventaja es la eliminación del boilerplate de validación y reintentos. El tipado fuerte permite que IDEs y linters detecten errores en tiempo de desarrollo, y los modelos Pydantic sirven como documentación viva del contrato de datos. Además, la integración con el ecosistema Pydantic (validadores custom, `Field`, tipos constrained) ofrece una expresividad enorme para refinar las restricciones.

Sin embargo, esta rigidez tiene un costo. Un esquema demasiado estricto puede limitar la creatividad del LLM o forzarlo a producir respuestas artificiales que cumplan la forma pero no el fondo. En tareas abiertas (como generación de texto creativo), un modelo de salida fijo puede ser contraproducente. Además, el framework depende de que el proveedor soporte function calling de calidad; en modelos más antiguos o locales, la fiabilidad puede disminuir. Por último, la curva de aprendizaje de Pydantic V2 (concepts como `model_validator`, `field_validator`, tipos `Annotated`) puede ser empinada para equipos que no lo dominen.

### Comparativa con LangChain

LangChain es el framework más popular para aplicaciones LLM. Ofrece un ecosistema amplio: chains, agents, tools, memoria, RAG, integración con decenas de proveedores. Su enfoque es modular y genérico, pero el tipado estático y la validación de salida no son prioridades. En LangChain, la salida de un chain o agente suele ser un string o un diccionario; el desarrollador debe validar y parsear manualmente. Existen output parsers, pero no ofrecen la misma integración profunda ni reintentos automáticos basados en errores de validación.

Pydantic AI, en cambio, es un framework narrow pero profundo. Su foco exclusivo en structured output lo hace más simple y predecible. No incluye abstracciones para RAG o memoria persistente, aunque se pueden integrar manualmente (como veremos en los ejemplos). La elección depende del caso de uso: LangChain es ideal para prototipado rápido, exploración de múltiples proveedores y flujos complejos con memoria y recuperación. Pydantic AI brilla cuando el requisito principal es un contrato de datos fiable y mantenible, especialmente en sistemas de producción donde la integridad de los datos es crítica.

## Ejemplos prácticos

### Structured output simple

Este ejemplo muestra cómo extraer información estructurada de un texto libre. Definimos un modelo `User` con `name` y `age`, creamos un agente y ejecutamos una consulta.

```python
import asyncio
from pydantic import BaseModel
from pydantic_ai import Agent

# Modelo de salida deseado
class User(BaseModel):
    name: str
    age: int

# Agente con system prompt que instruye al LLM
agent = Agent(
    model="openai:gpt-4o-mini",  # requiere OPENAI_API_KEY en entorno
    output_type=User,
    system_prompt="Extrae el nombre y la edad de la persona descrita en el texto."
)

# Ejecución síncrona
result = agent.run_sync("María tiene 34 años y vive en Madrid.")
user = result.data
print(f"Nombre: {user.name}, Edad: {user.age}")
# Salida: Nombre: María, Edad: 34
```

El framework se encarga de convertir `User` en un esquema JSON, llamar a OpenAI, validar la respuesta y reintentar si es necesario. El objeto `user` es una instancia de `User` plenamente tipada.

### Agente con tools y dependencias

Ahora construimos un agente que consulta el clima usando una tool. La tool recibe una ubicación y devuelve datos simulados. Usamos inyección de dependencias para pasar una ubicación por defecto.

```python
from dataclasses import dataclass
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext, Tool

# Modelo de salida
class WeatherResponse(BaseModel):
    location: str
    temperature_c: float
    conditions: str

# Dependencia inyectable
@dataclass
class Location:
    city: str
    country: str = "España"

# Tool que el LLM puede llamar
async def get_weather(ctx: RunContext[Location], location: str) -> dict:
    """Obtiene el clima actual para una ubicación."""
    # En producción, aquí iría una API real
    # Usamos la dependencia si no se especifica location
    target = location or ctx.deps.city
    # Simulación
    return {
        "location": target,
        "temperature_c": 22.5,
        "conditions": "soleado"
    }

# Agente con tool y dependencias tipadas
agent = Agent(
    model="openai:gpt-4o-mini",
    output_type=WeatherResponse,
    system_prompt="Usa la tool get_weather para obtener el clima y devuelve los datos estructurados.",
    deps_type=Location,
    tools=[Tool(get_weather)]
)

# Ejecución con dependencia inyectada
deps = Location(city="Barcelona")
result = agent.run_sync("¿Qué tiempo hace?", deps=deps)
weather = result.data
print(f"En {weather.location} hace {weather.temperature_c}°C y está {weather.conditions}.")
```

El agente decide llamar a `get_weather` con el argumento `location` inferido del prompt o de la dependencia. La tool recibe el `RunContext` que contiene `deps`, permitiendo acceder a la ubicación por defecto. La respuesta se valida contra `WeatherResponse`.

### Agente multi‑step con memoria y RAG simulado

Este ejemplo muestra un agente que realiza una investigación usando una tool de búsqueda en documentos y mantiene memoria de la conversación. El modelo de salida es complejo, con una lista de fuentes.

```python
from typing import List
from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext, Tool
from pydantic_ai.messages import ModelRequest, TextPart

# Documentos simulados (vector store en producción)
DOCUMENTS = [
    "Pydantic AI usa modelos Pydantic para structured output.",
    "LangChain es un framework generalista para LLMs.",
    "Pydantic V2 introdujo validadores más rápidos.",
]

# Modelo de salida
class Source(BaseModel):
    doc_id: int
    snippet: str

class ResearchResult(BaseModel):
    summary: str
    sources: List[Source] = Field(..., min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)

# Tool de búsqueda
async def search_docs(ctx: RunContext[None], query: str) -> List[str]:
    """Busca documentos relevantes a la query."""
    # Simulación: devuelve docs que contengan la query
    return [doc for doc in DOCUMENTS if query.lower() in doc.lower()]

# Agente con memoria (lista de mensajes)
agent = Agent(
    model="openai:gpt-4o-mini",
    output_type=ResearchResult,
    system_prompt=(
        "Eres un asistente de investigación. Usa la tool search_docs para encontrar información. "
        "Resume los hallazgos y proporciona fuentes. La confianza debe reflejar la relevancia."
    ),
    tools=[Tool(search_docs)],
)

# Historial de mensajes para memoria
user_query = "¿Qué diferencias hay entre Pydantic AI y LangChain?"
messages = [ModelRequest(parts=[TextPart(content=user_query)])]

# Ejecución con memoria
result = agent.run_sync(user_query, message_history=messages)
research = result.data
print(f"Resumen: {research.summary}")
for src in research.sources:
    print(f"  Fuente {src.doc_id}: {src.snippet}")
print(f"Confianza: {research.confidence}")

# Si el LLM no incluye fuentes, el framework reintentará automáticamente
# gracias a la validación de min_length=1 en sources.
```

El agente utiliza `search_docs` para recuperar fragmentos relevantes, construye un resumen y devuelve un objeto `ResearchResult` validado. La memoria se pasa como `message_history`, permitiendo conversaciones multi‑turno. Si el LLM omite fuentes o asigna una confianza fuera de rango, Pydantic AI reintentará la llamada hasta que el resultado cumpla el esquema.

## Errores frecuentes y cómo evitarlos

**Esquema demasiado restrictivo.** Un modelo con campos obligatorios y tipos muy concretos puede forzar al LLM a inventar datos o a fallar repetidamente. Si la información puede no estar disponible, usa `Optional` o `Union` con `None`. Por ejemplo, `age: Optional[int] = None` permite que el campo esté ausente. También puedes añadir descripciones en `Field(description="...")` para guiar al LLM sobre cuándo un campo es opcional.

**Ignorar el system prompt.** El modelo de salida no sustituye al prompt; el LLM necesita contexto para saber qué extraer. Un system prompt vago produce resultados pobres, aunque el esquema se cumpla. Dedica tiempo a escribir un prompt claro que explique la tarea, el formato esperado y cómo manejar ambigüedades. El prompt y el esquema trabajan juntos.

**No manejar excepciones en tools.** Si una tool lanza una excepción no controlada, el agente falla sin oportunidad de reintento útil. Envuelve la lógica de la tool en un bloque `try/except` y devuelve un mensaje de error estructurado (por ejemplo, un dict con clave `error`) que el LLM pueda interpretar. Así el agente puede decidir reintentar con otros argumentos o informar al usuario.

**Dependencia excesiva de reintentos.** Configurar `max_retries` muy alto puede consumir tokens rápidamente si el LLM no entiende el esquema. Ajusta el límite según la complejidad de la tarea (2‑3 reintentos suelen bastar) y, sobre todo, diseña prompts y modelos que minimicen los fallos de validación. Un buen modelado de datos reduce la necesidad de reintentos.

**Confundir `Result` con el modelo de datos.** `Result` es el contenedor que incluye `data` (el modelo validado) y `all_messages` (historial completo). Algunos desarrolladores asumen que `result` es directamente el modelo, lo que causa errores de atributo. Accede siempre a `result.data` para obtener la instancia tipada. `all_messages` es útil para depuración y para mantener la memoria en conversaciones multi‑turno.

## Para saber más

- Documentación oficial de Pydantic AI: [https://ai.pydantic.dev/](https://ai.pydantic.dev/)
- Documentación de Pydantic V2: [https://docs.pydantic.dev/latest/](https://docs.pydantic.dev/latest/)
- OpenAI Function Calling Guide: [https://platform.openai.com/docs/guides/function-calling](https://platform.openai.com/docs/guides/function-calling)
- Blog de Pydantic sobre el lanzamiento de Pydantic AI: [https://pydantic.dev/articles/pydantic-ai](https://pydantic.dev/articles/pydantic-ai)