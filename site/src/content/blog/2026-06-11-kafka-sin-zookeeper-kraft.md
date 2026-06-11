---
title: "Kafka sin ZooKeeper: KRaft"
description: "KRaft elimina la dependencia de ZooKeeper mediante un quorum Raft interno que almacena metadatos en un topic compactado, reduciendo el failover del controller a segundos y escalando a millones de particiones. Unifica la seguridad bajo los mecanismos nativos de Kafka y admite modos combinado y dedicado, pero exige dimensionar correctamente los controllers para evitar timeouts en el quorum."
date: 2026-06-11
tags: ["kraft", "kafka", "raft", "metadata", "controller"]
summary: "KRaft elimina la dependencia de ZooKeeper mediante un quorum Raft interno que almacena metadatos en un topic compactado, reduciendo el failover del controller a segundos y escalando a millones de particiones. Unifica la seguridad bajo los mecanismos nativos de Kafka y admite modos combinado y dedicado, pero exige dimensionar correctamente los controllers para evitar timeouts en el quorum."
issue: 4
requestedBy: "jlfernandezfernandez"
writer: "deepseek-v4-pro"
---

## El problema de la doble operación: ZooKeeper como dependencia externa

Durante más de una década, Apache Kafka dependió de Apache ZooKeeper para almacenar y coordinar los metadatos del clúster. ZooKeeper mantenía el registro de brokers activos, las configuraciones de topics, las asignaciones de particiones, el liderazgo de réplicas y, en versiones antiguas, los offsets de consumer groups. Esta arquitectura separaba el plano de datos (brokers que sirven mensajes) del plano de control (ZooKeeper + controller), y esa separación se convirtió en la principal fuente de complejidad operacional.

Operar un clúster de Kafka exigía desplegar, monitorizar y escalar dos sistemas distribuidos distintos con modelos de consistencia, protocolos de red y mecanismos de seguridad diferentes. ZooKeeper utiliza un protocolo de consenso propio (ZAB) y un modelo de sesiones con heartbeats que, en clústeres grandes, podía provocar falsos positivos y expulsiones de brokers. El failover del controller —el broker elegido por ZooKeeper para gestionar el estado del clúster— implicaba una recarga completa de metadatos desde ZooKeeper, lo que en clústeres con más de 200 000 particiones podía tardar decenas de segundos o incluso minutos, durante los cuales no se podían crear topics ni mover particiones.

Además, ZooKeeper imponía un límite práctico de escalabilidad. La recarga de metadatos durante un failover del controller crecía linealmente con el número de particiones, y la experiencia operativa mostraba que superar las ~200 000 particiones volvía el proceso frágil. La configuración de seguridad también era dual: ACLs de ZooKeeper por un lado y mecanismos SASL/TLS en Kafka por otro, lo que multiplicaba las posibilidades de error.

KRaft (Kafka Raft) se diseñó para eliminar esta dependencia externa, simplificar la operación, reducir los tiempos de failover a segundos y permitir clústeres con millones de particiones. La versión 3.3.1 de Kafka marcó la madurez productiva de KRaft, y la versión 4.0 eliminará por completo el modo ZooKeeper. Para cualquier equipo que opere Kafka hoy, entender KRaft no es opcional: es la base sobre la que se construirá el futuro del sistema.

## El quorum de consenso interno: cómo KRaft reemplaza a ZooKeeper

KRaft sustituye ZooKeeper por un grupo de consenso Raft que se ejecuta dentro del propio ecosistema Kafka. Un conjunto de nodos controller forman el quorum Raft; uno de ellos actúa como líder (controller activo) y los demás son seguidores que replican pasivamente el log de metadatos. Este log se almacena en un topic interno compactado llamado `__cluster_metadata`, particionado y replicado exclusivamente entre los controllers. Los brokers convencionales no participan en el quorum: obtienen los metadatos mediante un RPC específico (Metadata Fetch) desde el controller activo, comportándose como observadores del estado consensuado.

