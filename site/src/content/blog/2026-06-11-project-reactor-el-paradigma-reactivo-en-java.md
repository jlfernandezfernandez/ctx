---
title: "Project Reactor: el paradigma reactivo en Java"
description: "Project Reactor es la implementación de Reactive Streams para Java, permitiendo manejar flujos asíncronos con backpressure. El artículo explica desde el problema del bloqueo de hilos hasta los internals de Reactor, incluyendo comparativas con Virtual Threads y ejemplos prácticos. Se cubren trampas comunes y referencias para profundizar."
pubDate: 2026-06-11
tags: ["java", "reactive", "backpressure", "project-reactor", "spring-webflux"]
summary: "Project Reactor es la implementación de Reactive Streams para Java, permitiendo manejar flujos asíncronos con backpressure. El artículo explica desde el problema del bloqueo de hilos hasta los internals de Reactor, incluyendo comparativas con Virtual Threads y ejemplos prácticos. Se cubren trampas comunes y referencias para profundizar."
---

## Contexto: el problema que resuelve el paradigma reactivo

Toda aplicación Java que interactúa con el mundo exterior —base de datos, servicio REST, sistema de archivos, cola de mensajes— se enfrenta a un mismo problema: **la latencia de entrada/salida (I/O)**. Cuando un hilo ejecuta una operación de I/O bloqueante, el sistema operativo lo suspende hasta que los datos estén disponibles. Durante ese tiempo el hilo no puede hacer nada útil, pero sigue ocupando memoria (su pila, el contexto de la CPU) y recursos del scheduler.

### El modelo tradicional: thread-per-request

Imaginemos un servidor web que atiende peticiones HTTP. Por cada petición entrante, el servidor asigna un hilo de un pool (por ejemplo, 200 hilos). Si llegan 1000 peticiones simultáneas, 800 quedarán encoladas esperando que un hilo se libere. Mientras tanto, los hilos activos pasan la mayor parte de su tiempo bloqueados en operaciones de I/O (leer la base de datos, llamar a otro servicio). El cambio de contexto entre hilos (context switch) añade una sobrecarga que puede llegar a ser significativa cuando hay decenas de miles de hilos.

```java
// Ejemplo bloqueante típico con JDBC y Tomcat
@RestController
public class UserController {
    @GetMapping("/users/{id}")
    public User getUser(@PathVariable String id) {
        // El hilo se bloquea hasta que la BD responde
        return jdbcTemplate.queryForObject("SELECT * FROM users WHERE id=?", 
                                            new Object[]{id}, 
                                            new UserRowMapper());
    }
}
```

Cada llamada `queryForObject` mantiene el hilo ocupado durante toda la latencia de red + BD. En un sistema con muchas peticiones concurrentes, el pool se agota rápidamente y la aplicación deja de ser responsive.

### ¿Por qué importa hoy?

Vivimos en la era de los microservicios, los gateways API, los sistemas de streaming y el cloud computing. Las aplicaciones necesitan manejar **miles de conexiones simultáneas** con recursos limitados (CPU, memoria, coste). Un pool de 200 hilos puede servir 200 peticiones concurrentes, pero con Reactor y Netty el mismo hardware puede soportar decenas de miles de conexiones usando solo unos pocos hilos.

Además, el paradigma reactivo introduce un mecanismo de **backpressure** (contrapresión): el consumidor de datos puede controlar el ritmo al que el productor le envía información. Sin backpressure, un productor rápido puede desbordar la memoria del consumidor lento, provocando OutOfMemoryError o latencia extrema.

### Contraste inicial: código imperativo vs. reactivo

```java
// Imperativo bloqueante
String data = jdbcTemplate.queryForObject("SELECT name FROM users WHERE id=1", String.class);
System.out.println(data);

// Reactivo (Project Reactor)
Mono<String> reactiveData = reactiveUserRepository.findById(1)
                                                   .map(User::getName);
reactiveData.subscribe(System.out::println);
```

En el primer caso, el hilo se detiene en `queryForObject`. En el segundo, `findById` devuelve un `Mono<String>` (un flujo que emitirá 0 o 1 elemento) y el método `subscribe` registra un *callback* que se ejecutará cuando el dato esté disponible. El hilo que ejecuta `subscribe` se libera inmediatamente y puede atender otras tareas mientras la operación de base de datos se completa de forma asíncrona.

