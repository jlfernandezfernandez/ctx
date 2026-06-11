---
title: "Project Reactor: el paradigma reactivo en Java"
description: "Project Reactor es una librería para construir aplicaciones asíncronas y no bloqueantes en la JVM, implementando la especificación Reactive Streams. Resuelve el cuello de botella del modelo hilo-por-petición al usar un número reducido de hilos para manejar alta concurrencia I/O, gracias a flujos reactivos con backpressure. Usar cuando se requiera bajo consumo de recursos y alta escalabilidad, pero no si la lógica es inherentemente bloqueante o la depuración de pipelines reactivos añade una complejidad injustificada."
pubDate: 2026-06-11
tags: ["java", "reactive", "backpressure", "project-reactor", "non-blocking"]
summary: "Project Reactor es una librería para construir aplicaciones asíncronas y no bloqueantes en la JVM, implementando la especificación Reactive Streams. Resuelve el cuello de botella del modelo hilo-por-petición al usar un número reducido de hilos para manejar alta concurrencia I/O, gracias a flujos reactivos con backpressure. Usar cuando se requiera bajo consumo de recursos y alta escalabilidad, pero no si la lógica es inherentemente bloqueante o la depuración de pipelines reactivos añade una complejidad injustificada."
---

## 1. Contexto: qué problema existe y por qué este tema importa (desde cero)

El modelo imperativo y bloqueante ha sido la columna vertebral del desarrollo backend durante años. La premisa es simple: llega una petición HTTP, el servidor le asigna un hilo del pool, ese hilo ejecuta la lógica de negocio —que puede incluir llamadas a base de datos, a otros servicios o a disco— y devuelve una respuesta. Mientras la lógica espera una operación de I/O, el hilo queda bloqueado, inactivo, consumiendo memoria y recursos del sistema operativo. Si el pool tiene 200 hilos y todos están esperando respuestas de servicios externos, la aplicación deja de aceptar nuevas conexiones, aunque la CPU esté prácticamente ociosa.

Este modelo choca con la realidad de las aplicaciones modernas, intensivas en I/O. Un microservicio típico orquesta llamadas a otros microservicios, consultas a bases de datos, escritura en caches y notificaciones a colas de mensajería. Cada una de esas interacciones implica latencia de red o de disco, y durante esa espera el hilo permanece bloqueado. Aumentar el tamaño del pool solo agrava el problema: más hilos implican mayor consumo de memoria de pila, más cambios de contexto en el scheduler del sistema operativo y, a menudo, contención en recursos compartidos. El resultado es un sistema con baja capacidad de throughput y alta latencia en los percentiles superiores, a pesar de tener CPU infrautilizada.

La raíz del problema está en la naturaleza síncrona de las APIs: cuando un método devuelve un resultado, el hilo que lo invocó debe esperar ese resultado sin poder hacer otra cosa. La asincronía ofrece una alternativa: en lugar de esperar pasivamente, el hilo registra una continuación y vuelve al pool, quedando disponible para atender otras peticiones. Cuando la respuesta de I/O está lista, un callback o una promesa recibe el dato y se reanuda el procesamiento, posiblemente en otro hilo. Esto permite manejar muchas más conexiones concurrentes con muchos menos hilos.

El paradigma reactivo lleva esta idea al extremo, organizándola en torno a flujos de datos asíncronos gobernados por un modelo de empuje (push). En lugar de que el consumidor tire (pull) de los datos llamando a un método y quedándose bloqueado, es el productor quien empuja los datos hacia el consumidor cuando están disponibles. Así nace la especificación Reactive Streams (reactive-streams.org), un estándar mínimo que define la interacción entre un `Publisher` (fuente de datos asíncrona) y un `Subscriber` (consumidor), con un mecanismo de control de flujo no bloqueante llamado *backpressure*. Project Reactor es la implementación de referencia de esta especificación para la JVM y el núcleo reactivo de todo el ecosistema Spring.

## 2. Concepto central: la idea clave explicada con precisión