La arquitectura admite dos modos de despliegue. En modo combinado, un mismo proceso Kafka asume los roles de broker y controller, compartiendo recursos de CPU y red. En modo dedicado, los controllers se ejecutan en nodos independientes sin servir tráfico de datos. La elección depende del tamaño del clúster y de los requisitos de aislamiento: para clústeres pequeños o entornos de desarrollo, el modo combinado ahorra recursos; en producción con cientos de brokers y millones de particiones, los controllers dedicados evitan la contención que podría degradar el plano de control.

La seguridad se unifica bajo los mecanismos nativos de Kafka. Ya no hay ACLs de ZooKeeper que mantener: la autenticación y autorización entre controllers, y entre brokers y controllers, se configuran con SASL/SCRAM, mTLS o delegation tokens sobre listeners específicos. Esto reduce la superficie de ataque y simplifica la configuración, aunque exige definir listeners separados para el tráfico de controller y el tráfico de broker, cada uno con su propio protocolo de seguridad.

El controller activo escribe cada cambio de estado (creación de topics, reassignments, cambios de configuración) como un registro en el log Raft. Los seguidores replican esos registros y los aplican a su propia máquina de estados en memoria. Si el líder falla, un seguidor puede tomar el relevo inmediatamente porque ya posee una copia completa y actualizada de los metadatos, eliminando la ventana de inconsistencia que existía con ZooKeeper. Este diseño permite failover en segundos y escala a millones de particiones porque el nuevo líder no necesita reconstruir el estado desde cero: solo debe aplicar los registros que pudieran faltar desde la última snapshot.

## Internals, trade-offs y comparativas del consenso empotrado

Kafka implementa su propio protocolo Raft en lugar de usar bibliotecas externas como Apache Ratis. El log de metadatos es un topic compactado con un único líder de quorum. Cada entrada del log representa un evento de cambio de estado: creación de topic, actualización de configuración, cambio de ISR, etc. El controller activo aplica estos eventos a una máquina de estados en memoria que refleja el estado completo del clúster. Periódicamente, el controller genera snapshots que serializan el estado actual y permiten truncar el log, evitando un crecimiento ilimitado y acelerando la recuperación de nodos que se incorporan tarde.

El quorum Raft se configura con un conjunto fijo de voters identificados por `node.id`. Para tolerar F fallos, se necesitan 2F+1 voters. El protocolo garantiza que solo un líder puede escribir en el log, y que una entrada se considera comprometida cuando la mayoría del quorum la ha reconocido. La elección de líder utiliza timeouts aleatorios para evitar split-brain, y el líder envía heartbeats periódicos para mantener su autoridad.

Los trade-offs operacionales son significativos. La simplificación de eliminar ZooKeeper se paga con la necesidad de dimensionar y monitorizar un quorum de controllers. En modo combinado, un pico de tráfico de datos puede robar CPU al controller, provocando timeouts en el envío de heartbeats y desencadenando elecciones de líder espurias que degradan todo el clúster. Por eso, en entornos exigentes se recomiendan controllers dedicados con recursos garantizados. La seguridad unificada es más sencilla, pero la configuración de listeners con múltiples protocolos (SASL_PLAINTEXT para brokers, SASL_SSL para controllers) requiere atención al detalle. Algunas configuraciones dinámicas que en ZooKeeper se modificaban con `kafka-configs` aún requieren un rolling restart en KRaft, como ciertos parámetros de quotas a nivel de broker.

Comparado con el failover en ZooKeeper, donde el nuevo controller debía leer todos los metadatos desde ZooKeeper (operación O(particiones)), KRaft logra tiempos de failover de segundos independientemente del número de particiones, porque el seguidor ya tiene el estado en memoria. La escalabilidad de particiones salta de ~200k a varios millones, validado en pruebas de Confluent con clústeres de 2 millones de particiones. La migración desde ZooKeeper se realiza mediante un modo dual-write: los controllers KRaft se añaden al clúster ZooKeeper existente, se sincronizan los metadatos, y finalmente se corta la dependencia de ZooKeeper con un comando de transición. Este proceso está documentado en KIP-631 y permite migraciones sin downtime.

