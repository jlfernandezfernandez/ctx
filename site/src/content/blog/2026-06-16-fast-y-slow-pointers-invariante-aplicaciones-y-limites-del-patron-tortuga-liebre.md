---
title: "Fast y slow pointers: invariante, aplicaciones y límites del patrón tortuga-liebre"
description: "Dos punteros que avanzan a distinta velocidad crean una relación de distancia predecible que permite detectar ciclos, encontrar puntos medios y localizar entradas de ciclo en secuencias unidireccionales. El invariante matemático 2(a+b)=a+b+nL garantiza la corrección del algoritmo de Floyd y sus extensiones a problemas como el duplicado en arrays. La técnica exige una función next determinista y un ratio de velocidad coprimo con la longitud del ciclo, y ofrece complejidad O(n) en tiempo y O(1) en espacio."
date: 2026-06-16
tags: ["algorithms"]
summary: "Dos punteros que avanzan a distinta velocidad crean una relación de distancia predecible que permite detectar ciclos, encontrar puntos medios y localizar entradas de ciclo en secuencias unidireccionales. El invariante matemático 2(a+b)=a+b+nL garantiza la corrección del algoritmo de Floyd y sus extensiones a problemas como el duplicado en arrays. La técnica exige una función next determinista y un ratio de velocidad coprimo con la longitud del ciclo, y ofrece complejidad O(n) en tiempo y O(1) en espacio."
issue: 30
requestedBy: "charliecgu"
writer: "deepseek-v4-pro"
reviewer: "minimax-m3"
---

La técnica de fast and slow pointers —también conocida como tortoise and hare— resuelve múltiples problemas sobre secuencias con una idea sorprendentemente simple: dos referencias que avanzan a distinta velocidad crean una relación de distancia predecible. Esa relación permite detectar ciclos, encontrar puntos medios o localizar entradas de ciclo sin memoria adicional. El patrón no se limita a listas enlazadas; cualquier estructura con una función `next` determinista y un único sucesor por elemento puede analizarse con él. Su potencia está en el invariante matemático que gobierna el encuentro de los punteros, y sus limitaciones aparecen cuando la secuencia no es unidireccional o se rompe la relación de pasos.

## El invariante que lo sostiene todo

Dos punteros recorren una secuencia: `slow` avanza un paso por iteración, `fast` avanza dos. En una secuencia lineal sin ciclos, `fast` llega al final cuando `slow` ha recorrido exactamente la mitad de la distancia. Esta relación 2:1 de distancias recorridas es trivial pero útil: permite encontrar el nodo medio de una lista enlazada en una sola pasada.

En una secuencia con ciclo, el invariante es más interesante. Supongamos una estructura donde cada elemento tiene un sucesor único. Si existe un ciclo, los punteros terminarán entrando en él. Una vez ambos están dentro del ciclo, `fast` persigue a `slow` con una velocidad relativa de 1 paso por iteración (avanza 2, `slow` avanza 1, la distancia entre ellos se reduce en 1 por iteración). Como la longitud del ciclo L es finita, la distancia entre ellos dentro del ciclo eventualmente se reduce a cero: se encuentran. La velocidad relativa de 1 garantiza el encuentro para cualquier L porque 1 y L son coprimos.

El punto de encuentro codifica información estructural. Si la distancia desde la cabeza hasta la entrada del ciclo es `a`, la distancia desde la entrada del ciclo hasta el punto de encuentro (medida dentro del ciclo) es `b`, y la longitud del ciclo es `L`, entonces:

- `slow` recorre `a + b` pasos hasta el encuentro.
- `fast` recorre `a + b + nL` pasos para algún entero `n ≥ 1` (da vueltas extra dentro del ciclo).
- Como `fast` avanza al doble de velocidad: `2(a + b) = a + b + nL`.
- Simplificando: `a + b = nL`, por lo que `a = nL - b`.