Project Reactor introduce dos tipos principales: `Mono<T>` y `Flux<T>`. Ambos representan secuencias asíncronas de datos, pero `Mono` emite de 0 a 1 elemento (análogo a un `CompletableFuture<T>` pero con semántica reactiva completa) y `Flux` emite de 0 a N elementos (equivalente a un `Iterable<T>` push-based). A diferencia de `CompletableFuture`, que es eager y comienza a ejecutarse inmediatamente, `Mono` y `Flux` son lazy: no sucede nada hasta que alguien se suscribe.

La lógica de procesamiento se expresa mediante un ensamblaje declarativo de operadores funcionales (`map`, `flatMap`, `filter`, `zip`, etc.). Cada operador envuelve al `Publisher` anterior y crea un nuevo `Publisher`, formando una cadena de transformación. Esta tubería no se ejecuta en el momento de la declaración; solo cuando un `Subscriber` se suscribe al `Publisher` final, se activa todo el flujo hacia arriba, en una cascada de suscripciones que terminan generando los datos desde la fuente.

El concepto más diferenciador del paradigma reactivo es el *backpressure*. En un sistema push-based puro, un productor rápido podría saturar a un consumidor lento enviándole más datos de los que puede procesar. La especificación Reactive Streams resuelve esto mediante señalización `request(n)`. El `Subscriber`, al suscribirse, solicita una cantidad inicial de elementos con `request(n)`. Luego, tras procesar cada elemento, puede solicitar más con otra llamada a `request(1)`, o `request(m)`. El `Publisher` está obligado a no emitir más elementos de los solicitados. Así, el consumidor controla el ritmo sin necesidad de bloquearse, simplemente retrasando las solicitudes. Todo el mecanismo es no bloqueante y en pila de llamadas.

Veamos un contraste práctico: leer un archivo remoto línea por línea y contar las líneas. Versión imperativa bloqueante con `BufferedReader`:

```java
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.URL;

public class ImperativeLineCounter {
    public static void main(String[] args) throws Exception {
        URL url = new URL("https://example.com/large-file.txt");
        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(url.openStream()))) {
            int count = 0;
            String line;
            while ((line = reader.readLine()) != null) {
                count++;
            }
            System.out.println("Total lines: " + count);
        }
    }
}
```

Este código bloquea al hilo en cada operación de red y en cada `readLine()`. Para aumentar el throughput, necesitaríamos más hilos.

La versión reactiva con `Flux.usingWhen` y un `BaseSubscriber` con control manual de backpressure:

```java
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;
import reactor.core.scheduler.Schedulers;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.URL;

public class ReactiveLineCounter {
    public static void main(String[] args) {
        Flux.<String, BufferedReader>usingWhen(
            Mono.fromCallable(() -> new BufferedReader(
                new InputStreamReader(
                    new URL("https://example.com/large-file.txt").openStream()))),
            reader -> Flux.create(sink -> {
                String line;
                try {
                    while ((line = reader.readLine()) != null) {
                        sink.next(line);
                    }
                    sink.complete();
                } catch (Exception e) {
                    sink.error(e);
                }
            }),
            reader -> Mono.fromRunnable(() -> {
                try { reader.close(); } catch (Exception ignored) {}
            })
        )
        .subscribeOn(Schedulers.boundedElastic())
        .subscribe(new reactor.core.publisher.BaseSubscriber<String>() {
            int count = 0;
            @Override
            protected void hookOnSubscribe(Subscription subscription) {
                // Solicitar solo una línea inicial
                request(1);
            }
            @Override
            protected void hookOnNext(String value) {
                count++;
                // Procesar la línea y luego pedir la siguiente
                request(1);
            }
            @Override
            protected void hookOnComplete() {
                System.out.println("Total lines: " + count);
            }
        });
        // Mantener el proceso vivo un momento (en una app real no haría falta)
        try { Thread.sleep(5000); } catch (InterruptedException e) {}
    }
}
```

