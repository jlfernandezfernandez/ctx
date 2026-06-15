---
title: "De SPN a OBO: cómo cambiar de autenticación de servicio a delegada en Azure AD"
description: "Cuando un BFF autentica con SPN (client credentials) la API downstream no sabe quién es el usuario. El flujo On-Behalf-Of (OBO) permite al BFF actuar en nombre del usuario, pero cambia el JWT, los permisos y la configuración. Este artículo recorre ambos flujos desde cero, explica la terminología de Azure (appId, SPN, tenant, resource ID), compara los JWTs claim por claim, y muestra cómo migrar de uno a otro."
date: 2026-06-12
tags: ["auth", "azure"]
summary: "Cuando un BFF autentica con SPN (client credentials) la API downstream no sabe quién es el usuario. El flujo On-Behalf-Of (OBO) permite al BFF actuar en nombre del usuario, pero cambia el JWT, los permisos y la configuración. Este artículo recorre ambos flujos desde cero, explica la terminología de Azure, compara los JWTs claim por claim, y muestra cómo migrar de uno a otro."
issue: 19
requestedBy: "jlfernandezfernandez"
writer: "deepseek-v4-pro"
reviewer: "minimax-m3"
---

## El escenario: SPA, BFF y una API downstream

Tenéis un SPA en TypeScript que llama a un BFF (Python). El BFF, a su vez, llama a una API downstream —por ejemplo, Microsoft Graph, o vuestra propia API protegida por Azure AD.

Hoy el BFF se autentica con su propia identidad de servicio (SPN). El flujo funciona, pero la API downstream ve que la llama *el BFF*, no *el usuario*. Si Pedro pide ver su perfil, el BFF llama a Graph con su SPN, y Graph devuelve los datos de la aplicación, no los de Pedro.

Necesitáis que el BFF actúe en nombre del usuario: que la API downstream sepa que es Pedro quien pide, no el BFF. Eso cambia el flujo de autenticación de *client credentials* (SPN) a *On-Behalf-Of* (OBO).

Pero antes de compararlos, hay que entender qué significa cada nombre que aparece en el portal de Azure, porque la documentación usa términos como *appId*, *resourceId*, *SPN*, *service principal*, *enterprise application* y *tenant* como si fueran obvios —y no lo son.

## El diccionario de Azure que nadie te explica junto

Azure AD (ahora Microsoft Entra ID) usa varios nombres para cosas que se parecen pero no son lo mismo. La confusión empieza en el portal, donde una misma aplicación aparece en dos sitios distintos con nombres distintos.

### App Registration (application object)

Es la **definición global** de tu aplicación: su nombre, sus redirect URIs, los scopes que expone, los permisos que necesita, sus claves. Se crea en *App registrations* en el portal. Tiene un identificador público y estable: el **Application (client) ID**, también llamado **appId** o **client ID**. Este ID es el que se envía como `client_id` en OAuth. No es un secreto.

Una app registration existe en un *tenant origen* (el tenant donde la creaste). Si otra organización quiere usar tu aplicación, la instala en su tenant —y ahí aparece el service principal.

### Service Principal (Enterprise Application)

Es la **instancia local** de una aplicación dentro de un tenant. Piensa en ello como la app registration *puesta en marcha* en un directorio concreto. El service principal es donde se almacenan:

- Los permisos consentidos (delegados y de aplicación)
- Las asignaciones de usuarios y grupos
- La configuración de acceso condicional

En el portal, el service principal aparece en *Enterprise applications*. Tiene su propio **Object ID** (distinto del appId) que lo identifica dentro del tenant.

La relación es así de simple:

| Concepto | Dónde está en el portal | Qué almacena | Identificador |
|---|---|---|---|
| App Registration | *App registrations* | Definición global de la app: scopes, redirect URIs, secretos | **appId** (Application client ID) |
| Service Principal | *Enterprise applications* | Permisos consentidos, asignaciones, config local en este tenant | **Object ID** |

Una misma app registration puede tener service principals en muchos tenants (multi-tenant). El appId es el mismo en todos los tenants. El Object ID del service principal es distinto en cada uno.