Esto significa que la distancia desde la cabeza hasta la entrada del ciclo (`a`) es igual a un múltiplo de la longitud del ciclo menos la distancia desde la entrada hasta el punto de encuentro (`b`). Si reiniciamos un puntero a la cabeza y movemos ambos a un paso por iteración desde la cabeza y desde el punto de encuentro, coincidirán exactamente en la entrada del ciclo tras `a` pasos. El puntero que parte del punto de encuentro recorrerá `nL - b`, que lo deja justo en la entrada. Esta derivación es el núcleo del algoritmo de Floyd para encontrar la entrada del ciclo.

## Detección de ciclos: el algoritmo de Floyd

El problema canónico: determinar si una lista simplemente enlazada contiene un ciclo. La estructura de datos es mínima:

```python
class ListNode:
    def __init__(self, val=0, next=None):
        self.val = val
        self.next = next
```

El algoritmo avanza `fast` y `slow` hasta que coinciden o `fast` encuentra un `None`:

```python
def has_cycle(head: ListNode) -> bool:
    slow = fast = head
    while fast and fast.next:
        slow = slow.next
        fast = fast.next.next
        if slow == fast:
            return True
    return False
```

La condición `fast and fast.next` es crítica: `fast` avanza dos pasos, por lo que hay que verificar que tanto el nodo actual como el siguiente existen antes de moverlo. Omitir esta comprobación produce `AttributeError` cuando `fast.next` es `None`. En ciclos de longitud 1 —un nodo que se apunta a sí mismo— el algoritmo funciona correctamente porque `fast` y `slow` coinciden en la primera iteración.

Complejidad: O(n) tiempo, O(1) espacio. En el peor caso sin ciclo, `fast` recorre la lista completa (n nodos) en n/2 iteraciones. Con ciclo, el número de iteraciones está acotado por la distancia al ciclo más la longitud del ciclo. Frente a la alternativa de usar un hash set para registrar nodos visitados, el algoritmo de Floyd elimina el coste O(n) de memoria, pero exige un manejo cuidadoso de punteros.

## Localizar la entrada del ciclo

Detectar el ciclo es solo el primer paso. Para encontrar el nodo donde comienza, aplicamos la derivación del invariante:

```python
def detect_cycle(head: ListNode) -> ListNode | None:
    slow = fast = head
    while fast and fast.next:
        slow = slow.next
        fast = fast.next.next
        if slow == fast:
            # Ciclo detectado: buscar entrada
            slow = head
            while slow != fast:
                slow = slow.next
                fast = fast.next
            return slow
    return None
```

Tras el encuentro, reiniciamos `slow` a `head` y movemos ambos a un paso. El nodo donde coinciden es la entrada del ciclo. La justificación matemática está en el invariante: el puntero desde la cabeza recorre `a`, el puntero desde el punto de encuentro recorre `nL - b`, y ambos llegan a la entrada simultáneamente.

Un error frecuente es mover `fast` a dos pasos también en esta segunda fase. La derivación exige que ambos avancen a la misma velocidad (1 paso) para que la distancia relativa se mantenga y coincidan en la entrada.

En sistemas reales, este algoritmo identifica el origen de un bucle de reenvío en una cadena de proxies o la raíz de una referencia circular en estructuras de memoria. Si modelamos un grafo de dependencias como una función `next`, encontrar la entrada del ciclo señala el nodo responsable de la circularidad.

## El nodo medio en una pasada

Encontrar el nodo medio de una lista enlazada es un paso previo en algoritmos como merge sort sobre listas o en la verificación de palíndromos. Con fast y slow pointers se obtiene en O(n) tiempo y O(1) espacio:

```python
def middle_node(head: ListNode) -> ListNode | None:
    slow = fast = head
    while fast and fast.next:
        slow = slow.next
        fast = fast.next.next
    return slow
```