A diferencia de Apache Pulsar, que eliminó ZooKeeper delegando los metadatos en BookKeeper (otro sistema distribuido), Kafka optó por empotrar el consenso dentro del propio proceso Kafka. Esto evita introducir una nueva dependencia externa y permite que el protocolo Raft se beneficie de las mismas optimizaciones de red y seguridad que el resto de Kafka. La decisión refleja una filosofía de autosuficiencia: el sistema de mensajería debe gestionar su propio estado sin delegar en infraestructura externa.

## Configuración y operación práctica

### Clúster KRaft mínimo con Docker Compose

El siguiente ejemplo despliega tres nodos combinados (broker + controller) que forman un quorum de tres voters. Cada nodo necesita un `server.properties` con los roles, la lista de voters y los listeners adecuados. Antes de arrancar, se debe formatear el directorio de logs de metadatos con `kafka-storage format`.

`docker-compose.yml`:

```yaml
version: "3.8"
services:
  kafka1:
    image: confluentinc/cp-kafka:7.6.0
    hostname: kafka1
    container_name: kafka1
    ports:
      - "9092:9092"
      - "9093:9093"
    environment:
      KAFKA_NODE_ID: 1
      KAFKA_PROCESS_ROLES: "broker,controller"
      KAFKA_LISTENERS: "PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093"
      KAFKA_ADVERTISED_LISTENERS: "PLAINTEXT://localhost:9092"
      KAFKA_CONTROLLER_LISTENER_NAMES: "CONTROLLER"
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: "PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT"
      KAFKA_CONTROLLER_QUORUM_VOTERS: "1@kafka1:9093,2@kafka2:9095,3@kafka3:9097"
      KAFKA_LOG_DIRS: "/var/lib/kafka/data"
      KAFKA_METADATA_LOG_DIR: "/var/lib/kafka/data/metadata"
      CLUSTER_ID: "MkU3OEVBNTcwNTJENDM2Qk"
    volumes:
      - ./data/kafka1:/var/lib/kafka/data
    command: >
      bash -c "
        kafka-storage format --cluster-id=$${CLUSTER_ID} --config=/etc/kafka/kafka.properties --ignore-formatted &&
        /etc/confluent/docker/run
      "

  kafka2:
    image: confluentinc/cp-kafka:7.6.0
    hostname: kafka2
    container_name: kafka2
    ports:
      - "9094:9094"
      - "9095:9095"
    environment:
      KAFKA_NODE_ID: 2
      KAFKA_PROCESS_ROLES: "broker,controller"
      KAFKA_LISTENERS: "PLAINTEXT://0.0.0.0:9094,CONTROLLER://0.0.0.0:9095"
      KAFKA_ADVERTISED_LISTENERS: "PLAINTEXT://localhost:9094"
      KAFKA_CONTROLLER_LISTENER_NAMES: "CONTROLLER"
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: "PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT"
      KAFKA_CONTROLLER_QUORUM_VOTERS: "1@kafka1:9093,2@kafka2:9095,3@kafka3:9097"
      KAFKA_LOG_DIRS: "/var/lib/kafka/data"
      KAFKA_METADATA_LOG_DIR: "/var/lib/kafka/data/metadata"
      CLUSTER_ID: "MkU3OEVBNTcwNTJENDM2Qk"
    volumes:
      - ./data/kafka2:/var/lib/kafka/data
    command: >
      bash -c "
        kafka-storage format --cluster-id=$${CLUSTER_ID} --config=/etc/kafka/kafka.properties --ignore-formatted &&
        /etc/confluent/docker/run
      "

  kafka3:
    image: confluentinc/cp-kafka:7.6.0
    hostname: kafka3
    container_name: kafka3
    ports:
      - "9096:9096"
      - "9097:9097"
    environment:
      KAFKA_NODE_ID: 3
      KAFKA_PROCESS_ROLES: "broker,controller"
      KAFKA_LISTENERS: "PLAINTEXT://0.0.0.0:9096,CONTROLLER://0.0.0.0:9097"
      KAFKA_ADVERTISED_LISTENERS: "PLAINTEXT://localhost:9096"
      KAFKA_CONTROLLER_LISTENER_NAMES: "CONTROLLER"
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: "PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT"
      KAFKA_CONTROLLER_QUORUM_VOTERS: "1@kafka1:9093,2@kafka2:9095,3@kafka3:9097"
      KAFKA_LOG_DIRS: "/var/lib/kafka/data"
      KAFKA_METADATA_LOG_DIR: "/var/lib/kafka/data/metadata"
      CLUSTER_ID: "MkU3OEVBNTcwNTJENDM2Qk"
    volumes:
      - ./data/kafka3:/var/lib/kafka/data
    command: >
      bash -c "
        kafka-storage format --cluster-id=$${CLUSTER_ID} --config=/etc/kafka/kafka.properties --ignore-formatted &&
        /etc/confluent/docker/run
      "
```