### Terminología común y su traducción

| Lo que lees en docs o en el portal | Qué es realmente |
|---|---|
| **appId** / **client ID** / **Application (client) ID** | El identificador público de la app registration. Se pasa como `client_id` en OAuth. |
| **Object ID** (en App registrations) | Identifica el application object dentro de su tenant origen. No lo uses como `client_id`. |
| **Object ID** (en Enterprise applications) | Identifica el service principal dentro del tenant. Tampoco lo uses como `client_id`. |
| **resource ID** / **resource** | En el contexto de OAuth, el `aud` del token: la aplicación que recibe el token. Se expresa como su appId o como un URI (`api://mi-bff/access_as_user`). |
| **SPN** / **service principal name** | A veces se usa como sinónimo de service principal, a veces como el nombre alternativo (URI) del service principal. En la práctica, cuando alguien dice "autenticar con SPN" se refiere a *client credentials*: la app se autentica con su propia identidad, sin usuario. |
| **Tenant ID** / **Directory ID** | El identificador del directorio (organización) de Azure AD. Se pasa como parte de la authority en OAuth (`https://login.microsoftonline.com/{tenantId}`). |
| **Client secret** / **Client certificate** | Credencial que demuestra que el llamante es realmente la aplicación identificada por el `client_id`. Es el equivalente a una contraseña de app. **Debe protegerse.** |
| **Managed Identity** | Identidad asignada automáticamente por Azure a un recurso (App Service, VM, etc.). Evita tener que gestionar secrets. Se usa como client credentials sin secret en el código. |

### Una metáfora para acordarse

- **App Registration** es el **plano** de un edificio: define qué hay, pero es papel.
- **Service Principal** es el **edificio construido** en una ciudad concreta: tiene llaves asignadas, inquilinos, permisos.
- **appId** es el **DNI del plano**: único, público, el mismo en todas las ciudades.
- **Object ID (SP)** es la **dirección del edificio en esta ciudad**: distinta en cada una.
- **Client Secret** es la **llave de la puerta principal**: privada, rotable, demuestra que eres el edificio.

## Client Credentials: cuando el BFF habla con su propia identidad

El flujo *client credentials* (OAuth 2.0) es el más simple: la aplicación se autentica con su `client_id` y `client_secret` (o certificado), sin ningún usuario. Azure AD devuelve un token donde la identidad es la de la aplicación, no la de ninguna persona.

### Flujo paso a paso

1. El BFF necesita llamar a la API downstream. No hay usuario en este flujo.
2. El BFF envía una petición al endpoint `/token` de Azure AD con `grant_type=client_credentials`, su `client_id`, su `client_secret`, y el `scope` (o `resource`) de la API que quiere llamar.
3. Azure AD verifica que la aplicación (identificada por `client_id`) existe, que el secret es correcto, y que tiene permisos de aplicación sobre el recurso solicitado.
4. Azure AD emite un access token. El `sub` del token es el `appId` de la aplicación. El `aud` es el resourceId de la API downstream.
5. El BFF usa el token en el header `Authorization: Bearer <token>` para llamar a la API.
6. La API downstream valida el token (firma, emisor, audience, expiración) y ve que la llamada viene de la aplicación BFF.

### El JWT de Client Credentials

Un token de client credentials decodificado se ve así:

```json
{
  "aud": "api://mi-api-downstream",
  "iss": "https://login.microsoftonline.com/{tenantId}/v2.0",
  "sub": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "appid": "bff-client-id-aaaa-bbbb-cccc",
  "idtyp": "app",
  "roles": ["Api.Read", "Api.Write"],
  "tid": "{tenantId}",
  "iat": 1718146800,
  "exp": 1718150400
}
```

Claims clave:

| Claim | Qué significa | Nota |
|---|---|---|
| `sub` | Identifica *quién* hace la petición | En client credentials, es igual al `appid`. Es la aplicación, no un usuario. |
| `aud` | Para quién se emitió el token | El appId o scope URI de la API downstream. |
| `appid` | El appId de la aplicación que pidió el token | El BFF en este caso. |
| `idtyp` | Tipo de identidad del token | `"app"` significa que es una aplicación, no un usuario. |
| `roles` | Permisos de aplicación concedidos al BFF sobre la API | Se configuran como *Application Permissions* en Azure. |
| `tid` | Tenant del que se emitió el token | Útil en escenarios multi-tenant. |

**Lo que NO tiene este JWT**: `oid`, `upn`, `name`, `scp`, `azp`. No hay usuario. No hay identidad de persona. No hay scopes delegados.

### Configuración en Azure

1. Crear una app registration para el BFF.
2. En *API Permissions*, añadir *Application Permissions* sobre la API downstream (por ejemplo, `Api.Read`).
3. Un administrador debe conceder consentimiento (admin consent), porque los permisos de aplicación siempre requieren aprobación.
4. Generar un client secret (o subir un certificado) en *Certificates & secrets*.
5. El BFF usa `client_id` + `client_secret` para pedir el token.

## El problema: SPN no impersona

El BFF con client credentials funciona perfectamente para operaciones donde no importa **quién** hace la petición, solo **que** la aplicación autorizada la hace. Ejemplos:

- Un job nocturno que sincroniza datos
- Un servicio que envía notificaciones
- Una API que lee configuración compartida

Pero falla cuando la API downstream necesita saber **quién es el usuario**:

- "Devuélveme el perfil de Pedro" → Graph devuelve el perfil de la aplicación, no de Pedro
- "¿Tiene este usuario permiso para ver este recurso?" → No hay usuario en el token
- "Registra en auditoría qué usuario accedió" → Solo puedes registrar el appId del BFF

El BFF con SPN es como un mensajero que va al banco con su propio DNI: el banco atiende al mensajero, pero no sabe en nombre de quién va. Lo que necesitamos es que el mensajero lleve una autorización firmada de Pedro: el flujo On-Behalf-Of.

## On-Behalf-Of: cuando el BFF habla en nombre del usuario

El flujo On-Behalf-Of (OBO) es el mecanismo de Azure AD para que una API intermedia (el BFF) reciba un token del usuario y lo intercambie por otro token dirigido a una API downstream, manteniendo la identidad del usuario.

### Flujo paso a paso

1. El usuario se autentica en el SPA (typicamente con authorization code flow + PKCE). El SPA obtiene un access token dirigido al BFF (`aud: api://mi-bff/access_as_user`).
2. El SPA llama al BFF con ese token en `Authorization: Bearer <token>`.
3. El BFF valida el token entrante (firma, audience, expiración).
4. El BFF envía una petición al endpoint `/token` de Azure AD con:
   - `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer` (el tipo OBO)
   - `assertion=<token entrante>` (el access token del usuario)
   - `client_id=<appId del BFF>` + `client_secret=<secreto del BFF>`
   - `scope=<scopes de la API downstream>` (por ejemplo, `https://graph.microsoft.com/User.Read`)
   - `requested_token_use=on_behalf_of`
5. Azure AD verifica: el token entrante es válido, el BFF tiene permisos delegados sobre la API downstream, y el usuario consintió esos permisos.
6. Azure AD emite un nuevo access token dirigido a la API downstream (`aud: https://graph.microsoft.com` o `api://mi-api-downstream`), que contiene la identidad del usuario original.
7. El BFF usa este nuevo token para llamar a la API downstream.
8. La API downstream valida el token y ve tanto la identidad del usuario (`oid`, `upn`) como la del BFF (`azp`).

### El JWT de On-Behalf-Of

Un token obtenido vía OBO, decodificado:

```json
{
  "aud": "https://graph.microsoft.com",
  "iss": "https://login.microsoftonline.com/{tenantId}/v2.0",
  "sub": "x9y8z7w6-v5u4-t3s2-r1q0-ponmlkjihgfe",
  "oid": "pedro-user-id-1111-2222-3333",
  "upn": "pedro@midominio.com",
  "name": "Pedro García",
  "appid": "bff-client-id-aaaa-bbbb-cccc",
  "azp": "spa-client-id-dddd-eeee-ffff",
  "scp": "User.Read",
  "tid": "{tenantId}",
  "iat": 1718146800,
  "exp": 1718150400
}
```