Aquí el `Subscriber` controla cuántas líneas recibe del `Publisher`. Si el consumidor fuera más lento (por ejemplo porque escribe en disco), simplemente retrasaría las llamadas a `request()`, y el productor esperaría, sin ocupar hilos ni buffers intermedios.

## 3. En profundidad: internals, trade-offs, comparativas (lo que una newsletter no cuenta)

### Ensamblaje de operadores y cadena de decoradores

Cada operador en Reactor es un decorador del `Publisher` original. Cuando escribimos `Flux.just(1,2,3).map(x -> x*2).filter(x -> x>2)`, no hay una lista que se transforma. `just` devuelve un `FluxArray`. `map` devuelve un `FluxMapFuseable` (si el origen lo soporta) que envuelve al anterior. `filter` devuelve un `FluxFilterFuseable` que envuelve al `map`. Al suscribirnos, `filter` se suscribe a `map`, que se suscribe a `just`, y los datos fluyen hacia abajo respetando los límites de `request()`. Internamente, Reactor usa una infraestructura de `Operators` con macros de optimización que evitan la creación excesiva de objetos intermedios mediante fusión de operadores (macro-fusion y micro-fusion), lo que permite que secuencias de operadores map/filter iterativas se ejecuten casi al coste de un bucle for.

### Scheduler y el bucle reactor

El cambio de hilos en Reactor se maneja mediante `Scheduler` y workers. Existen varios por defecto:

- `Schedulers.parallel()`: pool fijo de hilos de CPU, óptimo para tareas intensivas en cómputo. No debe usarse para I/O bloqueante.
- `Schedulers.boundedElastic()`: pool elástico de hilos con límite superior, pensado para tareas bloqueantes legacy (adaptadores JDBC, llamadas a APIs síncronas). Cada tarea obtiene su propio hilo, pero el pool puede crecer hasta un tope y luego encolar.
- `Schedulers.single()`: un solo hilo dedicado para tareas que requieren ejecución secuencial sin contención.

En aplicaciones web con Spring WebFlux, el runtime subyacente suele ser Netty, que implementa un event loop basado en NIO. Los workers de Netty se encargan de manejar las conexiones y despachar eventos sin bloquearse. Reactor se integra con esos event loops, permitiendo que la mayor parte del procesamiento ocurra en esos hilos no bloqueantes, eliminando la necesidad de pools de hilos enormes.

### Backpressure avanzado y estrategias de sobrepresión

Cuando un productor emite más rápido de lo que el consumidor solicita, si no hay un buffer intermedio configurado, Reactor lanza un `OverflowException`. Sin embargo, hay múltiples estrategias para manejarlo sin perder el control:

- `onBackpressureBuffer(maxSize)`: almacena los elementos excedentes en un buffer hasta que el consumidor los pida. Si el buffer se llena, se puede lanzar error o aplicar otra estrategia.
- `onBackpressureDrop()`: descarta los elementos que el consumidor no puede procesar.
- `onBackpressureLatest()`: mantiene solo el último elemento emitido, descartando los anteriores.
- `onBackpressureError()`: lanza error inmediatamente al exceder la demanda.
- `limitRate(prefetch)`: establece la cantidad de elementos que el operador intermedio solicitará hacia arriba cuando tenga demanda desde abajo, permitiendo afinar el tamaño de lote.

Es crucial entender que muchos operadores como `flatMap` tienen un parámetro de concurrencia (`flatMap(mapper, concurrency, prefetch)`) que controla cuántas suscripciones internas concurrentes se permiten y cuál es el prefetch hacia el `Publisher` externo. Sin ajustarlos, un flujo rápido puede saturar silenciosamente la memoria.

### Reactor vs. CompletableFuture en composiciones complejas

`CompletableFuture` ofrece encadenamiento asíncrono con `thenApply`, `thenCompose`, etc., pero carece de backpressure, no representa múltiples elementos, y el manejo de errores es menos expresivo. Para secuencias de múltiples pasos con reintentos y timeouts, Reactor proporciona:

```java
Mono.just(request)
    .flatMap(this::remoteCall)
    .timeout(Duration.ofSeconds(2))
    .retryWhen(Retry.backoff(3, Duration.ofMillis(100)))
    .onErrorResume(throwable -> Mono.just(fallbackResponse));
```

Con `CompletableFuture` esto requeriría lógica manual de reintento con schedulers externos, perdiendo legibilidad y dificultando la gestión de errores parciales.

### Reactor vs. RxJava

RxJava (versiones 2 y 3) también implementa Reactive Streams, pero con diferencias de diseño:

- Tipos: RxJava usa `Flowable` para backpressure, `Observable` sin backpressure, `Single`, `Maybe`, `Completable`. Reactor unifica el manejo de backpressure en `Flux` y `Mono`, simplificando la elección.
- Reactor está optimizado para entornos en los que el runtime de Netty y Spring se encargan de la mayor parte de la concurrencia, mientras que RxJava está más orientado a aplicaciones standalone con control explícito de schedulers.
- En benchmarks recientes (como los publicados por el equipo de Reactor), las optimizaciones de fusión de operadores y la alineación con el runtime de Netty dan a Reactor una ventaja de rendimiento en entornos web, aunque la diferencia se ha reducido con RxJava 3.

### Trade-off del debugging

La naturaleza lazy y anidada de los operadores hace que los stacktraces por defecto sean crípticos: una excepción muestra una larga cadena de decoradores anónimos con poca información sobre dónde se declaró el ensamblaje. Reactor ofrece `Hooks.onOperatorDebug()`, que activa un modo de debugging en el que cada operador captura la traza de ensamblaje y la adjunta a los eventos. El coste en rendimiento es significativo (puede multiplicar por 5 o 10 el tiempo de ejecución), por lo que no debe usarse en producción. Como alternativa más ligera, se pueden usar checkpoints: `.checkpoint("después-consulta-bd")` añade una etiqueta que aparece en el stacktrace sin el overhead masivo de capturar toda la traza. En producción, las trazas de ensamblaje se pueden obtener con el agente Java de Reactor (`reactor-tools`), que las construye bajo demanda con un costo mucho menor.

## 4. Ejemplos de código ejecutables, comentados, de menos a más complejo

**Ejemplo 1: Creación y suscripción básica**

```java
import reactor.core.publisher.Flux;

public class BasicSubscription {
    public static void main(String[] args) {
        Flux<String> letters = Flux.just("a", "b", "c");
        letters.subscribe(
            value -> System.out.println("Received: " + value),
            error -> System.err.println("Error: " + error),
            () -> System.out.println("Completed")
        );
    }
}
```

**Ejemplo 2: Transformación con map y filter**

```java
import reactor.core.publisher.Flux;

public class MapFilterExample {
    public static void main(String[] args) {
        Flux.just(1, 2, 3, 4, 5)
            .filter(i -> i % 2 == 0)     // solo pares
            .map(i -> i * i)             // elevar al cuadrado
            .subscribe(System.out::println);
    }
}
```

Nótese que la secuencia original no se modifica; cada operador genera un nuevo `Flux` que envuelve al anterior.

**Ejemplo 3: Llamada a API externa con WebClient y manejo de errores**

```java
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

public class WebClientExample {
    public static void main(String[] args) {
        WebClient client = WebClient.create("https://jsonplaceholder.typicode.com");

        client.get()
            .uri("/posts/1")
            .retrieve()
            .bodyToMono(String.class)
            .flatMap(this::processResponse)
            .doOnError(e -> System.err.println("Se produjo un error: " + e.getMessage()))
            .onErrorReturn("Fallback data")
            .subscribe(System.out::println);

        // Mantener el proceso para que la llamada asíncrona se complete
        try { Thread.sleep(3000); } catch (InterruptedException e) {}
    }

    private static Mono<String> processResponse(String body) {
        return Mono.just("Procesado: " + body.toUpperCase());
    }
}
```

