---
title: "Netty vs Tomcat: cuándo usar cada uno"
description: "Tomcat utiliza un modelo hilo-por-petición que simplifica el desarrollo pero limita la escalabilidad a miles de conexiones concurrentes. Netty emplea event loops y I/O no bloqueante para manejar decenas de miles de conexiones con un puñado de hilos, y Reactor Netty añade backpressure reactiva extremo a extremo. La elección depende de la carga: Tomcat para aplicaciones web tradicionales con concurrencia moderada, Netty/Reactor Netty para alta concurrencia, WebSockets y stacks completamente reactivos."
date: 2026-06-11
tags: ["java", "reactive"]
summary: "Tomcat utiliza un modelo hilo-por-petición que simplifica el desarrollo pero limita la escalabilidad a miles de conexiones concurrentes. Netty emplea event loops y I/O no bloqueante para manejar decenas de miles de conexiones con un puñado de hilos, y Reactor Netty añade backpressure reactiva extremo a extremo. La elección depende de la carga: Tomcat para aplicaciones web tradicionales con concurrencia moderada, Netty/Reactor Netty para alta concurrencia, WebSockets y stacks completamente reactivos."
issue: 15
requestedBy: "jlfernandezfernandez"
writer: "deepseek-v4-pro"
reviewer: "minimax-m3"
---

## El cuello de botella del modelo hilo-por-petición y la necesidad de I/O no bloqueante

Durante años, los servidores web Java se construyeron sobre un modelo simple: cada petición HTTP entrante se asignaba a un hilo dedicado del pool, que la procesaba de principio a fin. Este enfoque, heredado de la especificación de servlets y popularizado por Apache Tomcat, funciona bien para cargas moderadas. Sin embargo, cuando el número de conexiones concurrentes crece, el modelo hilo-por-petición choca con el problema C10K: manejar diez mil clientes simultáneos con un hilo por cada uno consume una cantidad prohibitiva de memoria (cada hilo requiere su propia pila, típicamente 1 MB) y genera un overhead de CPU por el cambio de contexto entre hilos. En aplicaciones modernas —microservicios que invocan decenas de servicios externos, APIs con miles de clientes móviles, WebSockets que mantienen conexiones persistentes, o streaming de datos— la escalabilidad exige un paradigma diferente: I/O no bloqueante y arquitecturas asíncronas.

Aquí es donde la comparación entre Tomcat y Netty se vuelve relevante. Tomcat es el contenedor de servlets maduro por excelencia, robusto, con un ecosistema enorme (Spring MVC, seguridad declarativa, JSP, etc.). Netty, en cambio, es un framework de red asíncrono de alto rendimiento, diseñado desde cero para exprimir las capacidades de NIO y multiplexar miles de conexiones en un puñado de hilos. No son productos intercambiables: Tomcat es un servidor de aplicaciones HTTP completo, mientras que Netty es una herramienta de más bajo nivel para construir servidores y clientes de red con protocolos arbitrarios. Pero en la práctica, al elegir la base sobre la que correrá una aplicación, surge la disyuntiva: ¿usamos el modelo síncrono y familiar de Tomcat, o damos el salto a una arquitectura no bloqueante con Netty o Reactor Netty?

El ecosistema reactivo añade otra capa. Netty es la base de Reactor Netty, el motor que permite a Spring WebFlux ejecutar aplicaciones completamente no bloqueantes con backpressure de Reactive Streams. Tomcat, a partir de la versión 8, también incorporó soporte para servlets asíncronos y puede servir aplicaciones reactivas, pero lo hace con limitaciones: la API de servlet sigue anclada en InputStream/OutputStream, y el modelo de concurrencia subyacente no es puramente no bloqueante. Entender las diferencias arquitectónicas profundas entre Tomcat y Netty es esencial para decidir cuál se adapta mejor a los requisitos de concurrencia, latencia y modelo de programación de un proyecto.

## Dos paradigmas de concurrencia opuestos

