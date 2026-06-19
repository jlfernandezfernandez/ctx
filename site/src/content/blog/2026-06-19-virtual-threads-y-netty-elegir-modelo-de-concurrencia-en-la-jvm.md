---
title: "Virtual threads y Netty: elegir modelo de concurrencia en la JVM"
description: "Los virtual threads de la JDK 21 devuelven escalabilidad al código síncrono, compitiendo con Netty en servicios HTTP típicos. Netty sigue siendo superior donde se requiere control granular sobre buffers, backpressure o cero copias. La decisión es económica: simplicidad de desarrollo frente a rendimiento extremo."
date: 2026-06-19
tags: ["java", "concurrency", "virtual-threads"]
summary: "Los virtual threads de la JDK 21 devuelven escalabilidad al código síncrono, compitiendo con Netty en servicios HTTP típicos. Netty sigue siendo superior donde se requiere control granular sobre buffers, backpressure o cero copias. La decisión es económica: simplicidad de desarrollo frente a rendimiento extremo."
issue: 28
requestedBy: "jlfernandezfernandez"
writer: "deepseek-v4-pro"
---

El dilema comenzó cuando los servidores web alcanzaron su límite físico. Durante años, el modelo dominante fue simple: una *thread* del sistema operativo por cada petición concurrente. Tomcat en modo BIO encarnaba esta filosofía. El contenedor mantenía un pool de *threads* nativas, y cada una tomaba una conexión, leía la petición, invocaba el servlet y escribía la respuesta. El código de negocio era síncrono, secuencial y fácil de razonar.

El problema no era la lógica, sino la factura que pasaba el SO. Cada *thread* de plataforma exigía alrededor de 1 MB de pila, y el *context switch* entre *threads* implicaba salvar y restaurar registros, cambiar espacios de memoria y vaciar TLB. Con 10.000 conexiones concurrentes —el famoso problema C10k—, el sistema se ahogaba en consumo de memoria o en *thrashing* del scheduler. La solución fue abandonar el modelo uno-a-uno: en lugar de una *thread* por petición, un pequeño conjunto de *threads* manejaría miles de conexiones mediante I/O no bloqueante y *event loops*. Netty se convirtió en el estándar de facto para este patrón en la JVM, igual que Nginx en el mundo C y Node.js en JavaScript. El precio fue un modelo de programación radicalmente distinto: *callbacks*, *futures*, *promises* y la pérdida del flujo secuencial que hacía triviales el debugging y el manejo de excepciones.

## Virtual threads: el sistema operativo sale del camino

Project Loom introdujo en la JDK 21 los *virtual threads*, una abstracción que traslada la gestión de concurrencia del kernel a la JVM. Un *virtual thread* es una estructura ligera cuyo *stack* se almacena en el heap como un objeto Java, ocupando típicamente entre 200 y 300 bytes, y crece bajo demanda en lugar de reservar un megabyte por adelantado. La JVM programa estos *virtual threads* sobre un número reducido de *carrier threads* —*threads* de plataforma reales— usando un *scheduler* basado en *work-stealing* implementado sobre `ForkJoinPool`.

El mecanismo clave es el *desmontaje* (*unmounting*). Cuando un *virtual thread* ejecuta una operación bloqueante —I/O de red, `Thread.sleep()`, adquisición de un `ReentrantLock`—, la JVM libera el *carrier thread* que lo transportaba y lo asigna a otro *virtual thread* listo para ejecutarse. El *virtual thread* bloqueado permanece en el heap, y cuando la operación se completa, el scheduler lo vuelve a montar sobre un *carrier thread* disponible. Esto permite que millones de *virtual threads* coexistan sin saturar la memoria ni provocar los *context switches* de SO que lastraban el modelo tradicional.

La consecuencia práctica es inmediata: el estilo de programación síncrono y bloqueante vuelve a ser escalable. Un servidor HTTP puede aceptar una petición, asignarle un *virtual thread* y ejecutar dentro de él llamadas bloqueantes a base de datos, a otros servicios HTTP o a cualquier recurso externo, sin preocuparse por agotar el pool de *threads* del SO. El modelo *thread-per-request* se reconcilia con la alta concurrencia.

## Netty: donde el control fino sigue siendo determinante

Netty no es simplemente un servidor NIO. Es un *framework* para construir aplicaciones de red que ofrece un nivel de control sobre buffers, pipelines de procesamiento y transports que los *virtual threads* no reemplazan. Su arquitectura se basa en *event loops* que multiplexan miles de canales sobre un número reducido de *threads*, pero la diferencia con un uso ingenuo de NIO está en los detalles.

El modelo de pipeline de Netty permite encadenar `ChannelHandler` para codificación, decodificación, framing, compresión y lógica de negocio. Cada *handler* puede manipular buffers de forma eficiente y ejercer *backpressure* explícito: cuando un *handler* downstream no puede procesar más datos, la presión se propaga hacia arriba hasta frenar la lectura del socket. Esto es crítico en proxies y *message brokers*, donde un extremo rápido puede saturar a un consumidor lento.

