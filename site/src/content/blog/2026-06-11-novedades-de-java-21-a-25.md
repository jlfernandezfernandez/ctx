---
title: "Novedades de Java 21 a 25: virtual threads y pattern matching"
description: "Los hilos virtuales permiten volver al modelo thread‑per‑request con bloqueos escalables, pero se anclan (pin) en bloques synchronized y no mejoran tareas CPU‑bound. El pattern matching en switch proporciona desestructuración exhaustiva de records y tipos sellados, eliminando casts y ramas olvidadas. La concurrencia estructurada y scoped values simplifican la cancelación segura y el contexto heredable en entornos con millones de hilos ligeros."
date: 2026-06-11
tags: ["java", "virtual-threads"]
summary: "Los hilos virtuales permiten volver al modelo thread‑per‑request con bloqueos escalables, pero se anclan (pin) en bloques synchronized y no mejoran tareas CPU‑bound. El pattern matching en switch proporciona desestructuración exhaustiva de records y tipos sellados, eliminando casts y ramas olvidadas. La concurrencia estructurada y scoped values simplifican la cancelación segura y el contexto heredable en entornos con millones de hilos ligeros."
issue: 2
requestedBy: "jlfernandezfernandez"
writer: "deepseek-v4-pro"
reviewer: "minimax-m3"
---

## Contexto: Los límites del modelo tradicional y la necesidad de evolución

Durante años, el modelo de concurrencia en Java se basó en hilos del sistema operativo (platform threads). Cada petición entrante en un servidor se vinculaba a un hilo dedicado, lo que ofrecía un estilo de programación secuencial fácil de razonar. Sin embargo, estos hilos son recursos costosos: consumen alrededor de 1 MB de stack por defecto y requieren gestión del kernel. En aplicaciones cloud‑native que deben manejar decenas o cientos de miles de conexiones simultáneas, el modelo thread‑per‑request golpea los límites de escalabilidad. Dedicar un hilo a cada petición bloqueante (por ejemplo, esperando una respuesta de base de datos) agota la memoria y satura el planificador del sistema operativo, forzando a los equipos a migrar hacia frameworks reactivos y programación asíncrona con `CompletableFuture` o callbacks.

Esa transición no es trivial: el código se fragmenta en cadenas de promesas, la propagación de errores se vuelve compleja y el depurador pierde contexto. La experiencia diaria del desarrollador se resiente. De forma paralela, el manejo de datos con las herramientas clásicas –`instanceof` seguido de cast, cadenas `if‑else` y `switch` limitado a tipos primitivos y String– resulta verboso y propenso a errores. Sin un mecanismo estándar para desestructurar objetos de forma segura, cada comprobación de tipo requiere un cast manual y no hay forma de que el compilador verifique que se han cubierto todos los casos.

Java 21, la versión LTS publicada en 2023, marca un antes y un después. Introduce los virtual threads, una implementación ligera de hilos gestionada por la JVM que permite mantener el estilo secuencial sin las penalizaciones de escalabilidad de los hilos de plataforma. Junto a ellos, el pattern matching alcanza su madurez en `switch`, combinando patrones de tipo y de registro para escribir flujos declarativos y exhaustivos. Las versiones 22, 23 y 24 consolidan estas capacidades con mejoras incrementales, y Java 25, próximo LTS, las dejará listas para su adopción generalizada. A esto se suman la concurrencia estructurada, scoped values y sequenced collections: piezas que refuerzan la expresividad, la seguridad y el rendimiento del código cotidiano.

Estas novedades eliminan la fricción histórica entre simplicidad y rendimiento: ya no es necesario elegir entre código secuencial fácil de leer y un sistema que escale. La JVM proporciona ahora bloques de construcción que permiten expresar la lógica de negocio directamente, confiando en el runtime para gestionar la concurrencia masiva. En las siguientes secciones exploramos cómo funcionan, qué trade‑offs implican y cómo aplicarlos correctamente en situaciones reales.

## Threads virtuales y pattern matching: claves para una concurrencia sencilla y datos a prueba de errores