La diferencia fundamental entre Tomcat y Netty radica en cómo gestionan las conexiones y las peticiones. Tomcat se basa en la especificación de servlets, que define un modelo de procesamiento síncrono: el contenedor invoca el método `service()` del servlet, y dentro de ese método el desarrollador lee el `InputStream` y escribe el `OutputStream`. Aunque Tomcat puede usar conectores NIO para aceptar conexiones y leer datos de red de forma no bloqueante, la ejecución del servlet ocurre siempre en un hilo worker del pool. Ese hilo queda retenido durante toda la duración de la petición, incluso si el servlet está esperando I/O o realizando una operación bloqueante. En otras palabras, el conector NIO mejora la eficiencia en la aceptación y lectura inicial, pero no libera el hilo worker mientras el servlet procesa.

Netty, por el contrario, está construido alrededor de event loops: cada `EventLoop` es un hilo que ejecuta un bucle selector, atendiendo eventos de I/O de múltiples canales (conexiones) registrados. Un solo event loop puede manejar miles de channels, ejecutando pequeñas tareas no bloqueantes para cada evento (lectura, escritura, conexión). No existe un hilo dedicado por conexión o por petición; el procesamiento se divide en handlers que se ejecutan dentro del event loop de forma asíncrona. Esto permite que un número reducido de hilos (a menudo igual al número de núcleos) soporte decenas de miles de conexiones concurrentes sin agotar la memoria ni saturar el scheduler del sistema operativo.

Reactor Netty lleva este modelo al extremo reactivo. Adapta Netty a Reactive Streams, exponiendo `HttpServer` y `HttpClient` que devuelven `Mono` y `Flux`. La integración con Project Reactor permite que los operadores reactivos se ejecuten sobre los mismos event loops de Netty, usando schedulers que comparten los hilos de I/O. Así, una petición puede ser manejada completamente sin bloquear ningún hilo: la lectura del cuerpo, la transformación, la llamada a otro servicio reactivo y la escritura de la respuesta se encadenan como una secuencia de señales sobre el event loop, con backpressure extremo a extremo. Tomcat, incluso en modo asíncrono, no alcanza este nivel de integración porque el modelo de servlets asíncronos sigue requiriendo que el hilo worker inicial se libere manualmente y la respuesta se complete desde otro hilo, lo que introduce complejidad y posibles puntos de bloqueo.

## Arquitectura interna, rendimiento y casos de uso

### Tomcat: conectores, pipeline y el rol del Executor

Tomcat organiza el procesamiento en tres capas: conector, contenedor (engine, host, context, wrapper) y la cadena de filtros/servlets. El conector es responsable de aceptar conexiones TCP, leer bytes HTTP y pasarlos al motor de procesamiento. Existen varios tipos de conectores: BIO (bloqueante, obsoleto), NIO (usa `java.nio.channels.Selector` para multiplexar conexiones), NIO2 (basado en canales asíncronos de Java 7) y APR (nativo, con OpenSSL). El conector NIO, el más común hoy, utiliza un `Poller` que ejecuta un event loop para detectar eventos de lectura en los sockets, pero cuando una petición está completa, la entrega a un `Executor` (thread pool) donde un hilo worker ejecutará la cadena de `Valve`, `Filter` y finalmente el `Servlet.service()`. Durante esa ejecución, el hilo worker puede bloquearse sin afectar al poller, pero el hilo queda ocupado hasta que el servlet termina. Esto significa que la escalabilidad sigue limitada por el tamaño del pool de hilos: si todas las peticiones son lentas (por ejemplo, esperan respuestas de servicios externos), el pool se agota y las nuevas conexiones quedan en cola o son rechazadas.

### Netty: event loops, pipelines y control de backpressure

Netty estructura la aplicación en `ChannelPipeline`, una cadena de `ChannelHandler` que procesan eventos de I/O y datos. El `EventLoopGroup` se divide típicamente en un grupo "boss" que acepta conexiones y las registra en un selector, y un grupo "worker" que ejecuta los event loops para los canales ya establecidos. Cada `EventLoop` es un `SingleThreadEventExecutor` que ejecuta tareas en su propio hilo; un mismo event loop puede atender miles de canales, iterando sobre el selector y despachando eventos de lectura/escritura a los handlers correspondientes. Los datos se representan mediante `ByteBuf`, buffers con pooling que minimizan la presión sobre el garbage collector.