Netty también ofrece *zero-copy* mediante buffers compuestos y transferencias directas entre canales usando `FileRegion` y `sendfile`. En transports nativos como `EpollEventLoopGroup` (Linux) o `IoUringEventLoopGroup` (kernel 5.10+), estas operaciones evitan copias entre espacio de usuario y kernel, reduciendo latencia y consumo de CPU. Un *virtual thread* que lee de un `SocketChannel` y escribe en otro realiza al menos dos copias: del buffer del socket al buffer del *virtual thread*, y de ahí al buffer de salida. Netty puede encadenar ambos canales sin que los datos abandonen el *off-heap*.

Además, Netty separa estructuralmente la I/O del procesamiento. Los *event loops* solo manejan operaciones no bloqueantes; cualquier tarea que pueda bloquear se despacha a un `EventExecutorGroup` separado. Esto evita que una tarea lenta detenga el *event loop* y afecte a miles de conexiones. Con *virtual threads*, esta separación no es automática: si un *virtual thread* se *pinna* —por ejemplo, al ejecutar código nativo o al bloquear dentro de un bloque `synchronized`—, queda anclado a su *carrier thread* y bloquea a todos los *virtual threads* que compartían ese *carrier*, degradando la escalabilidad.

## Tomcat con virtual threads: la simplicidad escalable

Tomcat 10 permite configurar el *executor* del `Connector` para usar `VirtualThreadExecutor`. El código de aplicación —Servlets, filtros, controladores Spring MVC— se escribe de forma síncrona, sin `CompletableFuture` ni *callbacks*. El modelo mental es secuencial: recibir petición, validar, consultar base de datos, llamar a otro servicio, componer respuesta. El debugging recupera su linealidad, y el *tracing* distribuido no necesita propagar contextos a través de *futures*.

```java
// Configuración de Tomcat con virtual threads (programática)
Tomcat tomcat = new Tomcat();
Connector connector = new Connector("HTTP/1.1");
connector.setPort(8080);
// Usar virtual threads en lugar del pool de threads de plataforma
connector.getProtocolHandler().setExecutor(Executors.newVirtualThreadPerTaskExecutor());
tomcat.setConnector(connector);
```

Este modelo escala bien para cargas de trabajo típicas de servicios web: decenas de miles de peticiones concurrentes, cada una con varias llamadas bloqueantes a bases de datos o APIs externas. Sin embargo, tiene límites. El *pinning* en bloques `synchronized` o en llamadas nativas (JNI, `FileInputStream` en algunas implementaciones) puede reducir la escalabilidad. La contención en recursos compartidos —un pool de conexiones a base de datos de 20 conexiones frente a 10.000 *virtual threads*— no desaparece; solo cambia de sitio el cuello de botella. Y el *throughput* máximo, en escenarios de tráfico extremadamente denso, puede ser inferior al de un *event loop* bien afinado debido a la sobrecarga de las *continuations* y al *scheduling* cooperativo.

## Criterios de decisión

**Elige Tomcat + virtual threads cuando:**

- La lógica de negocio es inherentemente síncrona: llamadas a bases de datos, APIs REST, código *legacy* que asume un modelo secuencial.
- El equipo prioriza velocidad de desarrollo y no tiene experiencia profunda en programación reactiva.
- La concurrencia es alta pero no extrema (<100k conexiones persistentes con tráfico moderado).
- No necesitas control explícito sobre buffers, *backpressure* o protocolos binarios complejos.

**Elige Netty cuando:**

- Construyes proxies, *message brokers*, gateways de alto rendimiento o servidores de juegos con requisitos de latencia de microsegundos.
- Manejas cientos de miles de conexiones de larga duración con poco tráfico por conexión (IoT, chat, notificaciones push).
- El protocolo exige procesamiento de *streaming*, control de flujo a nivel de bytes o *zero-copy* entre canales.
- Ya tienes una base de código Netty y el coste de migrar a *virtual threads* no se justifica frente al beneficio.

**Zona gris — servicios web típicos:** Para un servicio HTTP que recibe peticiones, consulta una base de datos y responde JSON, Tomcat con *virtual threads* ofrece un modelo de desarrollo más simple y un rendimiento comparable a Netty. La diferencia de *throughput* en este escenario rara vez justifica la complejidad adicional de un pipeline Netty. Netty sigue siendo superior en el *edge* —donde el control sobre la capa de transporte es crítico— y en infraestructura de red especializada.

## La decisión no es técnica, es económica

Los *virtual threads* no eliminan a Netty, pero reducen drásticamente el espacio donde la complejidad reactiva está justificada. La elección entre ambos modelos ya no es binaria ni puramente técnica: es una decisión económica que sopesa el coste de desarrollo y mantenimiento frente al beneficio del control granular. En la mayoría de los sistemas, la respuesta será usar ambas herramientas donde cada una brilla: Tomcat con *virtual threads* para servicios de negocio, y Netty para la infraestructura de red que exige exprimir cada microsegundo.
