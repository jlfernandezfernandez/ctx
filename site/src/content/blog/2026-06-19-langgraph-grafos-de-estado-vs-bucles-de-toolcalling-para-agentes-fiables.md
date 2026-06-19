---
title: "LangGraph: Grafos de estado vs. bucles de tool‑calling para agentes fiables"
description: "El bucle de tool‑calling es suficiente para agentes lineales, pero falla cuando se necesita bifurcación por reglas de negocio, aprobación humana o recuperación granular. LangGraph modela el proceso como un grafo de estados con checkpoints, permitiendo pausar, persistir y reanudar desde el punto exacto. Se detalla el criterio de decisión y un ejemplo de flujo de pagos con intervención humana e idempotencia."
date: 2026-06-19
tags: ["ai-agents", "state-machines"]
summary: "El bucle de tool‑calling es suficiente para agentes lineales, pero falla cuando se necesita bifurcación por reglas de negocio, aprobación humana o recuperación granular. LangGraph modela el proceso como un grafo de estados con checkpoints, permitiendo pausar, persistir y reanudar desde el punto exacto. Se detalla el criterio de decisión y un ejemplo de flujo de pagos con intervención humana e idempotencia."
issue: 24
requestedBy: "jlfernandezfernandez"
writer: "deepseek-v4-pro"
reviewer: "minimax-m3"
---

El bucle autónomo: tool‑calling como máquina de estados efímera
------------------------------------------------------------------------

Un agente que razona y actúa mediante herramientas sigue un patrón sencillo: el modelo recibe una lista de mensajes, decide si necesita invocar herramientas, el executor las ejecuta y los resultados se añaden al historial. El ciclo se repite hasta que el modelo emite una respuesta final sin `tool_calls`. En LangChain, `create_react_agent` (de `langgraph.prebuilt`) encapsula este bucle en un grafo mínimo que solo conserva la lista de mensajes como estado.

```python
from langgraph.prebuilt import create_react_agent
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

@tool
def get_balance(account: str) -> float:
    """Devuelve el saldo de una cuenta."""
    return 1500.0

@tool
def transfer(from_acc: str, to_acc: str, amount: float) -> str:
    """Transfiere fondos entre cuentas."""
    return f"Transferencia de {amount} de {from_acc} a {to_acc} completada"

model = ChatOpenAI(model="gpt-4o")
agent = create_react_agent(model, [get_balance, transfer])

# Ejecución única, sin estado persistente
result = agent.invoke({"messages": [{"role": "user", "content": "Transfiere 200 de main a savings"}]})
```

El estado real es solo la lista de mensajes. No hay checkpoint, no hay memoria entre ejecuciones, no hay noción de “paso completado”. El modelo decide la siguiente herramienta basándose en el historial, pero no puede evaluar una regla de negocio como `if amount > 1000` sin invocar otra herramienta que devuelva el resultado. Si se necesita aprobación humana, el bucle debe detenerse artificialmente y no existe una forma estándar de reanudar con estado. Si una herramienta lanza una excepción, el modelo puede reintentarlo, pero no hay garantía de idempotencia ni reintentos con backoff gestionados por la orquestación.

Donde el bucle se rompe: un flujo de aprobación de gastos
----------------------------------------------------------

Imaginemos un agente que debe ejecutar un pago, pero si el importe supera 1000 € necesita aprobación humana. Además, el pago debe ser idempotente y recuperable si el servicio de pago falla.

Un intento con el bucle simple añadiría herramientas como `check_budget(amount)` y `request_approval(amount)`. El modelo vería que `check_budget` devuelve `{"exceeds": true}` y decidiría llamar a `request_approval`. Pero esa herramienta no puede pausar el proceso y esperar una acción externa; se necesitaría un mecanismo ad‑hoc de polling o una segunda invocación del agente con estado externo. Si el pago falla después de la aprobación, el progreso se pierde: reintentar requiere re‑ejecutar todo el bucle desde cero, repitiendo la aprobación.

El bucle no ofrece primitivas para *pausar*, *persistir* el punto exacto de ejecución ni *reanudar* desde ahí. La responsabilidad de la orquestación —cuándo detenerse, cómo recuperarse— queda fuera de su alcance.

Modelando el proceso como grafo de estado
-----------------------------------------