La variable `KAFKA_CONTROLLER_QUORUM_VOTERS` debe ser idéntica en todos los nodos y contener la dirección y puerto del listener CONTROLLER de cada voter. En este ejemplo, kafka1 escucha en 9093, kafka2 en 9095 y kafka3 en 9097, por lo que la lista es `1@kafka1:9093,2@kafka2:9095,3@kafka3:9097`. Cada nodo usa esta misma cadena para saber cómo contactar a los demás miembros del quorum.

### Inspección y gestión del quorum con `kafka-metadata-quorum`

Una vez el clúster está en marcha, la herramienta `kafka-metadata-quorum` permite consultar el estado del quorum y realizar cambios como añadir o eliminar controllers. Se ejecuta desde cualquier nodo con acceso al quorum.

```bash
# Describir el estado actual del quorum
kafka-metadata-quorum --bootstrap-server localhost:9092 describe --status
```

Salida esperada:

```
NodeId  Host            Port  Status
1       kafka1          9093  Leader
2       kafka2          9095  Follower
3       kafka3          9097  Follower
LeaderEpoch: 5, HighWatermark: 142
```

Para añadir un nuevo controller (por ejemplo, nodo 4) sin detener el clúster, primero se arranca el nuevo nodo con su configuración y el directorio de metadatos formateado, y luego se ejecuta:

```bash
kafka-metadata-quorum --bootstrap-server localhost:9092 add-controller --node-id 4 --host kafka4 --port 9099
```

El comando añade el nuevo voter al quorum dinámico. El nuevo nodo comenzará a replicar el log y aparecerá en `describe --status` como Follower. Para eliminar un controller, se usa `remove-controller --node-id <id>`. Estas operaciones requieren que el quorum mantenga mayoría en todo momento; no se puede eliminar un nodo si eso rompe la mayoría.

### Transparencia para las aplicaciones cliente

Las aplicaciones que usan Kafka no necesitan cambios para funcionar con KRaft. El `AdminClient` sigue operando igual; internamente, el protocolo Metadata Fetch obtiene la información del controller activo. El siguiente ejemplo Java crea un topic y consulta el ID del controller, demostrando que la API es idéntica.

