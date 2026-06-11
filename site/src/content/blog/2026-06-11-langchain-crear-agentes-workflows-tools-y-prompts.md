---
title: "LangChain: crear agentes, workflows, tools y prompts"
description: "LangChain proporciona abstracciones para construir agentes LLM que combinan razonamiento con ejecución de herramientas mediante ReAct o function calling. LangGraph extiende esto a workflows stateful con branching, ciclos e intervención humana. Usa agentes cuando el LLM deba interactuar con sistemas externos; prefiere function calling por fiabilidad y LangGraph para orquestaciones complejas más allá de bucles simples."
date: 2026-06-11
tags: ["langchain", "agents", "llm", "tools", "langgraph"]
summary: "LangChain proporciona abstracciones para construir agentes LLM que combinan razonamiento con ejecución de herramientas mediante ReAct o function calling. LangGraph extiende esto a workflows stateful con branching, ciclos e intervención humana. Usa agentes cuando el LLM deba interactuar con sistemas externos; prefiere function calling por fiabilidad y LangGraph para orquestaciones complejas más allá de bucles simples."
issue: 10
requestedBy: "jlfernandezfernandez"
writer: "deepseek-v4-pro"
---

## Por qué los LLMs necesitan agentes: el problema de la caja negra

Un LLM aislado es un motor de inferencia textual: recibe un prompt y devuelve una respuesta. No puede consultar una base de datos, llamar a una API externa, ejecutar código ni recordar lo que dijo hace tres turnos. Esta limitación lo vuelve insuficiente para automatizar tareas reales que requieren múltiples pasos, acceso a datos frescos o interacción con sistemas externos. Por ejemplo, un asistente que reserve una mesa en un restaurante necesita buscar disponibilidad en una API, proponer opciones al usuario, confirmar la elección y enviar la reserva. Un LLM solo no puede hacerlo.

Los agentes resuelven esta brecha al combinar el razonamiento del modelo con la capacidad de actuar. Un agente recibe un objetivo, decide qué herramienta invocar, ejecuta la acción, observa el resultado y repite el ciclo hasta alcanzar una respuesta final. Este patrón, conocido como razonamiento-acción (ReAct) o function calling, permite que el LLM se convierta en el cerebro de un sistema que integra APIs, bases de datos, código arbitrario y lógica de negocio.

LangChain es un framework que unifica estos componentes. Proporciona abstracciones para definir tools (herramientas), construir prompts con instrucciones y esquemas de salida, gestionar la memoria de conversación y ejecutar el bucle agente. Sobre esta base, LangGraph extiende el modelo a workflows stateful: grafos dirigidos donde cada nodo puede ser un agente, una tool o una función arbitraria, con branching condicional, ciclos e intervención humana. Esto permite orquestar procesos complejos que van más allá de un simple bucle de razonamiento-acción.

En este artículo exploraremos cómo LangChain estructura un agente, los internals de prompts y parsing, las diferencias entre tipos de agentes, y cómo LangGraph habilita workflows avanzados. Todo ello con ejemplos de código completos y autocontenidos, desde un agente mínimo hasta un grafo con human-in-the-loop.

## Anatomía de un agente en LangChain

Un agente en LangChain se compone de cuatro elementos fundamentales: el modelo de lenguaje (LLM), el prompt que define su comportamiento y formato de salida, un conjunto de tools con sus descripciones, y un executor que orquesta el ciclo de razonamiento-acción.

El LLM es el cerebro. LangChain soporta cualquier modelo compatible con su interfaz `BaseChatModel`, incluyendo OpenAI, Anthropic, Cohere y modelos locales. El prompt es un `ChatPromptTemplate` que contiene un `SystemMessage` con instrucciones sobre el rol del agente, las reglas para usar herramientas y el formato de respuesta esperado. Incluye también un `MessagesPlaceholder` para el historial de la conversación y otro para inyectar las descripciones de las tools en el momento de la ejecución.

Las tools son funciones Python que el agente puede invocar. Cada tool se define con un nombre, una descripción textual y un esquema de parámetros (generado automáticamente mediante type hints o un modelo Pydantic). La descripción es crítica: el LLM la usa para decidir si necesita la tool y qué argumentos pasarle. LangChain ofrece tools predefinidas (búsqueda web, calculadora, consulta a APIs) y un decorador `@tool` para crear tools personalizadas a partir de cualquier función.

