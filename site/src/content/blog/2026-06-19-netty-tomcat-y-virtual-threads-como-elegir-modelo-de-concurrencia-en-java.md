---
title: "Netty, Tomcat y virtual threads: cómo elegir modelo de concurrencia en Java"
description: "Netty ofrece control fino sobre I/O y máxima escalabilidad con código asíncrono, pero exige disciplina reactiva. Los virtual threads en Java 21 permiten escribir código síncrono que escala igual, compatibles con el ecosistema bloqueante, aunque con menor previsibilidad de latencia. Tomcat con virtual threads es la opción más productiva para servidores web típicos; Netty sigue siendo necesaria para protocolos personalizados o latencia extrema."
date: 2026-06-19
tags: ["java", "concurrency"]
summary: "Netty ofrece control fino sobre I/O y máxima escalabilidad con código asíncrono, pero exige disciplina reactiva. Los virtual threads en Java 21 permiten escribir código síncrono que escala igual, compatibles con el ecosistema bloqueante, aunque con menor previsibilidad de latencia. Tomcat con virtual threads es la opción más productiva para servidores web típicos; Netty sigue siendo necesaria para protocolos personalizados o latencia extrema."
issue: 28
requestedBy: "jlfernandezfernandez"
writer: "deepseek-v4-pro"
---

## El coste oculto del código síncrono

Durante años, el modelo natural para un servidor Java fue un hilo de plataforma por petición. El código es lineal, fácil de leer y depurar: aceptas una conexión, lees, procesas, escribes y cierras. Tomcat encarna este enfoque con un pool de hilos que reutiliza hilos del sistema operativo.

El problema aparece con la carga. Cada hilo de plataforma reserva del orden de 1 MB de stack y su cambio de contexto tiene un coste no trivial en la CPU. Un pool de 500 hilos puede manejar 500 peticiones concurrentes; para 10 000 necesitarías 10 000 hilos, y la memoria y el *throughput* se degradan. Esta limitación —el clásico problema C10k— empujó a la industria hacia la concurrencia no bloqueante.

## Netty: concurrencia sin bloqueos

Netty implementa un modelo *event loop* sobre I/O no bloqueante. Un grupo reducido de hilos (a menudo uno por núcleo) sondea canales registrados en un `Selector`. Cuando un canal tiene datos, el *event loop* ejecuta una cadena de `ChannelHandler` sin bloquearse jamás.

```java
EventLoopGroup bossGroup = new NioEventLoopGroup(1);
EventLoopGroup workerGroup = new NioEventLoopGroup();
try {
    ServerBootstrap b = new ServerBootstrap();
    b.group(bossGroup, workerGroup)
     .channel(NioServerSocketChannel.class)
     .childHandler(new ChannelInitializer<SocketChannel>() {
         @Override
         public void initChannel(SocketChannel ch) {
             ch.pipeline().addLast(new SimpleChannelInboundHandler<ByteBuf>() {
                 @Override
                 protected void channelRead0(ChannelHandlerContext ctx, ByteBuf msg) {
                     // Simular una operación costosa sin bloquear el event loop
                     ctx.executor().schedule(() -> {
                         ctx.writeAndFlush(msg.retain());
                     }, 50, TimeUnit.MILLISECONDS);
                 }
             });
         }
     });
    ChannelFuture f = b.bind(8080).sync();
    f.channel().closeFuture().sync();
} finally {
    bossGroup.shutdownGracefully();
    workerGroup.shutdownGracefully();
}
```

Cualquier bloqueo en el *event loop* —una llamada a `Thread.sleep`, una consulta JDBC síncrona— paraliza todos los canales asignados a ese hilo. La solución exige descomponer la lógica en *callbacks*, futuros o, en el ecosistema reactivo, operadores de Project Reactor o RxJava. El código se fragmenta, los *stack traces* pierden contexto y la depuración se vuelve más compleja. A cambio, Netty ofrece un control extremadamente fino sobre *buffers*, *backpressure* y protocolos, y puede sostener cientos de miles de conexiones con un puñado de hilos.

## Virtual threads: el regreso del bloqueo simple

Project Loom introduce en Java 21 los *virtual threads*, hilos ligeros gestionados por la JVM, no por el sistema operativo. Un *virtual thread* es un objeto que la JVM puede suspender y reanudar sobre un *carrier thread* del SO. Cuando un *virtual thread* se bloquea —en I/O, en `Thread.sleep` o en una llamada JDBC— la JVM libera el *carrier thread* para que ejecute otro *virtual thread*. El bloqueo no consume recursos del SO.