Claims clave:

| Claim | Qué significa | Nota |
|---|---|---|
| `sub` | Identifica *quién* hace la petición | En OBO, es un hash derivado del `oid` del usuario y el `tid`. Es distinto al `sub` del token de client credentials. |
| `aud` | Para quién se emitió el token | La API downstream (Graph, vuestra API). |
| `oid` | Object ID del usuario en Azure AD | Identifica unívocamente al usuario en este tenant. Es la claim que usar para autorización. |
| `upn` | User Principal Name | El email del usuario. Útil para display y logging. |
| `name` | Nombre del usuario | Display name del usuario en Azure AD. |
| `appid` | El appId de la aplicación que pidió el token (el BFF) | Es el intermediario que hizo la petición OBO. |
| `azp` | El appId de la aplicación original (el SPA) | Identifica quién inició la cadena de autenticación. |
| `scp` | Scopes delegados consentidos | Los permisos específicos concedidos. Solo existen en tokens delegados. |
| `idtyp` | Tipo de identidad | En tokens OBO no aparece siempre, pero si aparece es `"user"`. |

**Lo que SÍ tiene este JWT y el de SPN no tiene**: `oid`, `upn`, `name`, `scp`. La identidad del usuario está presente.

### Configuración en Azure

1. Crear app registrations para el SPA y el BFF.
2. En la app registration del BFF, exponer un scope (`api://mi-bff/access_as_user`). El SPA solicitará este scope.
3. En la app registration del BFF, añadir **Delegated Permissions** sobre la API downstream (por ejemplo, `User.Read` de Microsoft Graph).
4. En la app registration del SPA, añadir el scope del BFF (`api://mi-bff/access_as_user`) como permiso delegado.
5. Consentimiento: el usuario (o un administrador) debe consentir los permisos delegados. En la app registration del BFF, se puede configurar `knownClientApplications` para que el consentimiento sea en cascada: al consentir el SPA, se consienten automáticamente los permisos del BFF sobre la API downstream.

## Anatomía comparativa: JWT de SPN vs JWT de OBO

La diferencia fundamental se ve decodificando ambos tokens. Aquí están lado a lado:

### Claims que aparecen en ambos

| Claim | Client Credentials (SPN) | On-Behalf-Of (delegado) | Qué cambia |
|---|---|---|---|
| `aud` | `api://mi-api-downstream` | `https://graph.microsoft.com` | El audience cambia porque cada token está dirigido a un recurso distinto. En una cadena OBO, el primer token tiene `aud: api://mi-bff`, el segundo `aud: api://mi-api-downstream`. |
| `iss` | `https://login.microsoftonline.com/{tenantId}/v2.0` | Igual | El issuer siempre es Azure AD. |
| `sub` | Igual al `appid` del BFF | Hash derivado del `oid` del usuario y `tid` | `sub` es diferente en cada flujo y por cada par (usuario, aplicación). No uses `sub` para identificar de forma estable; usa `oid`. |
| `tid` | Tenant ID | Igual | El tenant es el mismo. |
| `iat` / `exp` | Timestamps | Igual | Validez típica de 1 hora. |

### Claims exclusivos de cada flujo

| Claim | Client Credentials (SPN) | On-Behalf-Of (delegado) |
|---|---|---|
| `idtyp` | `"app"` | Ausente o `"user"` |
| `roles` | Presente (ej: `["Api.Read"]`) | Ausente |
| `scp` | Ausente | Presente (ej: `"User.Read"`) |
| `oid` | Ausente | Presente (ej: `"pedro-user-id-1111..."`) |
| `upn` | Ausente | Presente (ej: `"pedro@midominio.com"`) |
| `name` | Ausente | Presente (ej: `"Pedro García"`) |
| `appid` | Presente (BFF) | Presente (BFF, el intermediario OBO) |
| `azp` | Ausente | Presente (SPA, la aplicación original) |