Los virtual threads son el pilar de una nueva estrategia de concurrencia. A diferencia de los hilos de plataforma, que tienen una relación 1:1 con los hilos del sistema operativo, un virtual thread es una abstracción ligera programada por la JVM sobre un número reducido de carrier threads (hilos de plataforma reales). Su creación cuesta apenas unos cientos de bytes y pueden existir millones de instancias simultáneas. El programador escribe código bloqueante –por ejemplo, `Thread.sleep()` o una llamada HTTP síncrona– y cuando el hilo virtual se bloquea en una operación de I/O, la JVM lo desmonta del carrier thread y lo aparca en memoria, liberando el portador para ejecutar otros virtual threads. Cuando la operación termina, el hilo se reanuda en cualquier portador disponible. Este mecanismo recuerda a las corrutinas o a los hilos verdes, pero está totalmente integrado en el lenguaje y no requiere palabras clave especiales.

El resultado práctico es que podemos volver al modelo thread‑per‑request: cada petición lanza un virtual thread que ejecuta su lógica secuencialmente, realizando llamadas bloqueantes sin penalizar la escalabilidad. Frameworks como Helidon Níma o el soporte nativo de Spring Boot 3.2 adoptan este enfoque, simplificando drásticamente el código en comparación con las alternativas reactivas. El impacto en el día a día es inmediato: desaparecen las cadenas de `thenApply`, el debugger muestra trazas lineales y las métricas de latencia no ocultan sobrecargas de planificación.

No obstante, los virtual threads no mejoran por sí solos el rendimiento de tareas intensivas en CPU. Su fortaleza está en las operaciones bloqueantes. Para tareas CPU‑bound, conviene limitar el paralelismo con semáforos o colas limitadas, evitando saturar el pool común de ForkJoin.

El pattern matching en `switch` es la otra gran revolución. Desde Java 16, `instanceof` permite declarar una variable de patrón, ahorrando el cast. Java 21 lleva este concepto al `switch`, permitiendo patrones de tipo y, crucialmente, patrones de registro. Con una jerarquía sellada (sealed hierarchy), podemos escribir un `switch` sobre una variable de la interfaz base y el compilador verifica que todas las especializaciones estén cubiertas. Además, los patrones de registro desestructuran un record en sus componentes, evitando el acceso manual a campos. Por ejemplo, un `case Rectangle(var ancho, var alto) -> ...` extrae directamente los valores. Java 21 introdujo como preview los patrones sin nombre con `_`, que permiten ignorar componentes que no interesan (finalizados en Java 22). Java 23 refina la interoperabilidad con tipos primitivos. Todo esto transforma el código de manipulación de datos en un flujo declarativo, seguro y libre de boilerplate, donde el compilador asume la responsabilidad de la exhaustividad.

Estas dos innovaciones, aunque distintas, convergen en un mismo objetivo: eliminar la fricción accidental. La concurrencia sencilla y la desestructuración de datos se convierten en recursos naturales del lenguaje, sin tener que recurrir a frameworks externos o patrones de diseño oscuros.

## Bajo el capó: internals de virtual threads, evolución del pattern matching y APIs complementarias

Para usar los virtual threads con confianza es necesario entender sus tripas. Cada virtual thread se implementa mediante una continuación (`Continuation`) que se monta sobre un carrier thread real. El scheduler por defecto es un `ForkJoinPool` en modo FIFO, que permite una alta tasa de cambios de contexto ligeros. Cuando un virtual thread llama a un método bloqueante nativo (por ejemplo, `Socket.read()`), el runtime sustituye la llamada mediante la infraestructura de `java.nio.channels`; si detecta que el hilo va a bloquearse, suspende la continuación y la almacena en un montón de hilos pendientes, liberando el carrier. Cuando los datos están disponibles, el hilo se vuelve elegible y se reanuda en algún carrier disponible. Todo este proceso es transparente y no requiere cambios en el código del usuario.

Sin embargo, existe un escollo conocido como *pinning*. Si un virtual thread ejecuta un bloque `synchronized` o llama a una función nativa JNI, no puede ser desmontado y ocupa su carrier thread hasta que sale de esa sección crítica. Durante ese tiempo, el carrier queda anclado, reduciendo la capacidad de ejecutar otros virtual threads. Si muchas peticiones caen en secciones sincronizadas, la escalabilidad se degrada significativamente. La monitorización se puede realizar con comandos `jcmd` y con el nuevo sistema de logs de incidencias de pinning introducido en Java 22. La solución pasa por reemplazar `synchronized` con `ReentrantLock` siempre que sea posible, o aislar las secciones críticas en pools de hilos de plataforma.