El control de flujo es explícito: cuando un canal no puede escribir porque el buffer de salida del socket está lleno, Netty marca el canal como no escribible (`channel.isWritable()` retorna false). El handler debe dejar de escribir y reanudar cuando el canal vuelva a ser escribible. Además, el mecanismo de auto-read suspende la lectura de nuevos datos si el pipeline no puede procesarlos, evitando saturación. Esto constituye una forma de backpressure a nivel de transporte que Reactor Netty traduce a la demanda de Reactive Streams.

### Reactor Netty: la capa reactiva sobre Netty

Reactor Netty envuelve los canales de Netty en `HttpServerOperations` y `HttpClientOperations`, que implementan las interfaces de Reactive Streams. Un `HttpServer` configurado con un handler reactivo recibe cada petición como un `HttpServerRequest` y debe devolver un `Mono<Void>` que representa la finalización de la respuesta. Internamente, Reactor Netty asigna la ejecución de los operadores reactivos al event loop de Netty mediante el `Scheduler` de Reactor, evitando cambios de hilo innecesarios. La backpressure se propaga desde el consumidor hasta la capa de transporte: si el downstream solicita pocos elementos, Netty deja de leer del socket, reduciendo la presión en toda la cadena.

### Comparativa de rendimiento y escalabilidad

En escenarios de alta concurrencia con muchas conexiones inactivas o lentas, Netty supera ampliamente a Tomcat. Un solo event loop de Netty puede mantener 50.000 conexiones WebSocket abiertas consumiendo apenas unos megabytes de memoria, mientras que Tomcat necesitaría un hilo por conexión (o al menos un hilo por petición activa) con el consiguiente consumo de stacks y overhead de CPU. En throughput puro con peticiones cortas, la diferencia puede ser menor si Tomcat está bien configurado con NIO y un pool de hilos suficiente, pero Netty sigue mostrando mejor latencia en percentiles altos porque evita la contención de hilos y los cambios de contexto.

La memoria también es un factor: los `ByteBuf` pooled de Netty y la ausencia de stacks de hilos por conexión reducen la huella, algo crítico en contenedores con recursos limitados.

### Trade-offs: complejidad frente a simplicidad

Netty exige programación asíncrona y gestión manual de buffers. Un handler debe ser cuidadoso de no bloquear el event loop, liberar `ByteBuf` correctamente y manejar la backpressure. El ecosistema de servlets de Tomcat, en cambio, ofrece un modelo mental simple y lineal, con soporte maduro para seguridad declarativa, sesiones, JSP y una infinidad de librerías que asumen un hilo por petición. Para aplicaciones CRUD de concurrencia moderada, esta simplicidad reduce el tiempo de desarrollo y la probabilidad de errores sutiles de concurrencia.

### Casos de uso

Tomcat es la elección natural para aplicaciones web tradicionales, portales, servicios REST con Spring MVC y cargas de trabajo donde el número de usuarios simultáneos no supera unos pocos miles y las peticiones son de corta duración. Netty (directamente o a través de Reactor Netty) brilla en microservicios reactivos que necesitan máxima eficiencia de recursos, API gateways que enrutan tráfico a múltiples backends, proxies de alto rendimiento, servidores WebSocket que mantienen conexiones persistentes con miles de clientes, y cualquier sistema que implemente protocolos personalizados sobre TCP o UDP. Spring WebFlux sobre Reactor Netty combina la productividad de Spring con la escalabilidad de Netty, siendo la opción preferida para stacks completamente reactivos.

## Ejemplos de código

### Servidor Tomcat embebido con servlet bloqueante

Este ejemplo muestra un Tomcat embebido con conector NIO y un servlet que simula una operación bloqueante de 5 segundos. Aunque el conector usa NIO, el hilo worker queda retenido durante el sleep, evidenciando el modelo hilo-por-petición.

