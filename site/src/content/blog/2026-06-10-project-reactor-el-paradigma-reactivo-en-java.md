---
title: "Project Reactor: el paradigma reactivo en Java"
description: "Las aplicaciones Java tradicionales se construyen sobre un modelo de servidor por hilo: cada petición entrante asigna un hilo del sistema operativo, que ejecuta el código de principio a fin de forma b"
pubDate: 2026-06-10
tags: ["java"]
---

## Contexto: el problema que resuelve Reactor

### El cuello de botella del modelo thread-per-request

Las aplicaciones Java tradicionales se construyen sobre un modelo de servidor por hilo: cada petición entrante asigna un hilo del sistema operativo, que ejecuta el código de principio a fin de forma bloqueante. Cuando ese código realiza una operación de E/S (leer de base de datos, llamar a un servicio REST, escribir en un archivo), el hilo se bloquea y queda inactivo hasta que la operación completa. Este diseño es sencillo y predecible, pero tiene un coste enorme en concurrencia.

Cada hilo consume memoria de pila (~1 MB por defecto en JVM), y el cambio de contexto (context switching) entre hilos es caro: guardar/restaurar registros, TLB, cachés de CPU. Con miles de peticiones simultáneas, los hilos compiten por la CPU y la memoria, y el sistema entra en contención. El problema C10K (manejar 10 000 conexiones simultáneas) se vuelve inviable con este modelo a menos que se recurra a técnicas como hilos virtuales o asincronía.

### Java no es reactivo por sí mismo

Java proporciona `Future`, `CompletableFuture` y el fork-join pool para asincronía, pero estas herramientas adolecen de limitaciones fundamentales:

- **Sin backpressure**: un `CompletableFuture` no permite al consumidor controlar la velocidad de producción. Cuando se encadenan llamadas asíncronas, el productor simplemente empuja resultados y el consumidor los recibe todos a la vez, sin posibilidad de frenar.
- **Composición limitada**: combinar múltiples flujos asíncronos requiere código complejo con `thenCombine`, `allOf`, etc., y no hay una forma natural de manejar errores en medio de secuencias largas.
- **No hay contra-presión**: si un productor genera datos más rápido de lo que el consumidor puede procesar, los datos se acumulan en buffers ilimitados o se pierden. En aplicaciones de streaming o grandes volúmenes de datos, esto lleva a `OutOfMemoryError`.

Veamos un ejemplo imperativo bloqueante que lee un archivo línea a línea:

```java
import java.io.*;
import java.nio.file.*;

public class ImperativeFileReader {
    public static void main(String[] args) throws IOException {
        Path path = Path.of("datos.txt");
        try (BufferedReader reader = Files.newBufferedReader(path)) {
            String line;
            while ((line = reader.readLine()) != null) {
                // Procesar línea (simulado)
                System.out.println("Procesando: " + line);
                // Si el procesamiento es lento, el hilo está bloqueado
            }
        }
    }
}
```

Si el archivo tiene 1 000 000 de líneas, se cargan todas en memoria (a través del buffer interno de `BufferedReader`, que normalmente es pequeño, pero el productor —la JVM— sigue leyendo del disco). Si el consumidor (procesamiento) va más lento, el buffer del sistema operativo se llena y se produce contención, pero no hay un mecanismo explícito de backpressure: el hilo se bloquea en `readLine()`, y eso frena la producción, pero es un bloqueo implícito y no controlado por el consumidor.

### El ecosistema reactive-streams

Para resolver estos problemas, nace la especificación **Reactive Streams** (reactive-streams.org), que define un conjunto de interfaces mínimas:

- `Publisher<T>`: fuente de datos, produce elementos bajo demanda.
- `Subscriber<T>`: consumidor, recibe datos y señales de finalización/error.
- `Subscription`: enlace entre ambos; el único método crítico es `request(long n)`, con el que el consumidor indica cuántos elementos puede procesar.
- `Processor<T,R>`: ambos a la vez.

Project Reactor es una implementación de Reactive Streams para Java 8+ que añade dos tipos principales: **Mono** (0 o 1 elemento) y **Flux** (0 a N elementos). Ambos implementan `Publisher` y proporcionan cientos de operadores que se encadenan para transformar, filtrar, combinar y controlar flujos de datos, siempre respetando la backpressure.

## Concepto central: flujo con backpressure

### De pull a push negociado

