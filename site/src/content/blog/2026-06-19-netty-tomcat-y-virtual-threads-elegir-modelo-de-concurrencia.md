---
title: "Netty, Tomcat y virtual threads: elegir modelo de concurrencia"
description: "Tres modelos compiten para manejar concurrencia en Java: thread-per-request de Tomcat, event-loop no bloqueante de Netty y virtual threads de Project Loom. La decisión depende del perfil de carga (I/O-bound vs CPU-bound), la densidad de conexiones y la madurez operativa del equipo."
date: 2026-06-19
tags: ["java", "concurrency", "reactive"]
summary: "Tres modelos compiten para manejar concurrencia en Java: thread-per-request de Tomcat, event-loop no bloqueante de Netty y virtual threads de Project Loom. La decisión depende del perfil de carga (I/O-bound vs CPU-bound), la densidad de conexiones y la madurez operativa del equipo."
issue: 28
requestedBy: "jlfernandezfernandez"
writer: "deepseek-v4-pro"
---

## El dilema real: por qué el modelo de concurrencia define tu arquitectura

Un servidor Java que maneja miles de conexiones concurrentes enfrenta una decisión que condiciona la estructura del código, el perfil de latencia y la capacidad operativa del sistema. No se trata solo de rendimiento: el modelo de concurrencia dicta cómo se escribe cada handler, cómo se gestiona la memoria y qué herramientas de diagnóstico estarán disponibles en producción.

Tres modelos dominan la discusión hoy: el clásico thread-per-request que Tomcat encarna con su pool de threads del SO; el event-loop no bloqueante de Netty, que multiplexa conexiones sobre unos pocos threads; y los virtual threads de Project Loom, que prometen código secuencial con escalabilidad de modelo asíncrono. La tesis es que ninguno es superior en absoluto. La elección correcta depende del perfil de carga —I/O-bound versus CPU-bound, densidad de conexiones— y de las prioridades del equipo en simplicidad, control y madurez operativa.

## Cómo gestiona la concurrencia cada modelo

**Tomcat y el pool de threads del SO.** En el modelo thread-per-request, cada petición HTTP se asigna a un thread del pool. Si el handler ejecuta I/O bloqueante —una consulta JDBC, una llamada HTTP a un backend— el thread se suspende. El kernel lo desaloja de la CPU, guarda su estado y planifica otro. Este cambio de contexto cuesta microsegundos que se acumulan. La memoria de stack por thread (típicamente 1 MB) impone un límite duro: con 5000 threads, solo los stacks consumen 5 GB. A partir de ahí, el scheduler del SO se convierte en el cuello de botella. La ventaja es un modelo de programación lineal: el código se lee de arriba abajo, sin callbacks ni máquinas de estados.

**Netty y el event-loop no bloqueante.** Netty opera con pocos threads —uno por núcleo de CPU— que ejecutan event loops. Cada loop usa un `Selector` de NIO para monitorizar miles de canales. Cuando un canal tiene datos disponibles, el loop despacha el evento a una pipeline de `ChannelHandler`s. Todo debe ser no bloqueante: si un handler realiza I/O, debe devolver un `Future` y ceder el thread. Un bloqueo accidental —una llamada JDBC síncrona, un `Thread.sleep()`— paraliza el event loop entero y todas las conexiones asignadas a él. A cambio, Netty ofrece control granular sobre asignación de buffers (pooled allocator, zero-copy) y backpressure explícito mediante canales de escritura que se desactivan cuando el receptor no consume.

**Virtual threads (Project Loom).** Un virtual thread es un objeto gestionado por la JVM, no un thread del SO. Cuando ejecuta una operación bloqueante —I/O, `Thread.sleep()`, una llamada a un socket— la JVM suspende el virtual thread y libera el carrier thread (un thread del SO del pool de ForkJoinPool) para que ejecute otro virtual thread. El código sigue siendo secuencial e imperativo. La escalabilidad se aproxima a la del modelo asíncrono porque miles de virtual threads pueden coexistir con un puñado de carriers. Las limitaciones: requiere JDK 21+, APIs que deleguen al scheduler de Loom (JDBC con driver compatible, HTTP client de Java 11+) y cuidado con bloques `synchronized` que provocan *thread pinning* —el carrier queda retenido y no se libera, degradando el scheduling.

## El factor determinante: perfil de carga y densidad de conexiones

**I/O-bound con alta concurrencia (>10k conexiones).** Cuando el tiempo de respuesta está dominado por esperas externas —bases de datos, APIs remotas— y la tasa de conexiones es alta, tanto virtual threads como Netty escalan. Los virtual threads ofrecen el mismo throughput con código secuencial, eliminando la complejidad asíncrona. Netty mantiene ventaja si se necesita control fino de memoria: cada virtual thread tiene un stack que crece dinámicamente, y aunque es órdenes de magnitud más ligero que un stack del SO, decenas de miles pueden sumar presión sobre el GC. Netty, con sus buffers reutilizables y zero-copy, minimiza la huella. Además, el backpressure explícito de Netty —pausar la lectura cuando los handlers posteriores están saturados— es más directo que limitar concurrencia con semáforos en virtual threads.

**CPU-bound o baja concurrencia (<1k conexiones).** Si el handler realiza cómputo intensivo —procesamiento de imágenes, serialización pesada— o la concurrencia es moderada, Tomcat con un pool de 200 threads es la opción más simple y robusta. Los virtual threads no aportan ventaja: el overhead de scheduling de la JVM compite con el trabajo útil, y el pool de threads del SO ya maneja la carga sin problemas. Netty añade complejidad innecesaria sin beneficio de rendimiento.