Cuando `fast` es `None` (longitud par) o `fast.next` es `None` (longitud impar), `slow` apunta al nodo medio. Para listas de longitud par, este código devuelve el segundo nodo medio. Si se necesita el primer nodo medio, se puede ajustar la condición o usar un puntero `prev` que siga a `slow`. La elección depende del problema concreto: para dividir una lista en dos mitades, el segundo nodo medio como inicio de la segunda mitad es la convención habitual.

Casos borde: lista vacía (devuelve `None`), un solo nodo (el bucle no se ejecuta, devuelve `head`). La condición `fast and fast.next` maneja ambos correctamente.

## Verificar palíndromos sin memoria extra

Comprobar si una lista enlazada es un palíndromo —se lee igual hacia adelante que hacia atrás— puede hacerse en O(n) tiempo y O(1) espacio combinando fast/slow para encontrar el medio, inversión in situ de la segunda mitad, y comparación:

```python
def is_palindrome(head: ListNode) -> bool:
    if not head or not head.next:
        return True

    # 1. Encontrar el medio (segundo nodo medio si longitud par)
    slow = fast = head
    while fast and fast.next:
        slow = slow.next
        fast = fast.next.next

    # 2. Invertir la segunda mitad desde slow
    prev = None
    while slow:
        next_temp = slow.next
        slow.next = prev
        prev = slow
        slow = next_temp
    second_half = prev  # cabeza de la mitad invertida

    # 3. Comparar primera mitad con segunda mitad invertida
    first_half = head
    result = True
    while second_half:
        if first_half.val != second_half.val:
            result = False
            break
        first_half = first_half.next
        second_half = second_half.next

    # 4. Restaurar la segunda mitad (opcional pero buena práctica)
    # ... (inversión de nuevo sobre prev)

    return result
```

La inversión in situ modifica la lista. Si el contrato de la función exige no alterar la estructura original, hay que restaurar la segunda mitad tras la comparación. El manejo de longitud par e impar es automático: para longitud impar, el nodo central queda en la primera mitad y no se compara, lo cual es correcto para un palíndromo.

Un error común es no considerar que `slow` avanza hasta que `fast` y `fast.next` son válidos, lo que deja `slow` en el nodo correcto para empezar la segunda mitad tanto en listas pares como impares.

## El patrón más allá de las listas: arrays y el problema del duplicado

La abstracción real de fast and slow pointers no depende de nodos y referencias, sino de una función `next` que mapea cada elemento a un sucesor único. Mientras exista esa función, podemos aplicar el patrón.

El problema del duplicado en un array lo ilustra: dado un array `nums` de `n + 1` enteros donde cada valor está en `[1, n]`, hay exactamente un número repetido. Encontrarlo sin modificar el array y con O(1) espacio extra parece imposible con enfoques convencionales, pero se reduce a detección de ciclos.

Tratamos el array como una función `f(i) = nums[i]`. Comenzando en `i = 0`, la secuencia `i, f(i), f(f(i)), ...` necesariamente contiene un ciclo porque el rango de valores `[1, n]` fuerza que algún índice se visite dos veces (principio del palomar). El valor duplicado es la entrada del ciclo: es el primer valor que se repite en la secuencia, y coincide con el nodo donde el ciclo comienza.

```python
def find_duplicate(nums: list[int]) -> int:
    # Fase 1: detectar ciclo
    slow = fast = nums[0]
    while True:
        slow = nums[slow]
        fast = nums[nums[fast]]
        if slow == fast:
            break

    # Fase 2: encontrar entrada del ciclo
    slow = nums[0]
    while slow != fast:
        slow = nums[slow]
        fast = nums[fast]

    return slow
```

Aquí `nums[0]` actúa como la cabeza de la secuencia. La función `next` es `nums[i]`. El código es estructuralmente idéntico al de listas enlazadas, pero opera sobre índices de un array. La restricción de no modificar el array se cumple; el espacio extra es O(1).