El executor es el motor que ejecuta el bucle. En su forma más simple, `AgentExecutor` recibe la entrada del usuario, la pasa al agente, y si el agente devuelve una acción (tool a invocar), ejecuta la tool, añade la observación al historial y vuelve a llamar al agente. Este ciclo se repite hasta que el agente produce una respuesta final (`AgentFinish`). El executor maneja límites de iteraciones y errores de parsing.

El ciclo de razonamiento-acción sigue el patrón ReAct o el function calling nativo de OpenAI. En ReAct, el prompt instruye al modelo para que genere un texto con formato específico:

```
Thought: razonamiento sobre qué hacer
Action: nombre de la tool
Action Input: parámetros en JSON
```

El agente parsea esta salida, ejecuta la tool y añade una `Observation` con el resultado. En function calling, el modelo devuelve directamente una llamada a función estructurada; LangChain la traduce a una invocación de tool y añade el resultado como un mensaje de tipo `ToolMessage`. Ambos enfoques comparten la misma esencia: el modelo decide cuándo y cómo usar herramientas, y el executor cierra el bucle.

El prompt es el pegamento que define la personalidad del agente, las restricciones de uso de herramientas y el esquema de salida. Un prompt mal diseñado es la causa más frecuente de fallos: el modelo puede ignorar herramientas, alucinar parámetros o no saber cuándo detenerse. Por eso LangChain proporciona plantillas específicas para cada tipo de agente, como `create_openai_tools_agent`, que construye el prompt adecuado para function calling.

## Internals, trade-offs y comparativas

El prompt de un agente no es estático: LangChain lo construye dinámicamente a partir de varios componentes. Un `ChatPromptTemplate` para OpenAI tools incluye un `SystemMessage` con instrucciones, un `MessagesPlaceholder` para el historial (`chat_history`) y otro para los mensajes generados por el agente (`agent_scratchpad`). Las tools se inyectan no como texto, sino como una lista de esquemas JSON que el modelo recibe en el parámetro `tools` de la API. En agentes ReAct, las descripciones de las tools se interpolan directamente en el system prompt como cadenas JSON, lo que consume más tokens y es menos fiable.

El parsing de la salida es otro punto crítico. `AgentOutputParser` es la clase base; para ReAct, `ReActSingleInputOutputParser` extrae `Action` y `Action Input` usando expresiones regulares. Si el modelo produce una salida mal formada, se lanza `OutputParserException`. LangChain ofrece `handle_parsing_errors` en `AgentExecutor`, que puede reintentar enviando el error al modelo, o usar `OutputFixingParser` que llama a otro LLM para corregir la salida. En function calling, el parsing es determinista: la respuesta incluye un array de `tool_calls` con nombre y argumentos JSON válidos, eliminando ambigüedades.

Existen tres familias principales de agentes. Los agentes ReAct son genéricos y funcionan con cualquier LLM, pero dependen de que el modelo siga un formato textual estricto; son propensos a errores de parsing y alucinaciones en la elección de herramientas. Los agentes OpenAI tools/functions aprovechan el soporte nativo del modelo, lo que mejora la precisión, reduce la latencia (menos tokens generados) y simplifica el parsing, pero atan el agente a un proveedor. El agente JSON legacy (basado en `StructuredChatAgent`) es una alternativa intermedia que pide al modelo que genere un blob JSON con la acción; hoy está en desuso frente a function calling. La elección depende del modelo y del equilibrio entre fiabilidad y portabilidad.

LangGraph introduce un cambio de paradigma frente al `AgentExecutor`. Este último es un bucle simple: el agente decide, ejecuta, repite. LangGraph modela el flujo como un grafo dirigido con estado. Cada nodo puede ser un agente, una tool, una función de enrutamiento o cualquier lógica. Las aristas condicionales permiten branching basado en el estado, ciclos controlados y paralelismo. Esto habilita workflows multi-agente, validaciones intermedias, reintentos y, crucialmente, human-in-the-loop: el grafo puede interrumpirse en un nodo y esperar input externo antes de continuar. El trade-off es una mayor complejidad de implementación y depuración, pero la flexibilidad es muy superior para procesos de negocio reales.