En cuanto al pattern matching, su evolución ha sido gradual. Java 16 introdujo los type patterns en `instanceof` con variable vinculada. Java 17 sentó las bases con las jerarquías selladas. Java 21 unificó todo en `switch`: patrones de tipo, patrones de registro y exhaustividad. El compilador no solo asegura la cobertura; también optimiza el código generado, omitiendo casts redundantes y minimizando las ramas condicionales. Java 21 también trajo en preview los patrones sin nombre (`_`), ideales para ignorar partes de un registro, que fueron finalizados en la versión 22. La verificación de exhaustividad se apoya en las sealed hierarchies, por lo que para aprovecharla al máximo es recomendable modelar las estructuras de datos con `sealed interface` y records.

Las APIs complementarias que llegan en estas versiones redondean la experiencia diaria. La concurrencia estructurada (`StructuredTaskScope`, en preview desde Java 21 y camino a ser final en 25) organiza las tareas concurrentes en bloques sintácticos: las tareas lanzadas dentro de un scope están vinculadas a la vida del bloque; si el scope se cierra (por ejemplo, al salir de un `try`‑with‑resources), todas las tareas pendientes se cancelan automáticamente. Esto contrasta con `CompletableFuture`, donde es fácil olvidar cancelar las ramas fallidas o perder la traza de errores. Aquí, una política como `ShutdownOnFailure` propaga las excepciones y cierra las tareas hermanas cuando una falla.

Los scoped values (`ScopedValue`) ofrecen una alternativa inmutable y de ámbito controlado a `ThreadLocal`. Con virtual threads abundantes, `ThreadLocal` puede inflar el consumo de memoria y complicar la limpieza. Un scoped value se enlaza dentro de un bloque `where(...).run(...)` y es heredado por cualquier hilo creado en ese ámbito, pero no persiste fuera. Su inmutabilidad y gestión automática del ciclo de vida eliminan fugas y hacen el código más predecible.

Las sequenced collections (Java 21) cierran una carencia histórica: acceder al primer y último elemento de una colección ordenada requería recorrerla o convertirla en lista. Las interfaces `SequencedCollection`, `SequencedSet` y `SequencedMap` unifican estos accesos con métodos `getFirst()`, `getLast()`, `removeFirst()`, `removeLast()` y una vista `reversed()`. Listas, `LinkedHashSet` y `SortedSet` pasan a implementar estas interfaces, simplificando algoritmos que necesitan extremos o inversión.

## Ejemplos de código paso a paso

Todos los fragmentos que siguen son completos y muestran las novedades en escenarios realistas.

**Ejemplo 1: Virtual threads y su escalabilidad en tareas bloqueantes**  
Simulamos 100.000 peticiones que duermen 1 segundo, comparando un pool de plataforma pequeño con virtual threads.

```java
import java.time.Duration;
import java.time.Instant;
import java.util.concurrent.Executors;
import java.util.concurrent.ExecutorService;
import java.util.stream.IntStream;

public class VirtualThreadDemo {
    public static void main(String[] args) throws Exception {
        int tareas = 100_000;
        // Pool de plataforma tradicional con 200 hilos
        Instant inicio = Instant.now();
        try (ExecutorService fixedPool = Executors.newFixedThreadPool(200)) {
            IntStream.range(0, tareas).forEach(i ->
                fixedPool.submit(() -> {
                    try { Thread.sleep(1000); } catch (InterruptedException e) { }
                })
            );
        }
        Instant fin = Instant.now();
        System.out.println("Platform pool (200 hilos): " + Duration.between(inicio, fin).toSeconds() + " segundos");

        // Virtual threads
        inicio = Instant.now();
        try (ExecutorService virtualPool = Executors.newVirtualThreadPerTaskExecutor()) {
            IntStream.range(0, tareas).forEach(i ->
                virtualPool.submit(() -> {
                    try { Thread.sleep(1000); } catch (InterruptedException e) { }
                })
            );
        }
        fin = Instant.now();
        System.out.println("Virtual threads: " + Duration.between(inicio, fin).toSeconds() + " segundos");
    }
}
```