### Cómo saber de un vistazo qué tipo de token tienes

1. Mira `idtyp`: si es `"app"`, es client credentials. Si no está o es `"user"`, es delegado.
2. Mira `scp` vs `roles`: scopes delegados (`scp`) = usuario presente. roles de aplicación (`roles`) =Sin usuario.
3. Mira `oid`: si está, hay un usuario. Si no, es una aplicación actuando sola.

### La claim que causa más confusión: `sub`

En client credentials, `sub` es igual a `appid` (la aplicación). En OBO, `sub` es un hash distinto para cada par (usuario, aplicación). Esto significa que el mismo usuario que llama a dos APIs distintas tendrá dos `sub` diferentes. Si necesitas identificar al usuario de forma estable entre APIs, usa `oid`, no `sub`.

### Otra confusión común: `appid` vs `azp`

En un token OBO, hay dos claims de aplicación:

- `appid`: la aplicación que hizo la petición al endpoint `/token`. En OBO, es el BFF (el intermediario).
- `azp`: la aplicación original que inició el flujo de autenticación. En OBO, es el SPA.

Si el SPA obtiene el token directamente (sin BFF), `appid` y `azp` son iguales. Solo cuando hay un intermediario OBO se diferencian.

## Consentimiento y configuración: de SPN a OBO sin morir en el intento

Migrar de client credentials a OBO implica cambios en tres sitios: la app registration del BFF, la app registration del SPA, y el consentimiento.

### Qué cambiar en la app registration del BFF

1. **Permisos**: quitar *Application Permissions* y añadir *Delegated Permissions* sobre la API downstream. Por ejemplo, quitar `Application.Read.All` y añadir `User.Read delegated`.
2. **Exponer un scope**: en *Expose an API*, crear un scope como `api://mi-bff/access_as_user`. Este es el scope que el SPA solicitará para obtener el token dirigido al BFF.
3. **`knownClientApplications`**: en el manifiesto de la app registration del BFF (o de la API downstream), listar el appId del SPA. Esto permite consentimiento en cascada: cuando el usuario consiente al SPA, automáticamente consiente los permisos que el BFF necesita sobre la API downstream.

### Qué cambiar en la app registration del SPA

1. **Permisos delegados**: añadir el scope del BFF (`api://mi-bff/access_as_user`) como permiso delegado.
2. Sin este permiso, el SPA no puede obtener un token con `aud: api://mi-bff`.

### Consentimiento

Los permisos delegados pueden requerir consentimiento de usuario o de administrador, dependiendo del permiso:

- **Permisos de bajo impacto** (por ejemplo, `User.Read`): el usuario puede consentir la primera vez que se autentica.
- **Permisos de alto impacto** (por ejemplo, `Mail.Read`): requieren consentimiento de administrador.

Si falta el consentimiento, la llamada OBO devuelve el error **AADSTS65001**. La resolución es consentir los permisos, ya sea mediante el flujo interactivo del SPA o a través del endpoint de consentimiento de administrador (`/adminconsent`).

### El error más común al migrar

El error **AADSTS50013** (Assertion failed signature validation) suele aparecer cuando el BFF intenta usar un token que no está dirigido a él como assertion. Recuerda: el BFF solo puede intercambiar un token cuyo `aud` es el propio BFF (`api://mi-bff/access_as_user`). Si intentas usar un token con `aud: https://graph.microsoft.com` como assertion, Azure AD lo rechazará.

## Ejemplo mínimo: SPA (TypeScript) + BFF (Python)

Esto es lo mínimo para ver el flujo completo. Sin Redis, sin caché, sin setup extenso. Solo el camino crítico.

### SPA: obtener el token para el BFF

```typescript
import { PublicClientApplication } from "@azure/msal-browser";

const msal = new PublicClientApplication({
  auth: {
    clientId: "spa-client-id",
    authority: "https://login.microsoftonline.com/{tenantId}",
  },
});

// Tras login interactivo:
const result = await msal.acquireTokenSilent({
  scopes: ["api://mi-bff/access_as_user"],
});

// result.accessToken tiene aud = api://mi-bff
// Se envía al BFF en Authorization: Bearer <token>
```