La memoria en agentes mantiene el contexto entre turnos. `ConversationBufferMemory` almacena la lista completa de mensajes, lo que ofrece máxima fidelidad pero incrementa el uso de tokens linealmente. `ConversationSummaryMemory` usa un LLM para resumir el historial, reduciendo el coste a expensas de posible pérdida de detalles. LangChain integra la memoria mediante `RunnableWithMessageHistory`, que persiste el historial en una sesión externa (base de datos, Redis) y lo inyecta en el prompt en cada invocación. La elección impacta directamente en el coste y en la capacidad del agente para recordar matices de la conversación.

## Ejemplos prácticos: de un agente mínimo a workflows con intervención humana

### Agente mínimo con tools predefinidas

Este ejemplo crea un agente con dos tools: búsqueda web (Tavily) y una calculadora matemática. Usa `create_openai_tools_agent` y `AgentExecutor`.

```python
import os
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, create_openai_tools_agent, Tool
from langchain.tools import TavilySearchResults
from langchain.chains import LLMMathChain
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

# Configurar API keys (se asume que están en variables de entorno)
os.environ["OPENAI_API_KEY"] = "sk-..."  # Reemplazar con tu key
os.environ["TAVILY_API_KEY"] = "tvly-..."  # Reemplazar con tu key

# Inicializar LLM
llm = ChatOpenAI(model="gpt-4o", temperature=0)

# Definir tools
search = TavilySearchResults(max_results=2)
math_chain = LLMMathChain.from_llm(llm=llm)  # Chain que usa LLM para evaluar expresiones matemáticas
math_tool = Tool(name="Calculator", func=math_chain.run, description="Useful for math calculations.")
tools = [search, math_tool]

# Prompt específico para OpenAI tools
prompt = ChatPromptTemplate.from_messages([
    ("system", "Eres un asistente útil. Usa las herramientas disponibles para responder con precisión."),
    MessagesPlaceholder(variable_name="chat_history", optional=True),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

# Crear agente
agent = create_openai_tools_agent(llm, tools, prompt)

# Executor con límite de iteraciones y manejo de errores
executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
    max_iterations=5,
    handle_parsing_errors=True,
)

# Ejecutar
respuesta = executor.invoke({"input": "¿Cuál es la raíz cuadrada de la población de Francia en 2023?"})
print(respuesta["output"])
```

El agente buscará la población de Francia, extraerá el número y luego usará la calculadora para la raíz cuadrada. `verbose=True` muestra el razonamiento paso a paso.

### Tool personalizada con el decorador @tool

Crear una tool propia es directo. El decorador `@tool` convierte una función en una tool de LangChain, usando el docstring como descripción y los type hints como esquema de parámetros.

```python
from langchain_core.tools import tool

@tool
def obtener_clima(ciudad: str) -> str:
    """Obtiene el clima actual de una ciudad. Retorna temperatura y condiciones."""
    # Simulación: en producción se llamaría a una API real
    climas_mock = {
        "madrid": "Soleado, 28°C",
        "buenos aires": "Nublado, 15°C",
        "londres": "Lluvia, 10°C",
    }
    return climas_mock.get(ciudad.lower(), "Ciudad no encontrada")

# Agregar al agente anterior
tools = [search, math_tool, obtener_clima]
# El resto del código es idéntico al ejemplo 1, reemplazando la lista de tools
```

El LLM leerá la descripción "Obtiene el clima actual de una ciudad..." y decidirá invocar `obtener_clima` cuando el usuario pregunte por el tiempo. La claridad del docstring es determinante.

### Agente con memoria de conversación

Para mantener contexto entre turnos, usamos `RunnableWithMessageHistory` con `ChatMessageHistory`. El historial se almacena en memoria (en producción se usaría una base de datos).

```python
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_core.chat_history import BaseChatMessageHistory

# Diccionario para almacenar sesiones (en memoria)
store = {}

def get_session_history(session_id: str) -> BaseChatMessageHistory:
    if session_id not in store:
        store[session_id] = ChatMessageHistory()
    return store[session_id]

# Crear el agente con memoria
agent_with_history = RunnableWithMessageHistory(
    executor,  # El AgentExecutor del ejemplo 1
    get_session_history,
    input_messages_key="input",
    history_messages_key="chat_history",
)

# Primera interacción
resp1 = agent_with_history.invoke(
    {"input": "Mi nombre es Carlos."},
    config={"configurable": {"session_id": "user123"}}
)
print(resp1["output"])

# Segunda interacción: el agente recuerda el nombre
resp2 = agent_with_history.invoke(
    {"input": "¿Recuerdas mi nombre?"},
    config={"configurable": {"session_id": "user123"}}
)
print(resp2["output"])
```