**Cargas mixtas con picos impredecibles.** Los virtual threads absorben picos de conexiones sin rechazar peticiones, porque crear un virtual thread es barato. Pero esa misma facilidad puede saturar recursos backend si no se limita la concurrencia con un semáforo o un pool. Netty permite configurar colas y watermarks en los canales para ejercer backpressure desde el borde. Tomcat clásico, con su pool fijo, rechaza peticiones bajo picos extremos —un comportamiento predecible pero potencialmente inaceptable para ciertos SLAs.

## Madurez, ecosistema y operatividad

Netty está probado en infraestructura crítica: gRPC, Cassandra, Elasticsearch. Su modelo de concurrencia es bien comprendido, pero la depuración es dura. Un stack trace de una excepción en un pipeline asíncrono muestra frames del event loop, no el flujo lógico de la petición. Se requiere experiencia para diagnosticar bloqueos del event loop y fugas de buffers.

Tomcat es el estándar de facto en aplicaciones empresariales. Integración nativa con Servlets, Spring Boot, métricas JMX, herramientas de APM. La operación es conocida: cualquier equipo de operaciones sabe monitorizar un pool de threads y detectar su saturación.

Los virtual threads están en adopción temprana. Dependen de JDK 21+ y de que las librerías del ecosistema —drivers JDBC, clientes HTTP, frameworks— hayan adaptado sus puntos de bloqueo al scheduler de Loom. El riesgo de *thread pinning* por `synchronized` en código legacy es real y difícil de detectar sin herramientas específicas. La monitorización está evolucionando: JFR emite eventos de virtual threads, pero los APM tradicionales aún no los distinguen con claridad.

## Marco de decisión

La elección se reduce a cuatro preguntas aplicadas en orden:

1. **¿La carga es I/O-bound con más de 10k conexiones concurrentes?** Si la simplicidad del código es prioridad, virtual threads. Si se requiere control extremo de memoria y backpressure, Netty.
2. **¿La carga es CPU-bound o la concurrencia es baja?** Tomcat thread-per-request. No hay razón para pagar la complejidad de los otros modelos.
3. **¿La madurez operativa es crítica y el equipo no puede asumir riesgo de adopción?** Tomcat o Netty según la carga; virtual threads solo si el equipo está dispuesto a invertir en validación de compatibilidad y monitorización.
4. **¿Se necesita backpressure explícito en cada etapa del pipeline?** Netty es la respuesta. Los virtual threads pueden simular backpressure con semáforos, pero no con la granularidad de watermarks por canal.

## Ejemplo concreto: API Gateway con transformación ligera

Un gateway que recibe HTTP, añade headers de enrutamiento y reenvía al backend. La lógica de negocio es trivial; el cuello de botella es la llamada al backend.

**Netty.** Se construye una pipeline con `HttpRequestDecoder`, un handler que modifica headers y un `HttpClient` no bloqueante. El handler devuelve un `Future`; el event loop continúa con otras conexiones. El código es asíncrono, con encadenamiento de `Future.thenCompose`. Un bloqueo accidental en el handler —por ejemplo, un logger que escribe a disco síncronamente— detiene el event loop.

```java
ChannelPipeline p = ch.pipeline();
p.addLast(new HttpRequestDecoder());
p.addLast(new HttpObjectAggregator(65536));
p.addLast(new GatewayHandler(httpClient));
// GatewayHandler: channelRead -> modificar headers -> httpClient.execute() -> Future
```

**Tomcat.** Un servlet con `HttpURLConnection` bloqueante. El pool de 200 threads limita la concurrencia a 200 peticiones simultáneas. Con 5000 conexiones entrantes, 4800 esperan en la cola de accept del SO o son rechazadas.

```java
protected void doGet(HttpServletRequest req, HttpServletResponse resp) {
    URL url = new URL("http://backend" + req.getPathInfo());
    HttpURLConnection conn = (HttpURLConnection) url.openConnection();
    // copiar headers, copiar cuerpo
    // bloquea hasta respuesta del backend
}
```

**Virtual threads.** El mismo código bloqueante del servlet se ejecuta dentro de `Executors.newVirtualThreadPerTaskExecutor()`. Miles de peticiones concurrentes no agotan threads del SO. Para proteger el backend de una sobrecarga, se añade un `Semaphore` con permisos limitados antes de la llamada HTTP.

```java
var executor = Executors.newVirtualThreadPerTaskExecutor();
Semaphore backendLimit = new Semaphore(500);
// en cada tarea: backendLimit.acquire(); try { ... llamada HTTP ... } finally { release(); }
```

La diferencia está en la complejidad del código y en el mecanismo de protección: Netty lo tiene integrado en su modelo de canales; virtual threads requieren un control explícito de concurrencia.

## La decisión informada evita sobreingeniería y subestimación

Los virtual threads no vuelven obsoleto a Netty ni a Tomcat. Cierran la brecha entre código secuencial y alta concurrencia, pero no eliminan la necesidad de backpressure ni el control de memoria en escenarios extremos. Tomcat con su pool de threads del SO sigue siendo la opción correcta para la mayoría de aplicaciones empresariales, donde la concurrencia es moderada y la simplicidad operativa pesa más que la escalabilidad infinita.

La decisión debe basarse en métricas reales del perfil de carga —no en intuiciones ni en la novedad de Loom— y en una evaluación honesta de la capacidad del equipo para operar el modelo elegido en producción. Elegir bien es minimizar la complejidad que no aporta valor y maximizar la previsibilidad cuando el sistema está bajo presión.