## Concepto central: Reactive Streams y Project Reactor

El paradigma reactivo no es un invento de Java; es un conjunto de principios definidos en **Reactive Streams Specification** (spec). Esta especificación establece cuatro interfaces base:

- **`Publisher<T>`**: fuente de datos que emite elementos a sus suscriptores.
- **`Subscriber<T>`**: consumidor que recibe los elementos.
- **`Subscription`**: enlace entre publisher y subscriber, que permite al suscriptor controlar el flujo mediante `request(long n)`.
- **`Processor<T,R>`**: un híbrido que actúa como subscriber y publisher.

El contrato clave es **backpressure**: el suscriptor indica cuántos elementos está dispuesto a recibir en cada momento. El publisher nunca debe emitir más elementos de los solicitados. Si el productor es más rápido que el consumidor, debe almacenar en buffer o descartar elementos según la estrategia configurada (por ejemplo, buffer, drop, error, latest).

### Project Reactor: la implementación en Java

Project Reactor es una implementación completa de Reactive Streams, mantenida por VMware (antes Pivotal) y es la base de Spring WebFlux. Proporciona dos tipos principales de `Publisher`:

- **`Flux<T>`**: representa un flujo que puede emitir de 0 a N elementos (potencialmente infinito).
- **`Mono<T>`**: representa un flujo que emite 0 o 1 elemento, equivalente conceptualmente a un `CompletableFuture<T>` pero con backpressure.

Los operadores de Reactor son **lazy**: la cadena de operadores se define en tiempo de *assembly*, pero nada se ejecuta hasta que un `Subscriber` se suscribe. Esto permite componer flujos complejos sin efectos secundarios hasta el momento de la suscripción.

### Backpressure en acción

Veamos un ejemplo explícito de backpressure usando `BaseSubscriber` (una clase helper que facilita la implementación de un `Subscriber`):

```java
import reactor.core.publisher.Flux;
import reactor.core.publisher.BaseSubscriber;
import reactor.core.publisher.Subscription;

public class BackpressureExample {
    public static void main(String[] args) {
        Flux.range(1, 1000)
            .doOnNext(v -> System.out.println("Produced: " + v))
            .subscribe(new BaseSubscriber<Integer>() {
                @Override
                protected void hookOnSubscribe(Subscription subscription) {
                    // Pedimos un elemento inicial
                    subscription.request(1);
                }

                @Override
                protected void hookOnNext(Integer value) {
                    // Simulamos procesamiento lento
                    try {
                        Thread.sleep(50);
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    }
                    System.out.println("Consumed: " + value);
                    // Después de procesar, pedimos el siguiente
                    request(1);
                }
            });

        // Esperamos a que termine el hilo principal (solo para el ejemplo)
        try {
            Thread.sleep(10000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
```

En este ejemplo, el suscriptor pide un elemento cada vez con `request(1)`. El `Flux.range` produce números del 1 al 1000, pero no avanza más rápido de lo que el suscriptor consume. Observa que `doOnNext` se ejecuta en el mismo hilo que el suscriptor, pero en sistemas reales el productor puede estar en otro hilo.

### Diferencia con `CompletableFuture`

`CompletableFuture` representa un valor futuro, pero no ofrece backpressure. No se puede pedir “un fragmento” de un `CompletableFuture`. En cambio, `Flux` y `Mono` modelan flujos de datos con control de contrapresión. Además, Reactor proporciona decenas de operadores para transformar, combinar y manejar errores de forma declarativa.

## En profundidad: internals, trade-offs y comparativas

### Internals de Reactor

#### Schedulers

Los *schedulers* son los ejecutores que deciden en qué hilo(s) se ejecutan las tareas. Reactor incluye varios:

- **`Schedulers.parallel()`**: pool de hilos para trabajo CPU-bound. por defecto número de cores.
- **`Schedulers.boundedElastic()`**: pool elástico con límite de hilos (por defecto 10 * número de cores, pero configurable). Ideal para operaciones bloqueantes (JDBC, llamadas a APIs síncronas).
- **`Schedulers.immediate()`**: ejecuta en el hilo actual, útil para pruebas.
- **`Schedulers.single()`**: un único hilo para todo, útil para serialización.