En el modelo síncrono, el consumidor **tira** (pull) de los datos: llama a un método como `readLine()` que bloquea hasta que hay datos. En el modelo reactivo, el productor **empuja** (push) los datos, pero solo cuando el consumidor ha indicado cuántos está dispuesto a recibir. La clave es el método `request(n)`: el suscriptor envía una señal de demanda, y el publicador responde emitiendo hasta `n` elementos. Después, el suscriptor puede pedir más. Este es un **contrato de backpressure**: la velocidad de producción está siempre acotada por la demanda del consumidor.

Imaginemos un tubo: el consumidor abre la llave (`request(100)`) y recibe 100 gotas. Mientras las procesa, el grifo no suelta más. Cuando termina, vuelve a abrir. Así, ningún extremo se desborda.

### Backpressure en esencia

Backpressure no es simplemente "evitar overflow". Es un protocolo de cooperación entre productor y consumidor para que ambos operen dentro de sus límites. Sin backpressure, si el productor es más rápido:
- En un sistema síncrono, el consumidor bloquea (no hay overflow de datos pero sí de hilos).
- En un sistema asíncrono sin backpressure, los datos se acumulan en un buffer ilimitado (OOM) o se descartan sin control.

Las estrategias imperativas para manejar esta diferencia de velocidad son toscas: hacer buffering con límite, dropear mensajes, throttle... Reactor ofrece medios declarativos para aplicar estas estrategias, pero la base siempre es el `request(n)`.

### Los tres pilares de Reactor: Mono, Flux y Schedulers

- **Mono**: representa una fuente que emite *como mucho* un elemento. Es similar a `CompletableFuture` pero reactivo: soporta backpressure (aunque solo pueda emitir 0 o 1) y se integra con los operadores de Reactor.
- **Flux**: emite de 0 a N elementos, y cada elemento individualmente puede ser solicitado mediante backpressure.
- **Schedulers**: son los contextos de ejecución. Reactor no ejecuta por defecto en un bucle de eventos como Node.js, sino que delega la ejecución a `Schedulers`. Los principales:
  - `Schedulers.parallel()`: para tareas CPU-bound, usa un pool fijo de hilos.
  - `Schedulers.boundedElastic()`: para tareas de E/S, con un pool que puede crecer pero acotado.
  - `Schedulers.single()`: un solo hilo para tareas secuenciales.
  - `Schedulers.fromExecutor(executor)`: adapta un `Executor` existente.

El event loop de Reactor no es un bucle de eventos único, sino que cada Scheduler puede implementar su propio mecanismo. Por ejemplo, `parallel()` usa `ForkJoinPool`. Pero el principio es el mismo: no hay hilos bloqueados esperando resultados; las tareas se ejecutan en hilos prestados y se devuelven al pool cuando terminan.

## En profundidad: internals, trade-offs y comparativas

### Cómo funciona el operador `flatMap` con concurrencia controlada

`flatMap` es uno de los operadores más potentes y peligrosos. Se aplica a cada elemento del flujo fuente y devuelve un `Publisher`, luego fusiona todas esas publicaciones en un único flujo de salida. El orden de los resultados no se preserva: los elementos se entregan a medida que sus respectivos publicadores internos emiten.

Su firma: `Flux<R> flatMap(Function<T, Publisher<R>> mapper, int concurrency, int prefetch)`. El parámetro `concurrency` limita cuántos publicadores internos pueden estar suscritos simultáneamente. Internamente, `flatMap` mantiene una cola de peticiones: cuando un publicador interno pide datos, el operador pide más al flujo fuente respetando la demanda agregada. La backpressure se propaga: si los publicadores internos no piden, el fuente tampoco produce.

Trade-offs: `flatMap` no garantiza orden (para orden usar `concatMap` que suscribe secuencialmente). Además, cada elemento fuente crea una suscripción interna, lo que tiene coste de asignación y contexto. Para flujos muy grandes, `concurrency` debe ajustarse para no saturar de hilos.

### El assembly-time vs subscription-time

En Reactor, construir un pipeline no ejecuta nada. Llamar a `Flux.just(1).map(x -> x+1).filter(x -> x>2)` ensambla una cadena de objetos `FluxOperator` (assembly). La ejecución comienza solo cuando se llama a `subscribe()` (subscription-time). Entonces, la cadena se activa hacia atrás: `subscribe` notifica al último operador, que se suscribe al anterior, y así hasta la fuente. Cada operador puede tener su propio estado y demanda.

Implicación: la traza de pila durante la ejecución no refleja la cadena de operadores, porque la suscripción es un camino de ida y vuelta. Esto dificulta la depuración; se recomienda usar `log()` o `checkpoint()` para identificar dónde falla.