`RunnableWithMessageHistory` inyecta automáticamente el historial en el placeholder `chat_history` del prompt. La clave `session_id` permite mantener conversaciones independientes.

### Workflow básico con LangGraph

LangGraph modela el flujo como un grafo con estado. Este ejemplo define un grafo con dos nodos: `agent` (que decide) y `tools` (que ejecuta). Una arista condicional desde `agent` dirige a `tools` si hay tool calls, o termina.

```python
from typing import TypedDict, Annotated, Sequence
import operator
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage

# Definir el estado del grafo
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]  # Historial acumulativo

# Nodo agente: invoca al LLM con tools
def call_agent(state: AgentState):
    messages = state["messages"]
    # Usamos el mismo llm y tools del ejemplo 1
    response = llm.bind_tools(tools).invoke(messages)
    return {"messages": [response]}

# Nodo tools: ejecuta las tool calls del último mensaje AIMessage
def call_tools(state: AgentState):
    last_message = state["messages"][-1]
    tool_calls = last_message.tool_calls
    tool_messages = []
    for tc in tool_calls:
        tool_name = tc["name"]
        tool_args = tc["args"]
        # Buscar la tool por nombre
        tool = next(t for t in tools if t.name == tool_name)
        result = tool.invoke(tool_args)
        tool_messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
    return {"messages": tool_messages}

# Función de enrutamiento: si el último mensaje tiene tool_calls, ir a tools; si no, END
def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END

# Construir el grafo
workflow = StateGraph(AgentState)
workflow.add_node("agent", call_agent)
workflow.add_node("tools", call_tools)
workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
workflow.add_edge("tools", "agent")  # Después de tools, vuelve al agente

graph = workflow.compile()

# Ejecutar
initial_state = {"messages": [HumanMessage(content="¿Clima en Madrid?")]}
for event in graph.stream(initial_state):
    for key, value in event.items():
        print(f"Nodo {key}: {value}")
```

El grafo itera automáticamente: el agente decide llamar a `obtener_clima`, el nodo `tools` ejecuta y devuelve el resultado al agente, que luego genera la respuesta final. `operator.add` en el estado anexa mensajes en lugar de sobrescribir.

### Workflow con human-in-the-loop

LangGraph permite pausar la ejecución para intervención humana mediante `interrupt`. En este ejemplo, un nodo de aprobación detiene el grafo si la acción es crítica; un humano revisa y reanuda con `Command`.

```python
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt, Command

# Estado extendido con un flag de aprobación
class AgentStateWithApproval(TypedDict):
    messages: Annotated[Sequence[BaseMessage], operator.add]
    approved: bool  # Indica si la acción fue aprobada

# Nodo que requiere aprobación humana antes de ejecutar una tool peligrosa
def approval_node(state: AgentStateWithApproval):
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        tool_name = last_message.tool_calls[0]["name"]
        # Interrumpir para pedir aprobación
        decision = interrupt(f"¿Apruebas ejecutar la tool '{tool_name}'? (yes/no)")
        if decision.lower() == "yes":
            return {"approved": True}
    return {"approved": False}

# Nodo tools modificado: solo ejecuta si approved es True
def call_tools_guarded(state: AgentStateWithApproval):
    if not state.get("approved", False):
        return {"messages": [AIMessage(content="Acción no aprobada por el humano.")]}
    # Misma lógica que call_tools del ejemplo anterior
    last_message = state["messages"][-1]
    tool_calls = last_message.tool_calls
    tool_messages = []
    for tc in tool_calls:
        tool = next(t for t in tools if t.name == tc["name"])
        result = tool.invoke(tc["args"])
        tool_messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))
    return {"messages": tool_messages}

# Construir grafo con checkpointing (necesario para interrupciones)
workflow = StateGraph(AgentStateWithApproval)
workflow.add_node("agent", call_agent)
workflow.add_node("approval", approval_node)
workflow.add_node("tools", call_tools_guarded)
workflow.set_entry_point("agent")
workflow.add_conditional_edges("agent", should_continue, {"tools": "approval", END: END})
workflow.add_edge("approval", "tools")
workflow.add_edge("tools", "agent")

memory = MemorySaver()
graph = workflow.compile(checkpointer=memory)

# Configuración con thread_id para persistencia
config = {"configurable": {"thread_id": "session1"}}

# Primera ejecución: se interrumpirá en approval_node
initial_state = {"messages": [HumanMessage(content="Borra todos los archivos del sistema.")], "approved": False}
for event in graph.stream(initial_state, config):
    for key, value in event.items():
        print(f"Nodo {key}: {value}")
# El grafo queda pausado; para reanudar:
# graph.invoke(Command(resume="yes"), config)
```