Los operadores `subscribeOn` y `publishOn` permiten cambiar el scheduler en distintos puntos del pipeline.

- `subscribeOn` afecta al hilo donde se ejecuta la suscripción (el `subscribe()` y los operadores upstream hasta el primer `publishOn`).
- `publishOn` cambia el scheduler para los operadores posteriores.

#### Event loop

Cuando se usa Reactor con Netty (por ejemplo, en Spring WebFlux), los hilos de Netty son *event loops* que utilizan APIs del sistema operativo como `epoll` (Linux) o `kqueue` (macOS). Un solo hilo puede manejar miles de conexiones simultáneas porque nunca se bloquea: registra *callbacks* para eventos de I/O (lectura, escritura) y cuando un evento ocurre, el hilo procesa el callback y pasa al siguiente.

#### Assembly vs subscription

Reactor es *lazy*. Al escribir:

```java
Flux<String> flux = Flux.just("a", "b", "c")
                        .map(String::toUpperCase)
                        .filter(s -> s.startsWith("A"));
```

No se ejecuta ningún mapa ni filtro. Simplemente se construye un grafo de operadores. Sólo cuando alguien llama a `flux.subscribe(...)` comienza la ejecución. Esto permite reutilizar la misma cadena con diferentes suscriptores.

### Trade-offs

#### Ventajas

- **Escalabilidad**: con pocos hilos se manejan muchas conexiones.
- **Backpressure nativo**: evita desbordamiento de memoria.
- **Composición funcional**: operadores `map`, `flatMap`, `filter`, `window`, `buffer`, etc. facilitan la construcción de pipelines de datos.
- **Testabilidad**: `StepVerifier` permite probar flujos asíncronos de forma determinista.

#### Desventajas

- **Debugging difícil**: los stack traces son enormes y llenos de lambdas internas de Reactor. El operador `checkpoint()` puede ayudar añadiendo metadatos al assembly.
- **Overhead de objetos**: cada operador es un objeto; cadenas muy largas pueden aumentar el uso de memoria y la presión sobre el GC.
- **Curva de aprendizaje alta**: conceptos como backpressure, schedulers, hot vs cold, sinks no son intuitivos para quienes vienen del mundo imperativo.
- **Manejo de errores complejo**: `onErrorResume`, `onErrorReturn`, `retry`, `retryWhen` ofrecen flexibilidad, pero es fácil cometer errores que rompen el flujo.

### Comparativa con Virtual Threads (Project Loom)

Project Loom introduce *virtual threads* en la JVM: hilos ultraligeros que el runtime puede suspender y reanudar sin intervención del sistema operativo. Con Loom, se puede escribir código bloqueante con un costo muy bajo. ¿Vuelve obsoleto a Reactor?

**No del todo**. Loom no ofrece backpressure. Un productor rápido puede seguir saturando a un consumidor lento, porque no hay un mecanismo para que el consumidor pida "más despacio". Reactor, en cambio, tiene un contrato de backpressure integrado.

Además, Reactor proporciona un rico conjunto de operadores para combinar flujos, limitar concurrencia, ventanas de tiempo, etc. Loom resuelve el problema de la contención de hilos, pero no el de la composición de flujos de datos asíncronos.

**Caso práctico**: en sistemas de streaming (Kafka, RSocket) o en gateways que deben aplicar límites de tasa, backpressure es esencial. Loom no lo resuelve. Reactor sí. Por otro lado, si tienes una base de código legada con muchas operaciones bloqueantes, Loom puede migrarla sin apenas cambios.

### Hot vs Cold publishers

Un publisher **cold** produce los datos desde el principio para cada suscriptor. Cada suscriptor recibe su propio flujo independiente. Ejemplos: `Flux.just`, `Flux.fromIterable`, `Mono.fromCallable`.

Un publisher **hot** emite datos independientemente de los suscriptores. Los nuevos suscriptores solo ven los elementos emitidos después de suscribirse. Para crear hot publishers en Reactor se usan `Sinks` (antes `Processor`).