```java
import org.apache.kafka.clients.admin.AdminClient;
import org.apache.kafka.clients.admin.AdminClientConfig;
import org.apache.kafka.clients.admin.CreateTopicsResult;
import org.apache.kafka.clients.admin.DescribeClusterResult;
import org.apache.kafka.clients.admin.NewTopic;
import org.apache.kafka.common.KafkaFuture;
import org.apache.kafka.common.Node;

import java.util.Collections;
import java.util.Properties;
import java.util.concurrent.ExecutionException;

public class KRaftClientExample {
    public static void main(String[] args) throws ExecutionException, InterruptedException {
        Properties props = new Properties();
        props.put(AdminClientConfig.BOOTSTRAP_SERVERS_CONFIG, "localhost:9092");

        try (AdminClient admin = AdminClient.create(props)) {
            // Crear un topic de prueba
            NewTopic newTopic = new NewTopic("test-topic", 3, (short) 3);
            CreateTopicsResult createResult = admin.createTopics(Collections.singleton(newTopic));
            createResult.all().get();
            System.out.println("Topic creado exitosamente.");

            // Obtener información del clúster, incluido el controller
            DescribeClusterResult clusterResult = admin.describeCluster();
            KafkaFuture<Node> controllerFuture = clusterResult.controller();
            Node controller = controllerFuture.get();
            System.out.println("Controller ID: " + controller.id() +
                               ", host: " + controller.host() +
                               ", port: " + controller.port());
        }
    }
}
```

Este código compila con las dependencias estándar de Kafka Clients. La salida mostrará el nodo que actúa como controller activo, que en un clúster combinado será uno de los brokers.

### Configuración avanzada de seguridad en modo combinado

Cuando se requiere seguridad, cada listener debe declarar su protocolo y las credenciales correspondientes. El siguiente `server.properties` configura un nodo combinado con SSL tanto para el tráfico de broker como para el de controller, usando almacenes de claves separados.

```properties
# server.properties para nodo combinado con SSL
node.id=1
process.roles=broker,controller

# Listeners: BROKER para clientes, CONTROLLER para quorum
listeners=BROKER://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093
advertised.listeners=BROKER://kafka1.example.com:9092
controller.listener.names=CONTROLLER
inter.broker.listener.name=BROKER

# Mapeo de protocolos de seguridad
listener.security.protocol.map=BROKER:SSL,CONTROLLER:SSL

# Configuración SSL común
ssl.keystore.location=/etc/kafka/secrets/broker.keystore.jks
ssl.keystore.password=broker-keystore-pass
ssl.key.password=broker-key-pass
ssl.truststore.location=/etc/kafka/secrets/broker.truststore.jks
ssl.truststore.password=broker-truststore-pass
ssl.client.auth=required

# Para el listener CONTROLLER se pueden sobrescribir propiedades con prefijo
listener.name.controller.ssl.keystore.location=/etc/kafka/secrets/controller.keystore.jks
listener.name.controller.ssl.keystore.password=controller-keystore-pass
listener.name.controller.ssl.key.password=controller-key-pass
listener.name.controller.ssl.truststore.location=/etc/kafka/secrets/controller.truststore.jks
listener.name.controller.ssl.truststore.password=controller-truststore-pass

# Quorum voters con nombres de host y puerto del listener CONTROLLER
controller.quorum.voters=1@kafka1.example.com:9093,2@kafka2.example.com:9093,3@kafka3.example.com:9093

# Directorios de logs
log.dirs=/var/lib/kafka/data
metadata.log.dir=/var/lib/kafka/data/metadata
```

Las propiedades con prefijo `listener.name.controller.` permiten definir credenciales distintas para el tráfico entre controllers, lo que es una buena práctica de segmentación. El parámetro `ssl.client.auth=required` fuerza la autenticación mutua, aplicable a ambos listeners salvo que se sobrescriba.

## Errores frecuentes y cómo evitarlos

**Lista de voters inconsistente o insuficiente.** `controller.quorum.voters` debe ser idéntica en todos los nodos del quorum y contener al menos tres voters para tolerar un fallo. Un solo voter impide cualquier tolerancia a fallos; si ese nodo se pierde, el clúster queda indisponible. Los IDs deben coincidir con `node.id` y los hosts/puertos deben apuntar al listener CONTROLLER de cada nodo. Un error típico es usar `localhost` en lugar de nombres de host resolubles por todos los nodos, lo que rompe la comunicación entre controllers en entornos distribuidos.