Este ejemplo muestra que el patrón no es una técnica de listas enlazadas, sino una técnica de secuencias unidireccionales. Cualquier problema que pueda modelarse como una función `next` determinista con un único sucesor es candidato.

## Cuándo usar fast and slow pointers: dominio y limitaciones

El patrón exige tres condiciones:

1. **Secuencia unidireccional**: cada elemento tiene exactamente un sucesor (o ninguno, en el caso terminal).
2. **Función `next` bien definida**: el sucesor es determinista y accesible en O(1).
3. **Ratio de velocidad con velocidad relativa coprima con la longitud del ciclo**: el ratio 2:1 (velocidad relativa 1) funciona para cualquier longitud de ciclo. Un ratio 3:1 (velocidad relativa 2) no garantiza encuentro si la longitud del ciclo es par, porque la distancia relativa puede saltar sobre el puntero lento sin coincidir.

No aplica directamente a listas doblemente enlazadas si se usan ambos sentidos, ni a árboles o grafos con múltiples caminos posibles desde un nodo. En esos casos, la noción de "sucesor único" se rompe.

Frente a la alternativa de usar un hash set para detección de ciclos, fast/slow ofrece O(1) espacio pero requiere manejo cuidadoso de condiciones de borde. El hash set es más simple de implementar y no corre riesgo de bucles infinitos por errores de puntero, pero consume O(n) memoria. La elección depende de las restricciones del sistema: en entornos con memoria limitada o donde la estructura es enorme, fast/slow es preferible; en prototipos o cuando la claridad prima, el hash set puede ser adecuado.

Errores frecuentes al implementar:

- No verificar `fast.next` y `fast.next.next` antes de avanzar, causando excepciones en listas sin ciclo.
- Elegir incorrectamente el nodo medio (primer vs. segundo medio) sin ajustar la condición de parada.
- Usar ratios de velocidad no coprimos con la longitud del ciclo, lo que puede impedir el encuentro.
- En el problema del duplicado, olvidar que la secuencia empieza en `nums[0]`, no en `0`, porque `0` no está en el rango `[1, n]` y no puede ser un valor del array.

## Aplicaciones en sistemas reales

El valor del patrón trasciende las entrevistas de algoritmos. En procesamiento de paquetes de red, dos sondas enviadas a distintas velocidades por una cadena de reenvío pueden detectar bucles de enrutamiento: si las sondas se encuentran, hay un ciclo, y el punto de encuentro señala el router donde comienza el bucle.

En gestión de memoria, los garbage collectors que operan sobre estructuras simplemente enlazadas pueden usar fast/slow para identificar ciclos de referencias sin necesidad de marcar objetos, ahorrando metadatos.

En sistemas distribuidos, máquinas de estados replicadas o protocolos de elección de líder pueden entrar en bucles infinitos donde los mensajes circulan sin progreso. El patrón ofrece un modelo mental para razonar sobre progreso cíclico: si dos marcas de tiempo o dos contadores enviados a distinta frecuencia muestran una relación predecible, el sistema avanza; si la relación se rompe, hay un ciclo.

La técnica no es solo un truco de código, sino una herramienta de razonamiento sobre secuencias y progreso. Reconocer cuándo un problema se reduce a una función `next` es la habilidad que la hace aplicable en dominios inesperados.

## El invariante como principio unificador

Detección de ciclos, nodo medio, palíndromos y búsqueda de duplicados parecen problemas dispares. La técnica de fast and slow pointers los unifica bajo un mismo invariante: la diferencia de velocidad crea una relación de distancia que codifica propiedades estructurales de la secuencia. La derivación matemática no es un adorno; es la garantía de corrección que permite aplicar el patrón con confianza en contextos nuevos.

La próxima vez que te enfrentes a una secuencia con una función `next` bien definida, pregúntate si dos punteros a distintas velocidades pueden revelar algo sobre su estructura. La respuesta, con frecuencia, es sí.