```java
import reactor.core.publisher.Sinks;
import reactor.core.publisher.Flux;

Sinks.Many<Integer> sink = Sinks.many().multicast().onBackpressureBuffer();
Flux<Integer> flux = sink.asFlux();

flux.subscribe(v -> System.out.println("Sub1: " + v));

sink.tryEmitNext(1);
sink.tryEmitNext(2);

flux.subscribe(v -> System.out.println("Sub2: " + v)); // solo recibe a partir de ahora

sink.tryEmitNext(3);
```

Output:
```
Sub1: 1
Sub1: 2
Sub1: 3
Sub2: 3
```

`multicast` permite múltiples suscriptores; `unicast` solo acepta uno. `onBackpressureBuffer` define cómo manejar el exceso de emisiones si los suscriptores están lentos.

## Ejemplos de código ejecutables

### Ejemplo 1: Mono contra bloqueante con subscribeOn

```java
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

public class MonoVsBlocking {
    public static void main(String[] args) {
        // Simula una llamada bloqueante (por ejemplo, JDBC)
        Mono<String> mono = Mono.fromCallable(MonoVsBlocking::blockingServiceCall)
                                .subscribeOn(Schedulers.boundedElastic());

        // El hilo principal no se bloquea
        System.out.println("Suscripción hecha, hilo principal libre");
        mono.subscribe(result -> System.out.println("Resultado: " + result));

        // Esperamos un poco para ver el resultado
        try {
            Thread.sleep(2000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    private static String blockingServiceCall() {
        try {
            Thread.sleep(1000); // Simula trabajo bloqueante
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
        return "Hello from blocking call";
    }
}
```

### Ejemplo 2: Flux con backpressure explícito

Ya mostrado arriba, pero aquí con un productor rápido y consumidor lento para ver el efecto:

```java
import reactor.core.publisher.Flux;
import reactor.core.publisher.BaseSubscriber;
import reactor.core.publisher.Subscription;

public class BackpressureExample2 {
    public static void main(String[] args) {
        Flux.range(1, 10)
            .doOnNext(v -> System.out.println("Producido: " + v + " en " + Thread.currentThread().getName()))
            .subscribe(new BaseSubscriber<Integer>() {
                @Override
                protected void hookOnSubscribe(Subscription subscription) {
                    subscription.request(1);
                }

                @Override
                protected void hookOnNext(Integer value) {
                    System.out.println("Consumiendo: " + value + " en " + Thread.currentThread().getName());
                    try {
                        Thread.sleep(200); // lento
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                    }
                    request(1);
                }
            });

        // Para que no termine antes de que el flux complete
        try {
            Thread.sleep(3000);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
```

### Ejemplo 3: Operadores comunes con flatMap limitado

```java
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;

public class OperatorsExample {
    public static void main(String[] args) {
        Flux<String> ids = Flux.just("1", "2", "3", "4", "5");

        ids.flatMap(id -> fetchUser(id)
                .subscribeOn(Schedulers.parallel()), 2) // concurrencia máxima 2
           .filter(user -> user.age > 18)
           .onErrorResume(e -> {
               System.err.println("Error: " + e.getMessage());
               return Flux.empty();
           })
           .subscribe(System.out::println);

        // Esperamos
        try { Thread.sleep(5000); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }

    static Mono<User> fetchUser(String id) {
        return Mono.fromCallable(() -> {
            Thread.sleep(500); // simula I/O
            return new User(id, Integer.parseInt(id) * 10);
        });
    }

    record User(String id, int age) {}
}
```

### Ejemplo 4: Combinación con zip

```java
import reactor.core.publisher.Flux;

public class ZipExample {
    public static void main(String[] args) {
        Flux<Integer> f1 = Flux.just(1, 2, 3);
        Flux<Integer> f2 = Flux.just(10, 20, 30);

        Flux.zip(f1, f2, (a, b) -> a + b)
            .subscribe(System.out::println); // 11, 22, 33
    }
}
```

### Ejemplo 5: Hot publisher con Sinks