LangGraph introduce un modelo explícito: un `StateGraph` donde el estado es un diccionario tipado que persiste entre nodos, las transiciones pueden ser condicionales y un `checkpointer` guarda el estado tras cada super‑paso. Esto permite bifurcar según lógica de negocio, interrumpir para intervención humana y recuperar desde el último checkpoint.

```python
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command, interrupt
from langchain_core.messages import add_messages
import uuid

class PaymentState(TypedDict):
    messages: Annotated[list, add_messages]
    amount: float
    approved: bool
    payment_id: str | None

def check_budget(state: PaymentState):
    # Simula consulta de presupuesto
    amount = state["amount"]
    exceeds = amount > 1000
    return {"messages": [{"role": "tool", "content": f"Budget check: exceeds={exceeds}"}],
            "amount": amount}

def request_approval(state: PaymentState):
    # Nodo que se interrumpe para esperar decisión humana
    decision = interrupt("Aprobación requerida")
    return {"approved": decision, "messages": [{"role": "tool", "content": f"Aprobado: {decision}"}]}

def execute_payment(state: PaymentState):
    payment_id = str(uuid.uuid4())
    # Llamada idempotente con payment_id como clave
    # Si falla, lanza NodeInterrupt para reintentar desde aquí
    return {"payment_id": payment_id, "messages": [{"role": "tool", "content": f"Pago {payment_id} ejecutado"}]}

builder = StateGraph(PaymentState)
builder.add_node("check_budget", check_budget)
builder.add_node("request_approval", request_approval)
builder.add_node("execute_payment", execute_payment)

builder.add_edge(START, "check_budget")
builder.add_conditional_edges("check_budget",
    lambda state: "execute_payment" if state["amount"] <= 1000 else "request_approval")
builder.add_edge("request_approval", "execute_payment")
builder.add_edge("execute_payment", END)

checkpointer = MemorySaver()
graph = builder.compile(checkpointer=checkpointer)
```

El grafo se detiene en el nodo `request_approval` mediante `interrupt()`. Un sistema externo notifica al humano, quien reanuda con:

```python
graph.invoke(Command(resume=True), config={"configurable": {"thread_id": "txn-123"}})
```

El `Command(resume=True)` inyecta la decisión en el `interrupt` y el grafo continúa. Si `execute_payment` falla, podemos lanzar `NodeInterrupt`; el checkpoint anterior permite re‑intentar solo ese nodo, conservando la aprobación.

Recuperación, reintentos e idempotencia
--------------------------------------

La persistencia del estado en cada super‑paso es la base de la durabilidad. Si el nodo de pago falla, el grafo puede reanudarse desde el checkpoint inmediatamente anterior, sin repetir la aprobación. La idempotencia se garantiza generando una clave única —por ejemplo, un `payment_id` basado en el `thread_id` y el número de intento— que el servicio de pago usa para deduplicar.

Para reintentos con backoff, se puede añadir un nodo de fallback que reintente el pago o derive a una cola de errores, manteniendo el resto del estado intacto. La intervención humana es real: el grafo se detiene, persiste el estado, notifica y espera; el humano actualiza el estado con `graph.update_state` y reanuda.

El coste de introducir un grafo: cuándo no usarlo
--------------------------------------------------

Modelar un proceso como grafo añade complejidad: hay que definir el esquema de estado, los nodos, las aristas y el checkpointer. La depuración se vuelve más difícil porque hay que inspeccionar trazas de grafo y estados intermedios. Además, cada transición persiste estado (I/O) y añade latencia frente al bucle directo.

El criterio de decisión no es técnico sino de responsabilidad. Usa el bucle de tool‑calling cuando el flujo es lineal, el modelo puede decidir el siguiente paso sin reglas externas, no hay intervención humana ni necesidad de recuperación granular. Introduce el grafo cuando necesitas:

- Bifurcaciones basadas en lógica de negocio, no solo en el output del modelo.
- Pausas para aprobación humana con reanudación desde el punto exacto.
- Reintentos con garantía de no duplicar efectos laterales.
- Recuperación tras fallos sin re‑ejecutar pasos ya completados.

La frontera es clara: el modelo decide *qué* hacer; el grafo decide *cuándo* y *cómo* se ejecuta, asegurando coherencia y durabilidad. Cuando tu proceso solo necesita la inteligencia del modelo para encadenar herramientas, el bucle es suficiente. Cuando la orquestación fiable importa más que la latencia, el grafo es la herramienta adecuada.