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

Un servidor Java con miles de conexiones concurrentes debe elegir un modelo de concurrencia que condiciona la estructura del código, la latencia y la operatividad. No es solo rendimiento: dicta cómo se escriben los handlers, cómo se gestiona la memoria y qué herramientas de diagnóstico estarán disponibles.

Tres modelos dominan: thread-per-request con pool de threads del SO (Tomcat), event-loop no bloqueante (Netty) y virtual threads (Project Loom). La tesis: ninguno es superior en absoluto. La elección depende del perfil de carga —I/O-bound vs CPU-bound, densidad de conexiones— y de las prioridades del equipo en simplicidad, control y madurez operativa.

## Cómo gestiona la concurrencia cada modelo

**Tomcat y el pool de threads del SO.** Cada petición se asigna a un thread del pool. Si el handler ejecuta I/O bloqueante, el thread se suspende y el kernel lo desaloja. El cambio de contexto cuesta microsegundos acumulables. La memoria de stack (1 MB por thread) impone un límite: 5000 threads consumen 5 GB solo en stacks. El scheduler del SO se convierte en cuello de botella. La ventaja es código secuencial, sin callbacks.

**Netty y el event-loop no bloqueante.** Netty usa pocos threads (uno por núcleo) que ejecutan event loops con un `Selector` de NIO. Cuando un canal tiene datos, el loop despacha el evento a una pipeline de `ChannelHandler`s. Todo debe ser no bloqueante: una operación bloqueante accidental paraliza el event loop y todas las conexiones asignadas. A cambio, ofrece control granular de buffers (pooled allocator, zero-copy) y backpressure explícito mediante canales que se desactivan cuando el receptor no consume.

**Virtual threads (Project Loom).** Un virtual thread es un objeto gestionado por la JVM. Al ejecutar una operación bloqueante, la JVM suspende el virtual thread y libera el carrier thread (un thread del SO del ForkJoinPool) para otro virtual thread. El código sigue siendo secuencial. Miles de virtual threads pueden coexistir con pocos carriers. Requiere JDK 21+, APIs que deleguen al scheduler de Loom y cuidado con bloques `synchronized` que provocan *thread pinning*: el carrier queda retenido, degradando el scheduling.

## El factor determinante: perfil de carga y densidad de conexiones

**I/O-bound con alta concurrencia (>10k conexiones).** Cuando el tiempo de respuesta depende de esperas externas, tanto virtual threads como Netty escalan. Los virtual threads ofrecen el mismo throughput con código secuencial, eliminando la complejidad asíncrona. Netty mantiene ventaja si se necesita control fino de memoria: los stacks de virtual threads crecen dinámicamente y, aunque ligeros, decenas de miles pueden presionar al GC. Netty, con buffers reutilizables y zero-copy, minimiza la huella. Además, el backpressure de Netty —pausar lectura cuando los handlers están saturados— es más directo que limitar concurrencia con semáforos en virtual threads.

**CPU-bound o baja concurrencia (<1k conexiones).** Si el handler realiza cómputo intensivo o la concurrencia es moderada, Tomcat con un pool de 200 threads es la opción más simple y robusta. Los virtual threads no aportan ventaja: el overhead de scheduling de la JVM compite con el trabajo útil, y el pool de threads del SO maneja la carga sin problemas. Netty añade complejidad innecesaria.

**Cargas mixtas con picos impredecibles.** Los virtual threads absorben picos porque crear un virtual thread es barato, pero pueden saturar recursos backend si no se limita la concurrencia con un semáforo. Netty permite configurar colas y watermarks para ejercer backpressure desde el borde. Tomcat, con su pool fijo, rechaza peticiones bajo picos extremos —comportamiento predecible pero potencialmente inaceptable para ciertos SLAs.

## Madurez, ecosistema y operatividad

Netty está probado en infraestructura crítica (gRPC, Cassandra, Elasticsearch). Su modelo es bien comprendido, pero la depuración es dura: un stack trace asíncrono muestra frames del event loop, no el flujo lógico de la petición. Se requiere experiencia para diagnosticar bloqueos del event loop y fugas de buffers.