```java
import org.apache.catalina.LifecycleException;
import org.apache.catalina.startup.Tomcat;
import org.apache.catalina.Context;
import org.apache.catalina.connector.Connector;
import org.apache.coyote.http11.Http11NioProtocol;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;

public class TomcatBlockingExample {
    public static void main(String[] args) throws LifecycleException {
        Tomcat tomcat = new Tomcat();
        tomcat.setPort(8080);

        Connector connector = new Connector(Http11NioProtocol.class.getName());
        connector.setPort(8080);
        tomcat.setConnector(connector);

        Context ctx = tomcat.addContext("", null);
        tomcat.addServlet(ctx, "blockingServlet", new HttpServlet() {
            @Override
            protected void doGet(HttpServletRequest req, HttpServletResponse resp)
                    throws IOException {
                try {
                    // Simula operación bloqueante (DB, servicio externo)
                    Thread.sleep(5000);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                resp.setContentType("text/plain");
                resp.getWriter().write("OK después de 5s");
            }
        });
        ctx.addServletMappingDecoded("/", "blockingServlet");

        tomcat.start();
        System.out.println("Tomcat iniciado en http://localhost:8080/");
        tomcat.getServer().await();
    }
}
```

### Servidor Netty básico asíncrono

Un servidor Netty mínimo que responde "Hello World" de forma no bloqueante. El handler se ejecuta en el event loop y no retiene ningún hilo.

```java
import io.netty.bootstrap.ServerBootstrap;
import io.netty.channel.*;
import io.netty.channel.nio.NioEventLoopGroup;
import io.netty.channel.socket.SocketChannel;
import io.netty.channel.socket.nio.NioServerSocketChannel;
import io.netty.handler.codec.http.*;
import io.netty.buffer.Unpooled;
import io.netty.util.CharsetUtil;

public class NettyHelloWorld {
    public static void main(String[] args) throws InterruptedException {
        EventLoopGroup bossGroup = new NioEventLoopGroup(1);
        EventLoopGroup workerGroup = new NioEventLoopGroup();

        try {
            ServerBootstrap b = new ServerBootstrap();
            b.group(bossGroup, workerGroup)
             .channel(NioServerSocketChannel.class)
             .childHandler(new ChannelInitializer<SocketChannel>() {
                 @Override
                 protected void initChannel(SocketChannel ch) {
                     ch.pipeline()
                       .addLast(new HttpServerCodec())
                       .addLast(new HttpObjectAggregator(65536))
                       .addLast(new SimpleChannelInboundHandler<FullHttpRequest>() {
                           @Override
                           protected void channelRead0(ChannelHandlerContext ctx,
                                                       FullHttpRequest request) {
                               FullHttpResponse response = new DefaultFullHttpResponse(
                                   HttpVersion.HTTP_1_1,
                                   HttpResponseStatus.OK,
                                   Unpooled.copiedBuffer("Hello World", CharsetUtil.UTF_8)
                               );
                               response.headers().set(HttpHeaderNames.CONTENT_TYPE,
                                                      "text/plain; charset=UTF-8");
                               ctx.writeAndFlush(response)
                                  .addListener(ChannelFutureListener.CLOSE);
                           }
                       });
                 }
             });

            ChannelFuture f = b.bind(8080).sync();
            System.out.println("Netty server en http://localhost:8080/");
            f.channel().closeFuture().sync();
        } finally {
            workerGroup.shutdownGracefully();
            bossGroup.shutdownGracefully();
        }
    }
}
```

### Servidor Reactor Netty con respuesta retardada no bloqueante

Este servidor usa Reactor Netty para devolver un `Mono<String>` después de un retardo de 5 segundos con `Mono.delay`. El event loop no se bloquea: la suscripción programa la emisión en un scheduler paralelo y la respuesta se escribe cuando el Mono emite.