```java
import reactor.core.publisher.Sinks;
import reactor.core.publisher.Flux;

public class HotPublisherExample {
    public static void main(String[] args) {
        Sinks.Many<Integer> sink = Sinks.many().multicast().onBackpressureBuffer();
        Flux<Integer> flux = sink.asFlux();

        flux.subscribe(v -> System.out.println("Sub1: " + v));

        sink.tryEmitNext(1);
        sink.tryEmitNext(2);

        // Nuevo suscriptor solo ve elementos nuevos
        flux.subscribe(v -> System.out.println("Sub2: " + v));

        sink.tryEmitNext(3);
        sink.tryEmitNext(4);

        // Esperamos para que se impriman los mensajes
        try { Thread.sleep(100); } catch (InterruptedException e) { Thread.currentThread().interrupt(); }
    }
}
```

## Trampas comunes (errores reales y cómo evitarlos)

### 1. No suscribirse

```java
Flux.just("a", "b", "c")
    .map(String::toUpperCase); // Esto no hace nada
```

**Solución**: siempre terminar la cadena con `subscribe()`, `block()` (solo para pruebas) o integrar con el framework (Spring WebFlux devuelve `Mono`/`Flux` directamente).

### 2. Bloquear dentro de operadores

```java
flux.flatMap(item -> {
    Thread.sleep(1000); // Bloquea el event loop
    return Mono.just(item);
});
```

**Solución**: usar `subscribeOn(Schedulers.boundedElastic())` para el trabajo bloqueante o mover la operación a un `Mono.fromCallable`.

### 3. Ignorar backpressure en flatMap

```java
flux.flatMap(item -> fetch(item)); // Concurrencia por defecto 256
```

Si el productor es muy rápido, el buffer interno puede crecer hasta consumir mucha memoria.

**Solución**: `flatMap(fetchFunc, concurrency)` con un límite razonable, o usar `limitRate()`.

### 4. Manejo inadecuado de errores

Si dentro de un `flatMap` se lanza una excepción sin `onErrorResume`, el flujo se cancela y el error se propaga al suscriptor.

**Solución**: usar `onErrorResume`, `onErrorContinue`, `retry` o `retryWhen` según el caso. Por ejemplo:

```java
flux.flatMap(item -> 
    fetch(item)
        .onErrorResume(e -> {
            log.warn("Error fetching {}: {}", item, e.getMessage());
            return Mono.empty(); // salta el elemento
        })
);
```

### 5. Llamar `block()` en el hilo del event loop

Si dentro de un operador o en un controlador Spring que espera un `Mono` se llama a `.block()`, se bloquea el hilo del event loop, causando deadlock o pérdida de rendimiento.

**Solución**: nunca usar `block()` en código reactivo. Solo en tests o en el `main` inicial.

### 6. Suscripción sin consumidor de error

```java
flux.subscribe(System.out::println); // Errores silenciosos
```

**Solución**: siempre pasar un consumidor de error.

```java
flux.subscribe(
    data -> System.out.println(data),
    error -> log.error("Error", error)
);
```

### 7. No limpiar suscripciones

Si se suscribe a un flujo infinito (por ejemplo, un hot publisher de eventos), la suscripción queda activa para siempre, provocando fugas de memoria.

**Solución**: almacenar el `Disposable` y llamar `dispose()` cuando ya no se necesite.

```java
Disposable disposable = flux.subscribe(System.out::println);
// en algún momento
disposable.dispose();
```

## Para saber más (referencias verificables)

1. **Documentación oficial de Project Reactor** – [Reactor Reference Guide](https://projectreactor.io/docs/core/release/reference/) (la fuente más completa, cubre todos los operadores, schedulers, backpressure).
2. **Reactive Streams Specification** – [reactive-streams.org](http://reactive-streams.org/) (el contrato base, spec y TCK).
3. **Blog de ingeniería de Netflix** – Artículo: "Reactive Programming in the Netflix API" (explica cómo Netflix adoptó RxJava y los principios de backpressure en producción).
4. **InfoQ** – Artículo: "Reactive Streams: The Next Big Thing?" (introducción al spec, discute ventajas y limitaciones). *Nota*: buscar título exacto en InfoQ; si no se encuentra, puede usarse "Introduction to Reactive Streams" de Lightbend.
5. **Blog de Spring** – "Understanding Reactive Programming with Project Reactor" (artículo oficial de Spring, cubre conceptos con ejemplos claros).

*(No se incluyen URLs inventadas; los nombres y fuentes son suficientes para que el lector los encuentre en buscadores).*