### BFF: intercambiar el token por otro para la API downstream

```python
import msal
import httpx

app = msal.ConfidentialClientApplication(
    client_id="bff-client-id",
    client_credential="bff-client-secret",
    authority="https://login.microsoftonline.com/{tenantId}",
)

def call_downstream(incoming_token: str):
    # OBO: intercambiar el token del usuario por otro para la API downstream
    result = app.acquire_token_on_behalf_of(
        user_assertion=incoming_token,
        scopes=["https://graph.microsoft.com/User.Read"],
    )
    if "error" in result:
        raise Exception(result["error_description"])

    downstream_token = result["access_token"]

    # Llamar a la API downstream con el nuevo token
    response = httpx.get(
        "https://graph.microsoft.com/v1.0/me",
        headers={"Authorization": f"Bearer {downstream_token}"},
    )
    return response.json()

# En el endpoint del BFF:
# incoming_token = request.headers["Authorization"].removeprefix("Bearer ")
# profile = call_downstream(incoming_token)
```

### Qué cambia respecto al flujo SPN

En client credentials, el BFF haría:

```python
# SPN: obtener token con su propia identidad, sin usuario
result = app.acquire_token_for_client(scopes=["api://mi-api-downstream/.default"])
# Este token tiene idtyp=app, roles, sin oid/upn/scp
```

En OBO, el BFF intercambia el token del usuario:

```python
# OBO: intercambiar el token del usuario por otro para la API downstream
result = app.acquire_token_on_behalf_of(
    user_assertion=incoming_token,
    scopes=["https://graph.microsoft.com/User.Read"],
)
# Este token tiene oid, upn, scp, azp — identidad del usuario
```

La diferencia esentral: `acquire_token_for_client` (SPN) vs `acquire_token_on_behalf_of` (OBO). El primero no necesita token entrante. El segundo lo requiere como `user_assertion`.

## Cuándo usar cada flujo

| Criterio | Client Credentials (SPN) | On-Behalf-Of (delegado) |
|---|---|---|
| ¿Hay usuario? | No | Sí, el usuario original |
| ¿La API downstream necesita saber quién es el usuario? | No | Sí |
| Tipo de permisos | Application Permissions | Delegated Permissions |
| Consentimiento | Solo admin | Admin o usuario |
| Token contiene | `roles`, `idtyp=app` | `scp`, `oid`, `upn`, `azp` |
| Caso de uso típico | Jobs, daemons, servicios de background | APIs que actúan en nombre de un usuario |
| Configuración | app registration + secret + app permissions | app registration + secret + delegated permissions + scope expuesto + consentimiento |

**La regla práctica**: si la API downstream necesita responder "¿quién es este usuario?" o actuar con los permisos de un usuario concreto, usa OBO. Si solo necesita verificar "¿tiene esta aplicación permiso para hacer esto?", usa client credentials. Y si hoy usáis SPN pero necesitáis impersonar al usuario, la migración consiste en cambiar Application Permissions por Delegated Permissions, exponer un scope en el BFF, y usar `acquire_token_on_behalf_of` en lugar de `acquire_token_for_client`.

## Referencias

- [Microsoft Identity Platform y OAuth 2.0 On-Behalf-Of flow](https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-oauth2-on-behalf-of-flow)
- [Microsoft Identity Platform y OAuth 2.0 Client Credentials flow](https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-oauth2-client-creds-grant-flow)
- [Application and service principal objects in Microsoft Entra ID](https://learn.microsoft.com/en-us/azure/active-directory/develop/app-objects-and-service-principals)
- [MSAL.NET documentation](https://learn.microsoft.com/en-us/azure/active-directory/develop/msal-net-overview)
- [MSAL Python documentation](https://learn.microsoft.com/en-us/azure/active-directory/develop/msal-python)
- [jwt.ms para decodificar tokens](https://jwt.ms)