```java
import reactor.core.publisher.Mono;
import reactor.netty.DisposableServer;
import reactor.netty.http.server.HttpServer;
import java.time.Duration;

public class ReactorNettyDelayed {
    public static void main(String[] args) {
        DisposableServer server = HttpServer.create()
            .port(8080)
            .handle((request, response) ->
                Mono.delay(Duration.ofSeconds(5))
                    .then(response.status(200)
                                  .header("Content-Type", "text/plain")
                                  .sendString(Mono.just("OK después de 5s (no bloqueante)")))
            )
            .bindNow();

        System.out.println("Reactor Netty server en http://localhost:8080/");
        server.onDispose().block();
    }
}
```

### Comparativa de manejo de conexiones lentas

**Netty: escritura periódica sin hilos extra.** Un servidor que mantiene 10.000 conexiones abiertas y envía un mensaje cada 30 segundos usando el event loop. Solo requiere unos pocos hilos.

```java
import io.netty.bootstrap.ServerBootstrap;
import io.netty.channel.*;
import io.netty.channel.nio.NioEventLoopGroup;
import io.netty.channel.socket.SocketChannel;
import io.netty.channel.socket.nio.NioServerSocketChannel;
import io.netty.handler.codec.string.StringEncoder;
import io.netty.handler.codec.string.StringDecoder;
import io.netty.handler.timeout.IdleStateHandler;
import io.netty.handler.timeout.IdleStateEvent;
import io.netty.buffer.Unpooled;
import io.netty.util.CharsetUtil;
import java.util.concurrent.TimeUnit;

public class NettySlowConnections {
    public static void main(String[] args) throws InterruptedException {
        EventLoopGroup bossGroup = new NioEventLoopGroup(1);
        EventLoopGroup workerGroup = new NioEventLoopGroup(4); // pocos hilos

        try {
            ServerBootstrap b = new ServerBootstrap();
            b.group(bossGroup, workerGroup)
             .channel(NioServerSocketChannel.class)
             .childHandler(new ChannelInitializer<SocketChannel>() {
                 @Override
                 protected void initChannel(SocketChannel ch) {
                     ch.pipeline()
                       .addLast(new StringDecoder(CharsetUtil.UTF_8))
                       .addLast(new StringEncoder(CharsetUtil.UTF_8))
                       .addLast(new IdleStateHandler(0, 0, 30, TimeUnit.SECONDS))
                       .addLast(new ChannelInboundHandlerAdapter() {
                           @Override
                           public void userEventTriggered(ChannelHandlerContext ctx,
                                                          Object evt) {
                               if (evt instanceof IdleStateEvent) {
                                   // Envía un keep-alive cada 30s sin crear hilos
                                   ctx.writeAndFlush("ping\n");
                               }
                           }
                       });
                 }
             });

            ChannelFuture f = b.bind(8080).sync();
            System.out.println("Netty mantiene conexiones lentas en :8080");
            f.channel().closeFuture().sync();
        } finally {
            workerGroup.shutdownGracefully();
            bossGroup.shutdownGracefully();
        }
    }
}
```

**Tomcat: agotamiento del pool de hilos.** Un servlet que duerme 30 segundos por petición. Con un pool pequeño (10 hilos), 100 conexiones concurrentes saturarán el pool y las restantes serán rechazadas o quedarán en cola.

```java
import org.apache.catalina.LifecycleException;
import org.apache.catalina.startup.Tomcat;
import org.apache.catalina.Context;
import org.apache.catalina.connector.Connector;
import org.apache.coyote.http11.Http11NioProtocol;
import javax.servlet.http.HttpServlet;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.concurrent.Executor;
import java.util.concurrent.Executors;

public class TomcatThreadExhaustion {
    public static void main(String[] args) throws LifecycleException {
        Tomcat tomcat = new Tomcat();
        Connector connector = new Connector(Http11NioProtocol.class.getName());
        connector.setPort(8080);
        // Pool pequeño para demostrar agotamiento
        Executor executor = Executors.newFixedThreadPool(10);
        connector.getProtocolHandler().setExecutor(executor);
        tomcat.setConnector(connector);

        Context ctx = tomcat.addContext("", null);
        tomcat.addServlet(ctx, "slowServlet", new HttpServlet() {
            @Override
            protected void doGet(HttpServletRequest req, HttpServletResponse resp)
                    throws IOException {
                try {
                    Thread.sleep(30000); // operación lenta
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
                resp.getWriter().write("Hecho");
            }
        });
        ctx.addServletMappingDecoded("/", "slowServlet");

        tomcat.start();
        System.out.println("Tomcat con pool de 10 hilos en :8080");
        tomcat.getServer().await();
    }
}
```

