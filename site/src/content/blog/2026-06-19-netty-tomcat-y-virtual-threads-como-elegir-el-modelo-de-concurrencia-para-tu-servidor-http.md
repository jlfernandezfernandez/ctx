---
title: "Netty, Tomcat y virtual threads: cómo elegir el modelo de concurrencia para tu servidor HTTP"
description: "Cada modelo de concurrencia (thread-per-request, event loop, virtual threads) impone un equilibrio distinto entre simplicidad de código, overhead de recursos y control sobre I/O. Tomcat con pool clásico es simple pero limitado en concurrencia. Netty ofrece escalabilidad extrema a costa de complejidad asíncrona. Virtual threads prometen lo mejor de ambos mundos, pero con riesgos de pinning y madurez operativa. La decisión ya no es solo escalabilidad, sino qué complejidad gestionar."
date: 2026-06-19
tags: ["concurrency", "java", "reactive"]
summary: "Cada modelo de concurrencia (thread-per-request, event loop, virtual threads) impone un equilibrio distinto entre simplicidad de código, overhead de recursos y control sobre I/O. Tomcat con pool clásico es simple pero limitado en concurrencia. Netty ofrece escalabilidad extrema a costa de complejidad asíncrona. Virtual threads prometen lo mejor de ambos mundos, pero con riesgos de pinning y madurez operativa. La decisión ya no es solo escalabilidad, sino qué complejidad gestionar."
issue: 28
requestedBy: "jlfernandezfernandez"
writer: "deepseek-v4-pro"
---

## Tres estrategias de concurrencia para una misma petición HTTP

Cuando un servidor recibe una petición HTTP, debe leer bytes de la red, procesar la solicitud y escribir la respuesta. La diferencia entre Tomcat, Netty y virtual threads está en cómo asignan hilos a ese ciclo de vida. Cada modelo prioriza un equilibrio distinto entre simplicidad de código, overhead de recursos y control sobre la I/O.

### Thread-per-request: el modelo clásico de Tomcat

Tomcat asigna cada conexión a un thread del pool (`maxThreads`, típicamente 200). El thread se bloquea en `InputStream.read()` hasta recibir la petición completa, ejecuta el servlet y se bloquea en `OutputStream.write()` hasta enviar la respuesta. El código es lineal y fácil de depurar:

```java
protected void doGet(HttpServletRequest req, HttpServletResponse resp) {
    String param = req.getParameter("id");
    String result = businessLogic(param); // puede incluir JDBC bloqueante
    resp.getOutputStream().write(result.getBytes());
}
```

La limitación aparece bajo carga: el pool de threads es un cuello de botella. Con 200 threads, 10 000 conexiones simultáneas forman una cola de espera; la latencia se dispara y las conexiones pueden ser rechazadas. Aumentar el pool alivia el síntoma, pero cada thread de plataforma reserva ~1 MB de stack, y el scheduler del kernel introduce contención cuando los threads superan los cores disponibles.

### Event loop + NIO: el modelo reactor de Netty

Netty evita asignar un thread por conexión. Un número reducido de threads (típicamente uno por núcleo) ejecutan *event loops* que sondean canales no bloqueantes mediante `epoll` o `kqueue`. Cada canal registra su interés en eventos de lectura/escritura; el event loop despierta solo cuando hay datos listos.

La lógica se organiza en una pipeline de `ChannelHandler`:

```java
public class MyHandler extends ChannelInboundHandlerAdapter {
    @Override
    public void channelRead(ChannelHandlerContext ctx, Object msg) {
        // msg es un ByteBuf con los datos leídos
        String result = businessLogic(msg.toString());
        ctx.writeAndFlush(Unpooled.copiedBuffer(result.getBytes()));
    }

    @Override
    public void exceptionCaught(ChannelHandlerContext ctx, Throwable cause) {
        cause.printStackTrace();
        ctx.close();
    }
}
```

No hay bloqueo: `channelRead` se invoca cuando los datos están disponibles, y `writeAndFlush` devuelve un `ChannelFuture` para manejar la finalización asíncrona. Esto permite manejar cientos de miles de conexiones con un puñado de threads, pero exige encadenar callbacks, propagar errores manualmente y controlar la contrapresión de forma explícita (`channel.isWritable()`).

### Virtual threads: el scheduler de la JVM toma el control

A partir de Java 21, un *virtual thread* es una abstracción ligera gestionada por la JVM, no por el sistema operativo. Cuando un virtual thread ejecuta una operación bloqueante —`InputStream.read()`, `Thread.sleep()`, una llamada a JDBC—, se *desmonta* del *carrier thread* (un thread de plataforma real) y libera ese carrier para que ejecute otro virtual thread. Al completarse la I/O, el scheduler vuelve a montar el virtual thread sobre un carrier disponible.

El código es idéntico al modelo bloqueante:

```java
Thread.startVirtualThread(() -> {
    String param = req.getParameter("id");
    String result = businessLogic(param);
    resp.getOutputStream().write(result.getBytes());
});
```

La diferencia está en el runtime: el stack del virtual thread se almacena en heap como un objeto contiguo que crece y se reduce dinámicamente (cientos de bytes cuando está inactivo). El scheduler JVM puede mapear millones de virtual threads a unas pocas decenas de carriers. El resultado es escalabilidad similar a Netty con código síncrono.