`interrupt` pausa el grafo y espera un `Command` con `resume`. El `MemorySaver` persiste el estado entre interrupciones. Este patrón es esencial para acciones sensibles que requieren validación humana.

## Trampas comunes y cómo evitarlas

**Prompts mal diseñados.** Si el prompt no especifica claramente cuándo y cómo usar las tools, el agente puede ignorarlas o generar formatos incorrectos. Incluye instrucciones explícitas: "Usa la herramienta X solo cuando necesites datos en tiempo real. Responde en JSON con el campo 'action'." Añadir ejemplos few-shot en el prompt mejora la adherencia. Valida el comportamiento con casos límite (preguntas que no requieren tools, múltiples tools necesarias).

**Descripciones de tools ambiguas.** Una descripción vaga como "Busca cosas" provoca que el LLM alucine parámetros o elija la tool equivocada. Sé conciso pero preciso: "Busca el clima actual de una ciudad dada. Entrada: nombre de la ciudad (string). Salida: descripción textual del clima." Incluye el propósito y los tipos de entrada/salida. Si una tool tiene efectos secundarios (escritura en BD), indícalo para que el agente sea cauteloso.

**No manejar `OutputParserException`.** En agentes ReAct, una coma mal puesta en el JSON puede romper el parsing. Configura `handle_parsing_errors=True` en `AgentExecutor` para que el error se envíe de vuelta al LLM y este corrija la salida. Alternativamente, usa `OutputFixingParser` con un modelo secundario. En function calling este problema es casi inexistente, pero siempre valida que los argumentos sean del tipo esperado antes de ejecutar la tool.

**Bucles infinitos.** Un agente ReAct puede entrar en un ciclo donde siempre elige una tool sin llegar a una respuesta final. Establece `max_iterations` bajo (5-10) y usa `early_stopping_method="generate"` para que el LLM genere una respuesta final forzada al alcanzar el límite. En LangGraph, asegúrate de que exista una arista hacia `END` desde al menos un nodo; las condiciones deben cubrir todos los casos posibles.

**Rutas condicionales incompletas en LangGraph.** Si una función de enrutamiento no mapea todos los valores de retorno a nodos o `END`, el grafo fallará en tiempo de ejecución. Define siempre un mapeo completo en `add_conditional_edges`. Usa `END` como valor por defecto para casos no contemplados. Depura con `graph.get_graph().draw_mermaid_png()` para visualizar el flujo.

**Coste de tokens elevado.** Cada tool añadida incrementa el system prompt (en ReAct) o la lista de funciones (en function calling). Con muchas tools, el contexto se satura y el coste por llamada se dispara. Limita las tools visibles en cada paso: puedes filtrar dinámicamente según el estado. Prefiere function calling, que codifica las tools de forma más compacta. Para memoria, usa `ConversationSummaryMemory` en conversaciones largas; resume el historial periódicamente para mantener el contexto dentro de la ventana del modelo.

## Para saber más

- Documentación oficial de LangChain: Agents y Tools – [https://python.langchain.com/docs/modules/agents/](https://python.langchain.com/docs/modules/agents/)
- Documentación de LangGraph – [https://langchain-ai.github.io/langgraph/](https://langchain-ai.github.io/langgraph/)
- Blog de LangChain: “LangGraph: Multi-Agent Workflows” – [https://blog.langchain.dev/langgraph-multi-agent-workflows/](https://blog.langchain.dev/langgraph-multi-agent-workflows/)
- Paper ReAct: “ReAct: Synergizing Reasoning and Acting in Language Models” – [https://arxiv.org/abs/2210.03629](https://arxiv.org/abs/2210.03629)
- Tutorial de agentes en LangChain por Harrison Chase (YouTube) – [https://www.youtube.com/watch?v=DWUdGhRrv2c](https://www.youtube.com/watch?v=DWUdGhRrv2c)