### Cold vs Hot publishers

- **Cold Publisher**: cada suscripción ejecuta la fuente desde cero. `Flux.just`, `Flux.range`, o `Flux.generate` son cold. Si dos suscriptores se conectan, cada uno recibe todos los datos independientemente.
- **Hot Publisher**: la fuente es compartida; los suscriptores reciben solo los elementos emitidos después de su suscripción. Ejemplos: `Sinks.many().multicast()`, `Flux.interval`, o convertir un cold a hot con `.publish().refCount()`.

El uso de hot es esencial para eventos en tiempo real (mensajería, ticks de mercado). `ConnectableFlux` permite controlar cuándo se conecta la fuente. `refCount(n)` conecta automáticamente cuando hay al menos `n` suscriptores.

Cuidado: con hot publishers, si un suscriptor es lento, el productor no se frena automáticamente porque la fuente no sabe a quién esperar. Se necesita una estrategia de backpressure específica (por ejemplo, `Sinks.many().multicast().onBackpressureBuffer()`).

### Backpressure a bajo nivel: `BaseSubscriber` y `Subscription.request`

Podemos implementar un suscriptor manual para controlar exactamente la demanda:

```java
import reactor.core.publisher.Flux;
import reactor.core.publisher.BaseSubscriber;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

public class ManualBackpressure {
    private static final Logger log = LoggerFactory.getLogger(ManualBackpressure.class);

    public static void main(String[] args) throws InterruptedException {
        Flux<Long> source = Flux.interval(java.time.Duration.ofMillis(100)).take(20);

        source.subscribe(new BaseSubscriber<Long>() {
            @Override
            protected void hookOnSubscribe(Subscription subscription) {
                // Pedimos 5 elementos al inicio
                request(5);
            }

            @Override
            protected void hookOnNext(Long value) {
                log.info("Procesando: {}", value);
                // Simulamos procesamiento lento
                try { Thread.sleep(200); } catch (InterruptedException e) {}
                // Procesado uno, pedimos otro
                request(1);
            }

            @Override
            protected void hookOnError(Throwable throwable) {
                log.error("Error", throwable);
            }

            @Override
            protected void hookOnComplete() {
                log.info("Completado");
            }
        });

        Thread.sleep(5000);
    }
}
```

Si no se llama a `request()`, el suscriptor nunca recibe datos (starvation). `subscribe()` con lambdas llama internamente a `request(Long.MAX_VALUE)`, que pide todo de golpe (bueno para flujos pequeños). Para flujos grandes o lentos, es mejor controlar la demanda.

Reactor ofrece estrategias de backpressure declarativas: `onBackpressureBuffer(int capacity)`, `onBackpressureDrop`, `onBackpressureLatest`. `buffer` almacena hasta `capacity` elementos; si se excede, lanza `OverflowException`. `drop` descarta los elementos que no caben; `latest` mantiene solo el último.

### Comparativa breve con RxJava y Kotlin Flow

- **RxJava** (versión 3) tiene una API similar (Observable, Flowable, Single, Maybe). Flowable implementa backpressure; Observable no (ignora). RxJava es más grande y tiene más operadores, pero Reactor está mejor integrado con Spring y tiene abstracciones como `FluxExpand` para flujos infinitos.
- **Kotlin Flow** está diseñado para corrutinas. Ofrece backpressure mediante `conflate`, `buffer`, `collect`. Es más idiomático en Kotlin, pero no es compatible directamente con Reactive Streams (necesita adaptadores). Reactor y RxJava sí lo son.

La ventaja principal de Reactor sobre RxJava es el soporte oficial de Spring Framework: `WebFlux`, `ReactiveMongoRepository`, `ReactiveCassandraRepository`, etc. Además, el operador `FluxExpand` (expansión recursiva) es muy útil para árboles o grafos.

## Ejemplos de código completos y ejecutables

### Ejemplo 1: De bloqueante a reactivo con backpressure

Versión imperativa (ya vista). Ahora reactiva:

```java
// File: ReactiveFileReader.java
import reactor.core.publisher.Flux;
import reactor.core.publisher.BaseSubscriber;
import reactor.core.scheduler.Schedulers;
import java.io.*;
import java.nio.file.*;
import java.time.Duration;

public class ReactiveFileReader {
    public static void main(String[] args) throws InterruptedException {
        Path path = Path.of("datos.txt");
        // Creamos un Flux que lee líneas bajo demanda
        Flux<String> lineFlux = Flux.using(
            () -> Files.newBufferedReader(path),
            reader -> Flux.generate(sink -> {
                try {
                    String line = reader.readLine();
                    if (line != null) {
                        sink.next(line);
                    } else {
                        sink.complete();
                    }
                } catch (IOException e) {
                    sink.error(e);
                }
            }),
            reader -> {
                try { reader.close(); } catch (IOException e) {}
            }
        ).subscribeOn(Schedulers.boundedElastic()); // E/S en hilo elástico

        // Suscriptor con demanda controlada: solo 3 líneas cada vez
        lineFlux.subscribe(new BaseSubscriber<String>() {
            @Override
            protected void hookOnSubscribe(Subscription subscription) {
                request(3); // primera tanda
            }

            @Override
            protected void hookOnNext(String line) {
                System.out.println("Línea: " + line);
                // Simulamos procesamiento lento
                try { Thread.sleep(100); } catch (InterruptedException e) {}
                // Pedimos una más cuando terminamos una
                request(1);
            }

            @Override
            protected void hookOnError(Throwable t) {
                System.err.println("Error: " + t.getMessage());
            }

            @Override
            protected void hookOnComplete() {
                System.out.println("Archivo leído completamente");
            }
        });

        // Esperar a que termine
        Thread.sleep(5000);
    }
}
```

**Comentario**: `Flux.using` garantiza que el `BufferedReader` se cierre al completar o fallar. `subscribeOn` mueve la lectura a un hilo de `boundedElastic` para no bloquear el hilo principal. La demanda inicial de 3 hace que solo se lean 3 líneas en memoria a la vez; al procesar una, pedimos otra. Así, el archivo nunca se carga entero.

Dependencia Maven:

```xml
<dependency>
    <groupId>io.projectreactor</groupId>
    <artifactId>reactor-core</artifactId>
    <version>3.6.5</version>
</dependency>
```

Gradle:

```groovy
implementation 'io.projectreactor:reactor-core:3.6.5'
```

### Ejemplo 2: Procesamiento paralelo controlado

```java
// File: ParallelProcessing.java
import reactor.core.publisher.Flux;
import reactor.core.scheduler.Schedulers;
import java.time.Duration;

public class ParallelProcessing {
    public static void main(String[] args) throws InterruptedException {
        Flux.range(1, 20)
            .flatMap(i -> heavyComputation(i), 5) // solo 5 en paralelo
            .subscribeOn(Schedulers.parallel())
            .doOnNext(result -> System.out.println("Resultado: " + result))
            .blockLast(); // espera a que termine (solo para demo)

        System.out.println("Terminado");
    }

    private static String heavyComputation(int input) {
        try { Thread.sleep(1000); } catch (InterruptedException e) {}
        return "Procesado-" + input;
    }
}
```

**Efecto**: con `concurrency=5`, solo se ejecutan 5 tareas simultáneas. Si usáramos `concatMap` (sin concurrencia), tardaría 20 segundos; con `flatMap` y 5 hilos, ~4 segundos. El parámetro `concurrency` es fundamental para controlar la carga.

**Atención**: `flatMap` no preserva orden. Si el orden importa, usar `concatMap` (suscribe secuencialmente). Para concurrencia con orden parcial, considerar `flatMapSequential`.

### Ejemplo 3: Error handling reactivo

```java
// File: ErrorHandling.java
import reactor.core.publisher.Flux;

public class ErrorHandling {
    public static void main(String[] args) {
        Flux.range(1, 10)
            .map(i -> {
                if (i == 5) throw new RuntimeException("Error en el 5");
                return i * 10;
            })
            .onErrorResume(e -> {
                System.err.println("Recuperado: " + e.getMessage());
                return Flux.just(-1); // valor de reemplazo
            })
            .subscribe(System.out::println);

        // Con onErrorContinue: salta el error y continúa con los siguientes
        Flux.range(1, 10)
            .map(i -> {
                if (i == 5) throw new RuntimeException("Error en el 5");
                return i * 10;
            })
            .onErrorContinue((e, i) -> {
                System.err.println("Error en elemento " + i + ": " + e.getMessage());
            })
            .subscribe(System.out::println);
    }
}
```

**Trampa**: `onErrorContinue` solo funciona con operadores que propagan el contexto (como `map`, `filter`). No funciona con `flatMap` a menos que se use una combinación específica. Siempre comprobar la documentación.

### Ejemplo 4: Hot publisher con Sinks