`flatMap` permite encadenar operaciones asíncronas que devuelven `Mono`. `doOnError` es un side-effect; `onErrorReturn` recupera con un valor por defecto.

**Ejemplo 4: Backpressure manual con Flux.interval y BaseSubscriber**

```java
import reactor.core.publisher.Flux;
import reactor.core.publisher.BaseSubscriber;
import reactor.core.scheduler.Schedulers;

public class ManualBackpressure {
    public static void main(String[] args) throws InterruptedException {
        Flux<Long> fastProducer = Flux.interval(java.time.Duration.ofMillis(10))
                                      .subscribeOn(Schedulers.parallel())
                                      .publish()
                                      .autoConnect();

        fastProducer
            .doOnRequest(r -> System.out.println("Solicitados: " + r))
            .subscribe(new BaseSubscriber<Long>() {
                @Override
                protected void hookOnSubscribe(Subscription subscription) {
                    request(5); // solicitar lote inicial de 5
                }
                @Override
                protected void hookOnNext(Long value) {
                    System.out.println("Procesando: " + value);
                    // simular procesamiento lento
                    try { Thread.sleep(200); } catch (InterruptedException e) {}
                    request(1); // pedir siguiente elemento solo cuando esté listo
                }
            });

        Thread.sleep(3000); // dejar correr un rato
    }
}
```

El productor emite cada 10 ms, pero el consumidor tarda 200 ms en procesar cada elemento. Gracias a la señalización `request`, el productor no satura al consumidor.

**Ejemplo 5: Timeout, retry con backoff y fallback**

```java
import reactor.core.publisher.Mono;
import reactor.util.retry.Retry;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicInteger;

public class ResilientService {
    private static final AtomicInteger attempts = new AtomicInteger(0);

    public static void main(String[] args) {
        Mono<String> remoteCall = Mono.<String>fromCallable(() -> {
            int call = attempts.incrementAndGet();
            System.out.println("Intento: " + call);
            if (call < 3) throw new RuntimeException("Servicio no disponible");
            return "Response body";
        }).delayElement(Duration.ofMillis(100)); // simular latencia

        remoteCall
            .timeout(Duration.ofSeconds(1))
            .retryWhen(Retry.backoff(3, Duration.ofMillis(100)))
            .onErrorResume(throwable -> {
                System.out.println("Fallback tras reintentos: " + throwable.getMessage());
                return Mono.just("Fallback response");
            })
            .subscribe(result -> System.out.println("Resultado final: " + result));

        try { Thread.sleep(2000); } catch (InterruptedException e) {}
    }
}
```

`Mono.fromCallable` difiere la ejecución hasta la suscripción. `Retry.backoff` espera 100 ms entre el primer y segundo intento, 200 ms entre el segundo y el tercero, etc. Si agotados los reintentos aún falla, `onErrorResume` proporciona un fallback.

## 5. Trampas comunes: errores reales que comete la gente y cómo evitarlos

**Bloquear dentro de operadores reactivos**

El error más frecuente es ejecutar código bloqueante dentro de un pipeline reactivo. Por ejemplo, meter un `Thread.sleep` o una llamada JDBC síncrona dentro de un `map`:

```java
flux.map(item -> {
    String data = someBlockingRestCall(item); // ¡Bloquea el event loop!
    return data.toUpperCase();
});
```

Esto ocupa un hilo no bloqueante (del event loop de Netty o del scheduler parallel) con una espera, destruyendo la escalabilidad. La solución es delegar las llamadas bloqueantes a un scheduler específico con `subscribeOn(Schedulers.boundedElastic())`, o mejor, usar APIs reactivas (R2DBC, WebClient). La herramienta BlockHound es un agente de Java que detecta automáticamente operaciones bloqueantes en hilos no bloqueantes y lanza error, permitiendo identificar estos problemas en desarrollo y testing.

**Ignorar el backpressure**