## Trampas comunes

**Bloquear el event loop de Netty.** Ejecutar operaciones síncronas (consultas JDBC, llamadas HTTP bloqueantes, lectura de archivos) dentro de un `ChannelHandler` detiene el event loop, paralizando todas las conexiones asignadas a ese hilo. La solución es delegar el trabajo bloqueante a un `EventExecutorGroup` separado o usar librerías asíncronas (R2DBC, WebClient reactivo). En Reactor Netty, se debe usar `subscribeOn(Schedulers.boundedElastic())` para aislar el bloqueo.

**Configuración inadecuada del pool de hilos de Tomcat.** Un pool demasiado pequeño provoca rechazo de conexiones bajo carga; uno excesivo consume memoria y aumenta el overhead de cambio de contexto. Además, no habilitar el conector NIO (por defecto en versiones modernas, pero en configuraciones heredadas puede estar en BIO) limita la capacidad de aceptar conexiones de forma eficiente. El tamaño óptimo del pool depende de la latencia de las operaciones y del número de núcleos, pero rara vez debe superar unos cientos de hilos.

**Mezclar modelos bloqueantes y no bloqueantes.** En una aplicación reactiva desplegada sobre Tomcat, usar filtros que realicen I/O bloqueante (por ejemplo, autenticación contra LDAP síncrono) anula los beneficios de la asincronía, ya que el hilo worker se bloquea. En Reactor Netty, ejecutar una llamada bloqueante sin cambiar de scheduler bloquea el event loop, degradando el rendimiento de todas las conexiones. La regla es: si se adopta un stack reactivo, todas las capas deben ser no bloqueantes.

**Ignorar la backpressure.** En Netty, escribir en un canal sin verificar `channel.isWritable()` puede provocar que los buffers de salida crezcan sin control hasta un `OutOfMemoryError`. Es necesario suspender la escritura cuando el canal no está escribible y reanudarla en el callback `channelWritabilityChanged`. En Reactor Netty, no propagar la demanda (por ejemplo, usando `Flux.create` sin respetar las solicitudes del downstream) puede saturar al consumidor. La backpressure es un contrato fundamental de Reactive Streams que debe respetarse.

**Fugas de ByteBuf.** Netty usa buffers con contador de referencias. Si un handler retiene un `ByteBuf` más allá del pipeline (por ejemplo, almacenándolo en una colección) sin llamar a `retain()`, o no lo libera tras usarlo, se producen fugas de memoria difíciles de detectar. La práctica recomendada es usar `SimpleChannelInboundHandler`, que libera el mensaje automáticamente después de `channelRead0`, o liberar manualmente con `ReferenceCountUtil.release()` en handlers que no son `SimpleChannelInboundHandler`.

**Asumir que Netty siempre es superior.** Para aplicaciones CRUD con baja concurrencia, Tomcat ofrece un modelo de desarrollo más simple, depuración más directa y un ecosistema de librerías que asumen un hilo por petición. La complejidad adicional de Netty solo se justifica cuando los requisitos de escalabilidad o latencia lo exigen. Migrar a Netty sin necesidad real puede aumentar los costes de desarrollo y mantenimiento sin beneficios tangibles.

## Para saber más

- [Netty User Guide](https://netty.io/wiki/user-guide-for-4.x.html)
- [Apache Tomcat 9 Architecture](https://tomcat.apache.org/tomcat-9.0-doc/architecture/index.html)
- [Reactor Netty Reference Guide](https://projectreactor.io/docs/netty/release/reference/index.html)
- [Project Reactor Core Reference](https://projectreactor.io/docs/core/release/reference/)
- [Scalable I/O in Java (Doug Lea)](http://gee.cs.oswego.edu/dl/cpjslides/nio.pdf)