Esto permite escribir código síncrono tradicional que escala a millones de hilos virtuales. Un servidor con *virtual threads* mantiene la misma estructura secuencial de siempre:

```java
try (ServerSocket server = new ServerSocket(8080)) {
    ExecutorService executor = Executors.newVirtualThreadPerTaskExecutor();
    while (true) {
        Socket socket = server.accept();
        executor.submit(() -> {
            try (socket;
                 BufferedReader in = new BufferedReader(
                     new InputStreamReader(socket.getInputStream()));
                 PrintWriter out = new PrintWriter(socket.getOutputStream(), true)) {
                String line = in.readLine();
                // Operación bloqueante sin penalización real
                Thread.sleep(50);
                out.println(line);
            } catch (IOException | InterruptedException e) {
                // manejo de error
            }
        });
    }
}
```

El código es idéntico al que usarías con un pool de hilos de plataforma, pero cada tarea se ejecuta en un *virtual thread* distinto. Tomcat 10.1+ puede configurarse con un `VirtualThreadExecutor` para aplicar este modelo a servlets, sin cambiar una línea de lógica de negocio.

La ventaja decisiva no está solo en la escalabilidad, sino en la compatibilidad con el ecosistema bloqueante. JDBC, JMS, sistemas de ficheros y la mayoría de las librerías de infraestructura son síncronas. Con Netty, integrarlas obliga a usar pools de hilos separados y a coordinar el traspaso entre el mundo no bloqueante y el bloqueante. Con *virtual threads*, las usas directamente, sin fricción.

## Cómo elegir: simplicidad, control y ecosistema

La decisión ya no es entre código simple y escalabilidad, sino entre tres perfiles de concurrencia con compromisos distintos.

**Simplicidad y mantenibilidad.** Los *virtual threads* ganan por margen. El flujo de una petición es un método que se lee de principio a fin, con *stack traces* completos y depuración convencional. Netty exige disciplina asíncrona y herramientas específicas para trazar errores. El modelo tradicional con hilos de plataforma es igual de simple, pero no escala.

**Throughput y latencia.** En *throughput* puro, Netty puede arañar algo más de rendimiento porque elimina casi toda la sobrecarga de planificación de hilos. Los *virtual threads* introducen una capa de scheduling dentro de la JVM, pero en cargas de trabajo típicas de servidor la diferencia es pequeña y el cuello de botella suele estar en la lógica de negocio o en la I/O externa. En latencia de cola, Netty ofrece más previsibilidad porque el *event loop* no sufre los breves desalojos que puede provocar el *preemption* del scheduler de *virtual threads*. Para aplicaciones web donde una latencia de milisegundos extra es aceptable, los *virtual threads* son suficientes.

**Ecosistema y librerías.** Si tu aplicación depende de librerías bloqueantes —JDBC, HTTP clients síncronos, acceso a ficheros—, los *virtual threads* te permiten mantenerlas sin sacrificar escalabilidad. Netty requiere drivers no bloqueantes (R2DBC, WebClient) o puentes que añaden complejidad y puntos de contención. Si ya has invertido en un stack reactivo completo, Netty sigue siendo la opción natural.

**Control sobre I/O y protocolos.** Netty proporciona acceso directo a *buffers*, *pipeline* de codificación y *backpressure* a nivel de bytes. Si implementas un protocolo binario propio, un proxy de alto rendimiento o necesitas afinar la asignación de memoria, Netty es la herramienta adecuada. Los *virtual threads* abstraen estos detalles; son ideales para la semántica request-response de HTTP o gRPC, pero no para escenarios donde cada asignación de *buffer* importa.

**Madurez operacional.** Netty lleva más de una década en producción en sistemas de alto tráfico. Los *virtual threads* son estables en Java 21, y la integración con Tomcat está probada, pero el ecosistema de monitorización y perfilado aún está madurando. Para equipos que prefieren minimizar riesgos, esto puede inclinar la balanza temporalmente.

## La convergencia de los modelos

Los *virtual threads* desdibujan la frontera que separaba el código bloqueante del escalable. Para la mayoría de aplicaciones web y microservicios, Tomcat con *virtual threads* ofrece la combinación más productiva: código síncrono, depuración sencilla, plena compatibilidad con librerías bloqueantes y un *throughput* que compite con el reactivo. Netty conserva su lugar cuando el control exhaustivo de la I/O, la latencia extrema o un ecosistema no bloqueante ya establecido son requisitos de primer orden. El modelo tradicional de hilos de plataforma queda como una solución suficiente para cargas moderadas o sistemas que no justifican el cambio.