Otro error común es asumir que Reactor maneja automáticamente cualquier desequilibrio de velocidad. Si un `Flux` se genera a partir de un productor que no respeta la demanda —por ejemplo, un `Flux.create` que llama a `sink.next()` sin verificar `sink.requestedFromDownstream()`—, se producirá un `OverflowException` silencioso o un crecimiento descontrolado de la memoria interna. Siempre hay que configurar una estrategia de backpressure con `onBackpressureBuffer`, `onBackpressureDrop`, etc., o asegurarse de que el productor implementa correctamente la interfaz reactiva.

**Confundir la pereza con inactividad**

Como `Mono` y `Flux` no ejecutan nada hasta que hay un `subscribe()`, es frecuente ver pipelines declarados que nunca se suscriben y que el desarrollador cree que están en ejecución. En una aplicación web Spring WebFlux, el framework se encarga de suscribirse a la respuesta; pero en una clase standalone o en tests, si olvidamos `.subscribe()` o `.block()`, la cadena nunca se activa y el programa termina sin hacer nada. La pereza también significa que efectos secundarios dentro de `map` o `flatMap` se ejecutarán cada vez que haya una suscripción nueva; si un `Mono` se reutiliza en varias suscripciones, esas operaciones se repetirán. Para efectos secundarios que deben ocurrir una sola vez, usar `.cache()` o `.share()`.

**Stacktraces ilegibles en producción**

Activar `Hooks.onOperatorDebug()` en producción es una receta para el desastre: cada ensamblaje captura un stacktrace completo, lo que multiplica el consumo de memoria y CPU. En su lugar, en producción se deben usar checkpoints con identificadores significativos en puntos clave de la cadena, y en desarrollo se puede activar `onOperatorDebug()` para una depuración puntual. El agente `reactor-tools` es una solución intermedia viable para producción que construye la traza de ensamblaje bajo demanda y con menos overhead.

**Fugas de recursos**

Cuando se trabaja con recursos que deben liberarse (ficheros, conexiones, sockets), el operador `using` puede no ser suficiente porque no asegura la liberación en caso de cancelación. `Flux.usingWhen` (y `Mono.usingWhen`) garantiza que el recurso se limpia tanto en caso de finalización normal como en error o cancelación, siguiendo un contrato de `cleanup` asíncrono. No hacerlo puede dejar conexiones abiertas que agoten el pool de la base de datos. Un ejemplo incorrecto sería un `Flux.create` que abre un `InputStream` y nunca lo cierra si el suscriptor cancela.

## 6. Para saber más

1. **Documentación oficial de Project Reactor – "Reactor Core Features"**. La referencia más completa y actualizada, con guías sobre todos los operadores, schedulers y testing. [https://projectreactor.io/docs/core/release/reference/](https://projectreactor.io/docs/core/release/reference/)

2. **Reactive Streams Specification**. El documento breve pero esencial que define el protocolo de backpressure y la interacción entre `Publisher` y `Subscriber`. Imprescindible para entender los contratos que Reactor implementa. [https://www.reactive-streams.org/](https://www.reactive-streams.org/)

3. **"Reactive Spring" – Josh Long**. Libro y serie de artículos en el blog oficial de Spring que explican la integración de Reactor con Spring Boot y Spring Cloud, con numerosos ejemplos prácticos. [https://spring.io/blog](https://spring.io/blog) (buscar "Reactive Spring").

4. **"Understanding Project Reactor's .then() and .flatMap() operators" – Baeldung**. Artículo que profundiza en operadores que generan confusión entre asincronía y secuencialidad, con ejemplos claros. [https://www.baeldung.com/project-reactor-then-flatmap](https://www.baeldung.com/project-reactor-then-flatmap)

5. **"Reactor Internals" – Simon Baslé (YouTube)**. Charla impartida por uno de los desarrolladores principales del proyecto, donde explica el ensamblaje de operadores, la fusión de macros y las optimizaciones internas. Disponible en el canal de SpringDeveloper.