Con virtual threads, el tiempo total será de segundos, mientras que el pool fijo puede tardar minutos, pues solo puede ejecutar 200 tareas a la vez bloqueando cada una.

**Ejemplo 2: Pattern matching con switch y records**  
Una jerarquía sellada de figuras, con cálculo de área exhaustivo y patrón sin nombre para ignorar.

```java
sealed interface Shape permits Circle, Rectangle, Square {}
record Circle(double radius) implements Shape {}
record Rectangle(double width, double height) implements Shape {}
record Square(double side) implements Shape {}

public class ShapeArea {
    public static double area(Shape s) {
        return switch (s) {
            case Circle(var r) -> Math.PI * r * r;
            case Rectangle(var w, var h) -> w * h;
            case Square(double side) -> side * side; // patrón inline
            // No se necesita caso default, la clase es sellada
        };
    }

    public static void main(String[] args) {
        Shape shape = new Square(5);
        System.out.println("Área: " + area(shape));
        // Patrón sin nombre (disponible desde Java 21 preview):
        // case Rectangle(_, var h) -> ...;
    }
}
```

El compilador rechaza cualquier omisión y optimiza el despacho.

**Ejemplo 3: Structured concurrency con ShutdownOnFailure**  
Consultamos dos servicios en paralelo y combinamos sus resultados. Si uno falla, el otro se cancela automáticamente.

```java
import java.util.concurrent.*;

public class StructuredConcurrencyExample {
    public static void main(String[] args) throws ExecutionException, InterruptedException {
        String resultado = fetchAndCombine();
        System.out.println("Resultado combinado: " + resultado);
    }

    static String fetchAndCombine() throws InterruptedException, ExecutionException {
        try (var scope = new StructuredTaskScope.ShutdownOnFailure()) {
            Callable<String> tarea1 = () -> { Thread.sleep(200); return "abc"; };
            Callable<String> tarea2 = () -> { Thread.sleep(100); return "xyz"; };

            StructuredTaskScope.Subtask<String> sub1 = scope.fork(tarea1);
            StructuredTaskScope.Subtask<String> sub2 = scope.fork(tarea2);

            scope.join();           // espera a que terminen o fallen
            scope.throwIfFailed();  // propaga excepciones si alguna falló

            return sub1.get() + "-" + sub2.get();
        }
    }
}
```

El `try`-with‑resources garantiza la cancelación de cualquier tarea aún en ejecución al salir del ámbito.

**Ejemplo 4: Scoped values como alternativa a ThreadLocal**  
Propagamos un `requestId` dentro de un hilo virtual sin posibilidad de fugas.

```java
public class ScopedValueDemo {
    private static final ScopedValue<String> REQUEST_ID =
            ScopedValue.newInstance();

    public static void main(String[] args) {
        ScopedValue.where(REQUEST_ID, "req-123").run(() -> {
            System.out.println("Dentro: " + REQUEST_ID.get());
            procesarSolicitud();
            // Dentro de procesarSolicitud, cualquier método llamado también ve "req-123"
        });

        // Fuera del bloque, la variable no está vinculada
        // System.out.println(REQUEST_ID.get());  // lanza NoSuchElementException
    }

    static void procesarSolicitud() {
        System.out.println("Procesando petición: " + REQUEST_ID.get());
    }
}
```

Scoped values son inmutables y se heredan en hilos virtuales creados dentro del ámbito, sin el overhead de `ThreadLocal` con millones de hilos.

**Ejemplo 5: Sequenced collections en una cola de reprocesamiento LIFO**  
Usamos `LinkedList` para acceder fácilmente al primer y último elemento y recorrer en orden inverso.

```java
import java.util.LinkedList;
import java.util.SequencedCollection;

public class SequencedCollectionDemo {
    public static void main(String[] args) {
        SequencedCollection<String> cola = new LinkedList<>();
        cola.addLast("msg1");
        cola.addLast("msg2");
        cola.addLast("msg3");

        System.out.println("Primero: " + cola.getFirst()); // msg1
        System.out.println("Último: " + cola.getLast());   // msg3
        System.out.println("Recorrido LIFO:");
        for (String msg : cola.reversed()) {
            System.out.println(" -> " + msg); // msg3, msg2, msg1
        }
    }
}
```