```java
// File: HotPublisherDemo.java
import reactor.core.publisher.Flux;
import reactor.core.publisher.Sinks;
import java.time.Duration;

public class HotPublisherDemo {
    public static void main(String[] args) throws InterruptedException {
        // Crear un sink multicast con backpressure buffer
        Sinks.Many<Integer> sink = Sinks.many().multicast().onBackpressureBuffer(10);

        // Convertir a Flux (hot)
        Flux<Integer> hotFlux = sink.asFlux();

        // Suscriptor rápido
        hotFlux.subscribe(i -> System.out.println("Rápido recibe: " + i));

        // Suscriptor lento
        hotFlux.subscribe(i -> {
            try { Thread.sleep(500); } catch (InterruptedException e) {}
            System.out.println("Lento recibe: " + i);
        });

        // Emitir elementos desde otro hilo
        new Thread(() -> {
            for (int i = 0; i < 20; i++) {
                sink.tryEmitNext(i);
                try { Thread.sleep(100); } catch (InterruptedException e) {}
            }
            sink.tryEmitComplete();
        }).start();

        Thread.sleep(5000);
    }
}
```

**Comportamiento**: el suscriptor lento recibirá backpressure: si el buffer de 10 se llena, `tryEmitNext` devolverá `EmitResult.FAIL_OVERFLOW`. Podemos manejarlo con un callback. El rápido no se ve afectado. Esto demuestra que la backpressure es individual por suscriptor en hot publishers.

## Trampas comunes y cómo evitarlas

### Olvidar `request()` en el subscriber

Si usas `subscribe` con `Consumer` lambda, Reactor llama internamente a `request(Long.MAX_VALUE)`, así que no hay problema. Pero si implementas `BaseSubscriber` y no llamas a `request()` en `hookOnSubscribe`, nunca recibirás datos. Siempre llama a `request(n)` con un número adecuado.

### Bloquear dentro de un pipeline reactivo

Llamar a `Thread.sleep()`, `Future.get()`, o `block()` dentro de un operador (por ejemplo, dentro de un `map`) bloquea el hilo del Scheduler actual. Si es el hilo del event loop (parallel), detiene todo el flujo. Solución: usar `subscribeOn` para mover la operación bloqueante a un Scheduler elástico, o usar `block()` solo al final de la cadena (fuera del pipeline). Incluso mejor: no bloquear nunca; usar operadores reactivos para esperar (por ejemplo, `Mono.delay`).

### No suscribirse (cold nunca se ejecuta)

Un `Flux` o `Mono` construido no hace nada hasta que alguien llama a `subscribe()`. Es un error común al depurar con `log()`: esperar ver trazas sin suscripción. Asegúrate de que todo flujo que quieras ejecutar tenga un suscriptor.

### Usar `Mono` para operaciones que pueden dar cero o múltiples resultados

`Mono` puede emitir un elemento o vacío (`Mono.empty()`). Si esperas varias emisiones, usa `Flux`. Si usas `Mono.just(..)` para un valor que en realidad es una lista, estás emitiendo la lista completa como un solo elemento. Aplica entonces `flatMapMany` para aplanar.

### Mezclar código imperativo y reactivo sin barreras

Llamar a `block()` dentro de un pipeline reactivo puede provocar deadlock si no hay hilo disponible (por ejemplo, en un solo hilo de event loop). La buena práctica es mantener el código reactivo puro hasta el borde de la aplicación (controlador web, servicio de mensajería). Si necesitas obtener un valor bloqueante, hazlo al inicio o al final, no en medio.

### Ignorar el error de contrapresión cuando el consumidor es muy lento

Si usas `Sinks.many().multicast()` sin `onBackpressureBuffer`, el comportamiento por defecto es fallar con `OverflowException` cuando se excede la capacidad. Siempre especifica una estrategia: `buffer(int)`, `drop()`, `latest()`. En `Flux` puedes usar `onBackpressureBuffer` en el propio flujo antes de suscribir.

## Para saber más: referencias concretas

1. **Documentación oficial de Project Reactor** – [Reactor Core Reference Guide](https://projectreactor.io/docs/core/release/reference/) (capítulos 1, 3, 5, 8).  
2. **Reactive Streams Specification** – [reactive-streams.org](https://www.reactive-streams.org/), especialmente el documento de especificación.  
3. **“Designing Data-Intensive Applications”** – Martin Kleppmann (capítulo 8 sobre flujos y contrapresión).  
4. **Artículo técnico de Simon Baslé** – “Understanding reactor internals: assembly vs subscription” (blog de Project Reactor).  
5. **Charla de Rossen Stoyanchev** – “Reactive Programming with Spring” (SpringOne 2020) – en especial la explicación de backpressure en HTTP/2.