Tomcat es el estándar empresarial. Integración nativa con Servlets, Spring Boot, métricas JMX, herramientas de APM. Cualquier equipo de operaciones sabe monitorizar un pool de threads y detectar saturación.

Los virtual threads están en adopción temprana. Dependen de JDK 21+ y de que librerías (drivers JDBC, clientes HTTP) hayan adaptado sus puntos de bloqueo. El riesgo de *thread pinning* por `synchronized` en código legacy es real y difícil de detectar sin herramientas específicas. La monitorización está evolucionando: JFR emite eventos, pero los APM tradicionales aún no los distinguen con claridad.

## Marco de decisión

Cuatro preguntas en orden:

1. **¿La carga es I/O-bound con más de 10k conexiones concurrentes?** Si la simplicidad del código es prioridad, virtual threads. Si se requiere control extremo de memoria y backpressure, Netty.
2. **¿La carga es CPU-bound o la concurrencia es baja?** Tomcat thread-per-request. No hay razón para pagar la complejidad de los otros modelos.
3. **¿La madurez operativa es crítica y el equipo no puede asumir riesgo de adopción?** Tomcat o Netty según la carga; virtual threads solo si el equipo está dispuesto a invertir en validación de compatibilidad y monitorización.
4. **¿Se necesita backpressure explícito en cada etapa del pipeline?** Netty es la respuesta. Los virtual threads pueden simular backpressure con semáforos, pero no con la granularidad de watermarks por canal.

## Ejemplo concreto: API Gateway con transformación ligera

Un gateway que recibe HTTP, añade headers de enrutamiento y reenvía al backend. La lógica es trivial; el cuello de botella es la llamada al backend.

**Netty.** Pipeline con `HttpRequestDecoder`, un handler que modifica headers y un `HttpClient` no bloqueante. El handler devuelve un `Future`; el event loop continúa. Código asíncrono con `Future.thenCompose`. Un bloqueo accidental detiene el event loop.

```java
ChannelPipeline p = ch.pipeline();
p.addLast(new HttpRequestDecoder());
p.addLast(new HttpObjectAggregator(65536));
p.addLast(new GatewayHandler(httpClient));
// GatewayHandler: channelRead -> modificar headers -> httpClient.execute() -> Future
```

**Tomcat.** Servlet con `HttpURLConnection` bloqueante. Pool de 200 threads limita concurrencia a 200 peticiones simultáneas; con 5000 conexiones, el resto espera o es rechazado.

**Virtual threads.** El mismo código bloqueante del servlet se ejecuta en `Executors.newVirtualThreadPerTaskExecutor()`. Miles de peticiones concurrentes no agotan threads del SO. Para proteger el backend, se añade un `Semaphore` con permisos limitados.

```java
var executor = Executors.newVirtualThreadPerTaskExecutor();
Semaphore backendLimit = new Semaphore(500);
// en cada tarea: backendLimit.acquire(); try { ... llamada HTTP ... } finally { release(); }
```

La diferencia está en la complejidad del código y el mecanismo de protección: Netty lo integra en su modelo de canales; virtual threads requieren control explícito de concurrencia.

## La decisión informada evita sobreingeniería y subestimación

Los virtual threads no vuelven obsoleto a Netty ni a Tomcat. Cierran la brecha entre código secuencial y alta concurrencia, pero no eliminan la necesidad de backpressure ni el control de memoria en escenarios extremos. Tomcat con su pool de threads del SO sigue siendo la opción correcta para la mayoría de aplicaciones empresariales, donde la concurrencia es moderada y la simplicidad operativa pesa más que la escalabilidad infinita.

La decisión debe basarse en métricas reales del perfil de carga —no en intuiciones ni en la novedad de Loom— y en una evaluación honesta de la capacidad del equipo para operar el modelo elegido en producción. Elegir bien es minimizar la complejidad que no aporta valor y maximizar la previsibilidad cuando el sistema está bajo presión.