**Mezcla incorrecta de configuraciones ZooKeeper y KRaft.** Durante una migración con dual-write, es obligatorio seguir el procedimiento documentado: primero añadir controllers KRaft al clúster ZooKeeper existente, sincronizar, y luego ejecutar el comando de transición. Si se arrancan nodos con `zookeeper.connect` y `process.roles=controller` simultáneamente sin pasar por el modo migración, se puede producir split-brain o pérdida de metadatos. Nunca se deben mezclar configuraciones de ambos modos en un mismo nodo fuera del proceso de migración controlado.

**Nodos combinados sin recursos suficientes.** En modo combinado, el proceso Kafka maneja tanto el tráfico de datos como la participación en el quorum Raft. Si la CPU o la red se saturan sirviendo peticiones de clientes, el controller puede sufrir timeouts en el envío de heartbeats, provocando elecciones de líder innecesarias. En clústeres con alta carga o muchas particiones, se deben usar controllers dedicados con recursos aislados (CPU pinning, red separada) para garantizar la estabilidad del plano de control.

**Configuración incorrecta de `controller.listener.names`.** Este parámetro debe coincidir exactamente con uno de los nombres definidos en `listeners`. Si se define como `CONTROLLER` pero en `listeners` el nombre es `CTRL`, los brokers no podrán obtener metadatos porque el controller no expone ese listener. Además, el protocolo de seguridad mapeado en `listener.security.protocol.map` para ese nombre debe ser coherente con la configuración de seguridad (por ejemplo, no declarar `SSL` y luego no proporcionar keystores).

**Olvidar el formateo inicial de metadatos.** Antes del primer arranque, cada nodo con rol `controller` debe ejecutar `kafka-storage format` con el `--cluster-id` correcto. Si se omite, el proceso Kafka se negará a iniciar con un error explícito. En entornos containerizados, es común scriptar este paso en el entrypoint, pero en despliegues manuales se olvida con frecuencia.

**Asumir que todas las configuraciones dinámicas funcionan igual.** En KRaft, algunas propiedades que en ZooKeeper se modificaban con `kafka-configs` sin reinicio ahora requieren un rolling restart. Por ejemplo, cambios en `advertised.listeners` o ciertos parámetros de quotas a nivel de broker. Es crucial consultar la documentación de cada versión para saber qué configuraciones son verdaderamente dinámicas en KRaft.

**No planificar la pérdida del quorum.** Si se pierde la mayoría de los controllers, el clúster entero queda indisponible porque no se puede elegir líder ni comprometer nuevas entradas en el log de metadatos. Es necesario monitorizar la salud del quorum (herramientas como `kafka-metadata-quorum describe --status` y métricas JMX de Raft) y conocer el procedimiento de recuperación: si un nodo falla permanentemente, se debe usar `remove-controller` para ajustar el quorum y luego añadir un reemplazo con `add-controller`, siempre manteniendo la mayoría durante la transición.

## Para saber más

- [Apache Kafka Documentation: KRaft](https://kafka.apache.org/documentation/#kraft)
- [KIP-500: Replace ZooKeeper with a Self-Managed Metadata Quorum](https://cwiki.apache.org/confluence/display/KAFKA/KIP-500%3A+Replace+ZooKeeper+with+a+Self-Managed+Metadata+Quorum)
- [KIP-631: The KRaft Controller Migration](https://cwiki.apache.org/confluence/display/KAFKA/KIP-631%3A+The+KRaft+Controller+Migration)
- [Confluent Blog: Apache Kafka Without ZooKeeper: The KRaft Era](https://www.confluent.io/blog/kafka-without-zookeeper-kraft-era/)
- [Confluent Blog: KRaft Performance and Scalability](https://www.confluent.io/blog/kraft-performance-and-scalability/)