Estas interfaces unifican el comportamiento en listas, `LinkedHashSet`, `TreeSet` y mapas secuenciados.

## Errores frecuentes al adoptar las nuevas capacidades

Aunque las novedades están diseñadas para simplificar, existen trampas que pueden degradar la escalabilidad o romper la semántica esperada.

**Pinning por bloques `synchronized` o JNI**  
El fallo más común con virtual threads es el pinning inadvertido. Si un hilo virtual ejecuta un bloque `synchronized` y se bloquea dentro de él (por ejemplo, con una llamada a `Socket.read()`), no puede ser desmontado del carrier thread. Con muchas peticiones concurrentes que entren en estos bloques, el pool de carriers se satura y la escalabilidad cae en picado. La solución es reemplazar los `synchronized` por `ReentrantLock` o, para código heredado, usar `jcmd` y las opciones `-Djdk.tracePinnedThreads` para identificar los puntos conflictivos. El pinning también ocurre al invocar código nativo a través de JNI.

**Sobrecarga con tareas CPU‑bound**  
Los virtual threads no aceleran tareas intensivas en CPU; al revés, pueden saturar el `ForkJoinPool` común si no se controla el paralelismo. Lanzar cientos de miles de virtual threads que compitan por la CPU generará sobrecarga de cambio de contexto y contendrá los carriers sin aprovechar la ventaja de la suspensión. Se recomienda usar un semáforo o un pool de tareas limitado para tareas CPU‑bound, manteniendo los virtual threads sólo para la orquestación de I/O.

**En pattern matching, el manejo de `null` y ramas inaccesibles**  
Un `switch` exhaustivo sobre una sealed hierarchy no maneja `null` por defecto. Si la variable puede ser `null`, el `switch` lanzará `NullPointerException`. Es necesario incluir un caso `case null -> ...` explícito si se desea otra semántica. Además, al escribir patrones, hay que vigilar que no existan patrones dominantes que hagan inaccesibles otros; el compilador rechazará esos casos, pero puede ser confuso al principio. Por ejemplo, un `case null, default` antes de otros patrones genera un error.

**Ámbitos de concurrencia estructurada sin `try`-with‑resources**  
Olvidar usar `try`-with‑resources con `StructuredTaskScope` provoca que las tareas lanzadas no se cancelen automáticamente al salir del ámbito, dejando hilos huérfanos y posibles fugas de recursos. Además, la política `ShutdownOnFailure` debe combinarse con `scope.throwIfFailed()`; de lo contrario, los errores se ignoran silenciosamente.

**Persistir con `ThreadLocal` en entornos de virtual threads**  
Cada virtual thread que accede a un `ThreadLocal` genera una nueva entrada en el mapa interno, lo que con millones de hilos provoca un consumo excesivo de memoria. Los scoped values constituyen la alternativa diseñada para este nuevo modelo: inmutables, de ámbito delimitado y con herencia controlada. Migrar código legacy requiere abstraer el acceso mediante patrones que oculten la implementación concreta.

**Confiar en el orden en cualquier `Set` secuenciado**  
Las interfaces `SequencedCollection` y `SequencedSet` se implementan en `LinkedHashSet` y `TreeSet`, pero no en `HashSet`. Suponer que cualquier `Set` tiene un orden de iteración definido llevará a comportamientos impredecibles al usar `getFirst()` o `reversed()`. Es necesario elegir explícitamente una implementación que mantenga el orden de inserción o un orden definido.

Con conciencia de estos puntos, la transición a las nuevas APIs es fluida y los beneficios en mantenibilidad y rendimiento son inmediatos.

## Para saber más

- [JEP 444: Virtual Threads](https://openjdk.org/jeps/444)
- [JEP 441: Pattern Matching for switch](https://openjdk.org/jeps/441)
- [JEP 453: Structured Concurrency (Second Preview)](https://openjdk.org/jeps/453)
- [Documentación oficial de Java 21](https://docs.oracle.com/en/java/javase/21/)
- [Inside Java: artículos de evolución del lenguaje](https://inside.java/)