Pero no es magia. Cada montaje/desmontaje consume ciclos de CPU. Y existe el riesgo de *pinning*: si un virtual thread se bloquea dentro de un bloque `synchronized` o una llamada nativa (JNI), el carrier thread queda retenido y no puede liberarse. En ese caso, el rendimiento colapsa al modelo thread-per-request tradicional, porque cada carrier atrapado equivale a un thread de plataforma bloqueado.

## El precio oculto de los threads de plataforma

Un thread de plataforma es caro. El kernel le asigna un stack de memoria fijo (1 MB por defecto en la mayoría de JVMs) y lo incluye en su planificación. Con 10 000 threads, solo los stacks consumen ~10 GB de RAM. Además, el scheduler del SO incurre en cambios de contexto costosos cuando la cantidad de threads excede los cores; la contención degrada el throughput.

Tomcat con un pool de 200 threads mantiene el sistema seguro, pero no puede absorber picos de 10 000 conexiones concurrentes sin encolar peticiones o rechazarlas. Escalar horizontalmente añade instancias, no resuelve la ineficiencia por conexión.

Netty evade el problema con un modelo reactor: pocos threads propios, I/O delegada al SO mediante `epoll`/`kqueue`. El coste por conexión es una estructura de datos en heap (canal, buffers, pipeline), no un stack de thread. Por eso puede mantener 100 000 conexiones abiertas con un consumo de memoria modesto y sin contención de scheduling.

Los virtual threads cambian la ecuación: el stack vive en el heap y se paga solo por lo que se usa. El scheduler de la JVM (un work-stealing `ForkJoinPool`) mapea miles de virtual threads a unos pocos carriers, típicamente igual al número de cores. La operación bloqueante no consume un thread de SO; el carrier se libera y atiende otro virtual thread. El límite de concurrencia pasa a ser la memoria heap y la capacidad de scheduling, no el número de threads de plataforma.

## Asincronía: control fino a cambio de complejidad

Netty ofrece un control granular sobre buffers, protocolos y contrapresión que no existe en los otros modelos. Se puede decidir exactamente cuándo leer, cuándo escribir y cuántos bytes aceptar antes de aplicar backpressure. Es la opción natural para proxies, gateways de API, brokers de mensajería o servidores de juegos donde el rendimiento de red es crítico y los protocolos no siempre son HTTP.

Ese control tiene un precio. El código asíncrono con callbacks encadenados (`ChannelFutureListener`) es más difícil de escribir, leer y depurar. Los stacks truncados y los eventos fuera de orden complican el diagnóstico de errores. La contrapresión debe implementarse manualmente verificando `channel.isWritable()` y configurando `WriteBufferWaterMark`. La complejidad se justifica cuando los requisitos de rendimiento o de protocolo no admiten otra solución.

Tomcat, en el extremo opuesto, ofrece la simplicidad del código bloqueante y la compatibilidad total con el ecosistema síncrono (JDBC, JPA, JMS). Pero esa simplicidad es frágil bajo carga: el pool de threads se agota, la latencia crece y las conexiones se rechazan. Escalar requiere más instancias o aumentar threads a costa de memoria y contención.

Los virtual threads prometen eliminar esa disyuntiva: permiten escribir código bloqueante simple y escalar a millones de conexiones. Sin embargo, el scheduler introduce una latencia de scheduling que puede ser relevante en sistemas con deadlines estrictos. El *pinning* es un riesgo real: bibliotecas que usan `synchronized` internamente (como algunas versiones de drivers JDBC o clientes HTTP) pueden retener el carrier y degradar el rendimiento. Además, el ecosistema de monitoreo es inmaduro: `jstack` muestra carriers, no virtual threads individuales; se requieren `jcmd` y nuevas APIs para obtener volcados utilizables.

## Cuándo elegir cada modelo

**Tomcat con pool clásico** sigue siendo adecuado para aplicaciones empresariales con menos de 10 000 conexiones concurrentes, latencias de I/O bajas y un ecosistema 100 % bloqueante. La simplicidad operativa y la depuración tradicional pesan más que la escalabilidad extrema.

**Netty** (o frameworks asíncronos como Vert.x) es la elección cuando se necesitan más de 100 000 conexiones simultáneas, control fino sobre buffers y protocolos no HTTP, o rendimiento de red extremo. Requiere equipos con experiencia en programación reactiva y tolerancia a una mayor complejidad de código.

**Virtual threads** (con Tomcat embebido o servidores compatibles con Loom) encajan en nuevos servicios que requieren alta concurrencia (>10 000 conexiones) pero desean mantener código síncrono. También permiten migrar aplicaciones bloqueantes existentes para soportar picos de carga sin reescribir la lógica de negocio. La cautela es obligatoria: hay que auditar las bibliotecas en busca de *pinning* frecuente y asumir que el ecosistema de monitoreo aún está evolucionando.

## La decisión ya no es solo escalabilidad

Virtual threads eliminan la falsa dicotomía «simple y limitado vs. complejo y escalable». Pero no convierten a Netty en obsoleto ni a Tomcat en irrelevante. Netty retiene la ventaja en casos extremos de rendimiento y control; Tomcat clásico sigue siendo suficiente para cargas moderadas con ecosistemas maduros. La decisión ahora se desplaza hacia la madurez operativa, la tolerancia al *pinning* y la necesidad de control fino sobre la I/O. Elegir modelo de concurrencia ya no es solo una cuestión de escalabilidad: es una cuestión de qué complejidad estamos dispuestos a gestionar y qué garantías necesitamos sobre el runtime.
