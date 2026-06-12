---
title: "Autenticación delegada con MSAL: flujo On-Behalf-Of"
description: "El flujo On-Behalf-Of (OBO) permite a una API intermedia actuar en nombre del usuario original para llamar a una API descendente, intercambiando un token de acceso entrante por uno nuevo dirigido al recurso destino. Se implementa con MSAL usando el token como aserción, requiere permisos delegados y consentimiento, y exige estrategias de caché distribuida y validación estricta para evitar riesgos de seguridad."
date: 2026-06-12
tags: ["agents"]
summary: "El flujo On-Behalf-Of (OBO) permite a una API intermedia actuar en nombre del usuario original para llamar a una API descendente, intercambiando un token de acceso entrante por uno nuevo dirigido al recurso destino. Se implementa con MSAL usando el token como aserción, requiere permisos delegados y consentimiento, y exige estrategias de caché distribuida y validación estricta para evitar riesgos de seguridad."
issue: 19
requestedBy: "jlfernandezfernandez"
writer: "deepseek-v4-pro"
reviewer: "minimax-m3"
---

## El problema de la identidad en cadenas de APIs

En una arquitectura de microservicios o en aplicaciones con múltiples capas, es frecuente que una API intermedia necesite actuar en nombre del usuario original para llamar a otra API descendente. El escenario típico es:

1. Un cliente (SPA, aplicación móvil, daemon) se autentica y obtiene un token de acceso para la **API intermedia**.
2. La API intermedia recibe la petición, valida el token y necesita, a su vez, llamar a una **API descendente** (por ejemplo, Microsoft Graph, otra API interna o un servicio de terceros) con la identidad del usuario original.

Pasar el token recibido directamente a la API descendente no funciona: el token está emitido para la API intermedia (su audiencia es esa API), no para la descendente. La API descendente lo rechazaría porque la audiencia (`aud`) no coincide con su identificador. Además, el token podría contener scopes que solo son válidos para la API intermedia.

Reemitir el token con la identidad del usuario pero dirigido a otro recurso requiere un mecanismo de delegación controlada. En el ecosistema de Microsoft Identity Platform, ese mecanismo es el flujo **On-Behalf-Of (OBO)**, definido en la especificación OAuth 2.0 Token Exchange (RFC 8693) y soportado por MSAL (Microsoft Authentication Library) y Azure AD.

## Fundamentos de delegación en Microsoft Identity Platform

### Permisos delegados vs. permisos de aplicación

Antes de implementar OBO, hay que entender los dos tipos de permisos que una aplicación puede solicitar a Azure AD:

- **Permisos delegados**: la aplicación actúa en nombre de un usuario autenticado. El consentimiento puede ser otorgado por el propio usuario (si el permiso no requiere administrador) o por un administrador. El token de acceso contiene scopes (scp) que reflejan los permisos delegados concedidos. La audiencia (`aud`) es la API que expone los scopes.
- **Permisos de aplicación**: la aplicación actúa con su propia identidad, sin usuario presente. Requiere consentimiento del administrador. El token de acceso contiene roles (`roles`) en lugar de scopes. La audiencia es la API destino.

En el flujo OBO, la API intermedia usa un token de acceso delegado (recibido del cliente) para solicitar otro token delegado hacia la API descendente. Por tanto, la API intermedia debe tener permisos delegados sobre la API descendente, y el usuario original debe haber consentido esos permisos (directa o indirectamente).

### El rol de la API intermedia como cliente confidencial

La API intermedia actúa como **cliente confidencial** en el flujo OBO. Para canjear el token entrante por uno nuevo, debe autenticarse frente a Azure AD usando su propio secreto de cliente (contraseña o certificado). Esto es necesario porque el flujo OBO es un intercambio de tokens que requiere que el llamante (la API intermedia) demuestre su identidad.

### Propagación de identidad

El token de acceso emitido para la API descendente contiene claims que identifican al usuario original: `sub`, `oid`, `upn`, `tid`, entre otros. De esta forma, la API descendente puede aplicar autorización basada en el usuario real, aunque la llamada provenga de la API intermedia. La claim `azp` identifica al cliente original (la aplicación que inició la cadena), mientras que `aud` identifica al destinatario inmediato (la API intermedia o descendente, según el tramo).

## Anatomía del flujo On-Behalf-Of

El flujo OBO consta de los siguientes pasos:

1. El cliente obtiene un token de acceso para la API intermedia (recurso A), usando el flujo que corresponda (authorization code, device code, etc.). El token contiene scopes para A y aud = A.
2. El cliente llama a la API intermedia incluyendo el token en el header `Authorization: Bearer <token>`.
3. La API intermedia valida el token entrante (emisor, audiencia, firma, expiración, etc.).
4. La API intermedia construye una aserción (`assertion`) a partir del token entrante (normalmente el `access_token` recibido) y solicita un nuevo token para la API descendente (recurso B) al endpoint `/token` de Azure AD, autenticándose con sus propias credenciales de cliente confidencial.
5. Azure AD valida la aserción, verifica que la API intermedia tiene permisos delegados sobre B y que el usuario consintió esos permisos, y emite un nuevo token de acceso dirigido a B, junto con un refresh token opcional.
6. La API intermedia usa el nuevo token para llamar a la API descendente.

MSAL abstrae este proceso mediante el método `AcquireTokenOnBehalfOf` (MSAL.NET) o `acquire_token_on_behalf_of` (MSAL Python). Internamente, MSAL construye la aserción con el token entrante y el tipo de aserción `urn:ietf:params:oauth:grant-type:jwt-bearer`, y realiza la petición al endpoint `/token`.

### OBO con token de acceso vs. con refresh token

El flujo estándar usa el `access_token` entrante como aserción. Sin embargo, Azure AD también admite un flujo OBO en el que la API intermedia recibe un refresh token del cliente (en lugar del access token) y lo usa para solicitar tokens descendentes. Esto es menos común y requiere que el cliente comparta un refresh token con la API intermedia, lo cual introduce riesgos de seguridad adicionales. MSAL soporta ambos modos, pero la práctica recomendada es usar el access token como aserción y no propagar refresh tokens fuera del cliente confidencial original.

## Configuración de consentimiento y scopes

Para que el flujo OBO funcione, es necesario registrar correctamente las aplicaciones en Azure AD y configurar los permisos y la exposición de scopes.

### Registro de la API intermedia

- Exponer al menos un scope (por ejemplo, `access_as_user`) que los clientes solicitarán. Esto define la API como recurso.
- Configurar permisos delegados hacia la API descendente (por ejemplo, Microsoft Graph: `User.Read`, `Mail.Read`). Estos permisos deben ser consentidos por el usuario o el administrador.
- Si se desea que el consentimiento para la API intermedia incluya automáticamente los permisos para la descendente, se puede usar `knownClientApplications` en el manifiesto de la API descendente, listando el `appId` de la API intermedia. Esto permite el consentimiento en cascada: cuando un usuario consiente a la API intermedia, también consiente los permisos necesarios para la descendente.

### Scopes efectivos en cada tramo

El token que recibe la API intermedia contiene los scopes que el cliente solicitó para ella (por ejemplo, `api://intermedia/access_as_user`). El token que la API intermedia obtiene para la API descendente contiene los scopes que la intermedia solicitó en su petición OBO, que deben ser un subconjunto de los permisos delegados configurados y consentidos. No hay herencia automática de scopes: la API intermedia debe solicitar explícitamente los scopes que necesita para la descendente.

## Implementación con MSAL: adquisición del token On-Behalf-Of

### Inicialización del cliente confidencial

En MSAL.NET, se crea un `IConfidentialClientApplication`:

```csharp
var app = ConfidentialClientApplicationBuilder
    .Create(clientId)
    .WithClientSecret(clientSecret) // o WithCertificate
    .WithAuthority(authority) // https://login.microsoftonline.com/{tenantId}
    .Build();
```

En MSAL Python:

```python
import msal
app = msal.ConfidentialClientApplication(
    client_id=client_id,
    client_credential=client_secret,
    authority=f"https://login.microsoftonline.com/{tenant_id}"
)
```

### Extracción y validación del token entrante

Antes de invocar OBO, la API intermedia debe validar el token recibido. En ASP.NET Core, se puede usar `Microsoft.Identity.Web` que automatiza la validación y expone el token a través de `ITokenAcquisition`. Si se prefiere un control manual, se puede validar con `JwtSecurityTokenHandler`:

```csharp
var handler = new JwtSecurityTokenHandler();
var validationParameters = new TokenValidationParameters
{
    ValidateIssuer = true,
    ValidIssuer = $"https://login.microsoftonline.com/{tenantId}/v2.0",
    ValidateAudience = true,
    ValidAudience = clientId, // App ID de la API intermedia
    ValidateLifetime = true,
    IssuerSigningKeys = ... // obtener de OpenID Connect discovery
};
SecurityToken validatedToken;
var principal = handler.ValidateToken(token, validationParameters, out validatedToken);
```

Es crucial validar la audiencia (`aud`) para evitar que un token emitido para otra API se use como aserción en esta.

### Adquisición del token OBO

Con el token validado, se construye un `UserAssertion` y se llama al método OBO:

**C# (MSAL.NET):**

```csharp
string incomingAccessToken = ...; // extraído del header Authorization
var userAssertion = new UserAssertion(incomingAccessToken);
var scopes = new[] { "https://graph.microsoft.com/User.Read" };

AuthenticationResult result = await app.AcquireTokenOnBehalfOf(scopes, userAssertion)
    .ExecuteAsync();
string downstreamToken = result.AccessToken;
```

**Python (MSAL Python):**

```python
scopes = ["https://graph.microsoft.com/User.Read"]
result = app.acquire_token_on_behalf_of(
    user_assertion=incoming_access_token,
    scopes=scopes
)
downstream_token = result['access_token']
```

### Ejemplo completo en C# (API intermedia con ASP.NET Core)

A continuación, un controlador que recibe una petición, valida el token entrante, adquiere un token para Microsoft Graph y llama a Graph para leer el perfil del usuario.

```csharp
[ApiController]
[Route("api/[controller]")]
public class ProfileController : ControllerBase
{
    private readonly IConfiguration _config;
    private readonly IConfidentialClientApplication _app;

    public ProfileController(IConfiguration config)
    {
        _config = config;
        _app = ConfidentialClientApplicationBuilder
            .Create(config["AzureAd:ClientId"])
            .WithClientSecret(config["AzureAd:ClientSecret"])
            .WithAuthority($"{config["AzureAd:Instance"]}{config["AzureAd:TenantId"]}")
            .Build();
    }

    [HttpGet]
    public async Task<IActionResult> GetProfile()
    {
        // 1. Extraer token entrante
        string authHeader = Request.Headers["Authorization"].FirstOrDefault();
        if (string.IsNullOrEmpty(authHeader) || !authHeader.StartsWith("Bearer "))
            return Unauthorized();
        string incomingToken = authHeader["Bearer ".Length..].Trim();

        // 2. Validar token (simplificado; en producción usar Microsoft.Identity.Web)
        var handler = new JwtSecurityTokenHandler();
        // ... validación con TokenValidationParameters (omitted for brevity, but essential)
        // Asumimos token válido.

        // 3. Adquirir token OBO para Graph
        var userAssertion = new UserAssertion(incomingToken);
        var scopes = new[] { "https://graph.microsoft.com/User.Read" };
        AuthenticationResult result;
        try
        {
            result = await _app.AcquireTokenOnBehalfOf(scopes, userAssertion)
                .ExecuteAsync();
        }
        catch (MsalUiRequiredException)
        {
            // El consentimiento falta o el token de aserción no es válido
            return Challenge(); // o devolver 403 con instrucciones
        }

        // 4. Llamar a Microsoft Graph
        using var httpClient = new HttpClient();
        httpClient.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", result.AccessToken);
        var graphResponse = await httpClient.GetAsync("https://graph.microsoft.com/v1.0/me");
        graphResponse.EnsureSuccessStatusCode();
        var content = await graphResponse.Content.ReadAsStringAsync();
        return Content(content, "application/json");
    }
}
```

### Ejemplo en Python (FastAPI)

```python
from fastapi import FastAPI, Request, HTTPException
import msal
import httpx

app = FastAPI()

# Configuración
CLIENT_ID = "your_api_client_id"
CLIENT_SECRET = "your_api_secret"
TENANT_ID = "your_tenant_id"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

msal_app = msal.ConfidentialClientApplication(
    client_id=CLIENT_ID,
    client_credential=CLIENT_SECRET,
    authority=AUTHORITY
)

@app.get("/profile")
async def get_profile(request: Request):
    # 1. Extraer token
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401)
    incoming_token = auth_header[7:]

    # 2. Validación básica (en producción usar librería como PyJWT con claves de Azure AD)
    # ...

    # 3. OBO
    scopes = ["https://graph.microsoft.com/User.Read"]
    result = msal_app.acquire_token_on_behalf_of(
        user_assertion=incoming_token,
        scopes=scopes
    )
    if "error" in result:
        raise HTTPException(status_code=403, detail=result.get("error_description"))

    # 4. Llamar a Graph
    async with httpx.AsyncClient() as client:
        graph_response = await client.get(
            "https://graph.microsoft.com/v1.0/me",
            headers={"Authorization": f"Bearer {result['access_token']}"}
        )
        graph_response.raise_for_status()
        return graph_response.json()
```

## Caché de tokens: estrategias y desafíos en entornos distribuidos

MSAL incluye una caché de tokens en memoria por defecto. Cuando se adquiere un token OBO, MSAL almacena el resultado (access token, refresh token, expiración) asociado a la aserción (usuario) y los scopes. En llamadas posteriores con la misma aserción y scopes, MSAL devuelve el token de la caché sin llamar a Azure AD, reduciendo latencia y carga en el STS.

### El problema de la caché en memoria en APIs multi-instancia

En una API desplegada en múltiples instancias (horizontal scaling), la caché en memoria no se comparte. Una instancia puede tener un token válido en caché, pero otra instancia que recibe una petición del mismo usuario tendrá que solicitar un token nuevo. Esto no es un error funcional, pero aumenta las llamadas al STS y la latencia. Peor aún, si se usa el flujo OBO con refresh token, la rotación de refresh tokens puede causar problemas de sincronización: una instancia puede usar un refresh token que otra instancia ya ha reemplazado, provocando fallos de autenticación.

### Serialización de la caché

MSAL permite personalizar el almacenamiento de la caché mediante los delegados `BeforeAccess` y `AfterAccess` (en MSAL.NET) o el `token_cache` con serialización personalizada (en MSAL Python). La caché se serializa como un blob binario (MSAL.NET) o JSON (MSAL Python). Para entornos distribuidos, se debe persistir en un almacén compartido.

**Ejemplo de serialización en Redis con MSAL.NET:**

```csharp
var app = ConfidentialClientApplicationBuilder.Create(clientId)
    .WithClientSecret(clientSecret)
    .WithAuthority(authority)
    .WithCacheOptions(CacheOptions.EnableSharedCacheOptions) // opcional
    .Build();

// Configurar serialización a Redis
var redisConnection = ConnectionMultiplexer.Connect("redis-connection-string");
var cache = app.UserTokenCache;
cache.SetBeforeAccess(async (args) =>
{
    var db = redisConnection.GetDatabase();
    var key = $"msal:cache:{args.SuggestedCacheKey}";
    var data = await db.StringGetAsync(key);
    if (data.HasValue)
        args.TokenCache.DeserializeMsalV3(data);
});
cache.SetAfterAccess(async (args) =>
{
    if (args.HasStateChanged)
    {
        var db = redisConnection.GetDatabase();
        var key = $"msal:cache:{args.SuggestedCacheKey}";
        var data = args.TokenCache.SerializeMsalV3();
        await db.StringSetAsync(key, data, TimeSpan.FromDays(30));
    }
});
```

En MSAL Python, se puede pasar un `token_cache` personalizado que persista en Redis, base de datos, etc.

### Particionado por tenant y cuenta

Para evitar fugas de tokens entre tenants (en aplicaciones multi-tenant), la clave de caché debe incluir el `home_account_id` o el `tenant_id`. MSAL.NET expone `SuggestedCacheKey` que ya incluye el identificador de cuenta y tenant. Al serializar, se debe usar esa clave para aislar correctamente.

### Trade-offs

- **Latencia**: la caché distribuida añade una llamada de red (Redis, SQL) en cada acceso, pero evita la llamada al STS, que es más lenta. El balance es positivo si la tasa de aciertos es alta.
- **Consistencia**: en escenarios con refresh token rotation, varias instancias pueden competir por actualizar la caché. Se debe implementar bloqueo optimista o usar almacenes con consistencia fuerte.
- **Seguridad en reposo**: los tokens almacenados deben estar encriptados. MSAL.NET puede integrarse con la Data Protection API (ASP.NET Core) para encriptar la caché antes de enviarla a Redis. En MSAL Python, se debe encriptar manualmente o usar un almacén seguro.

## Seguridad en el intercambio de tokens

El flujo OBO introduce riesgos específicos que deben mitigarse:

### Validación estricta del token entrante

- **Audiencia**: el `aud` debe coincidir con el `clientId` de la API intermedia. Si se acepta un token con `aud` de otra API, un atacante podría usar un token robado de otra aplicación para suplantar al usuario en esta API.
- **Emisor**: debe ser `https://login.microsoftonline.com/{tenantId}/v2.0` (o el emisor correspondiente). No se deben aceptar tokens de otros tenants no confiables.
- **Firma**: validar con las claves públicas del emisor (obtenidas del endpoint `jwks_uri` del discovery document).
- **Nonce y expiración**: aunque el nonce es más relevante en el flujo de autorización, se debe verificar `exp`, `nbf` y opcionalmente `iat` con una ventana temporal para mitigar replay attacks. Azure AD emite tokens con una validez típica de 1 hora; la API intermedia puede rechazar tokens con `iat` demasiado antiguo (por ejemplo, más de 5 minutos) si se requiere frescura.

### Uso de access_token vs. id_token como aserción

El flujo OBO está diseñado para usar el `access_token` como aserción. Un `id_token` no es adecuado porque su audiencia es el cliente, no la API, y no contiene scopes. Usar un `id_token` puede permitir suplantación si no se valida correctamente. MSAL espera un `access_token` en el `UserAssertion`.

### Protección contra replay

Azure AD incluye un claim `nonce` en algunos tokens, pero no en todos. Para mitigar replay, se puede registrar el `jti` (JWT ID) del token entrante en una caché de un solo uso con un TTL igual a la ventana de validez. Si un token con el mismo `jti` se recibe más de una vez, se rechaza.

### Confidencialidad del secreto de cliente

El secreto usado por la API intermedia para autenticarse en el flujo OBO debe protegerse como cualquier credencial: almacenado en Azure Key Vault, variables de entorno seguras, o mejor, usando Managed Identities cuando la API se ejecuta en Azure (App Service, Functions, AKS). MSAL soporta `WithClientAssertion` para usar certificados o Managed Identity (a través de `Azure.Identity`).

### Rotación de secretos

Los secretos de cliente deben rotarse periódicamente. Azure AD permite múltiples secretos activos para facilitar la rotación sin downtime.

## Errores comunes y diagnóstico

### AADSTS50013: Assertion failed signature validation

Causas típicas:
- El token entrante ha expirado.
- La audiencia del token no coincide con la API intermedia (el `aud` es incorrecto).
- El token está mal formado o fue manipulado.
- Se está usando un `id_token` en lugar de `access_token`.

Solución: validar el token antes de usarlo como aserción; comprobar `exp`, `aud` y la firma.

### AADSTS65001: Consent missing

El usuario (o administrador) no ha consentido los permisos delegados que la API intermedia solicita para la API descendente. Puede ocurrir si el consentimiento incremental no se ha completado o si la configuración de `knownClientApplications` no está correcta.

Solución: asegurar que el consentimiento se otorga antes de la llamada. En desarrollo, se puede usar el endpoint de consentimiento del administrador (`/adminconsent`). En producción, redirigir al usuario para que consienta si se recibe este error (MSAL lanza `MsalUiRequiredException`).

### AADSTS70011: Invalid scope

El scope solicitado en la llamada OBO no está expuesto por la API descendente o está mal escrito (por ejemplo, `https://graph.microsoft.com/User.Read` vs `User.Read`). Verificar el manifiesto de la API descendente.

### Tokens expirados en caché

MSAL maneja la expiración automáticamente: si el token en caché está expirado, intenta usar el refresh token para obtener uno nuevo. Si el refresh token también expiró o es inválido, lanza `MsalUiRequiredException` (en MSAL.NET) o devuelve un error en el diccionario (MSAL Python). La API intermedia debe capturar esta excepción y devolver un error 401 o 403 al cliente, indicando que necesita reautenticarse.

### Logging y telemetría

MSAL proporciona logging configurable. En MSAL.NET:

```csharp
var app = ConfidentialClientApplicationBuilder.Create(clientId)
    .WithLogging((level, message, containsPii) =>
    {
        Console.WriteLine($"{level}: {message}");
    }, LogLevel.Verbose, enablePiiLogging: false)
    .Build();
```

En MSAL Python, se puede habilitar logging estándar de Python para el módulo `msal`. Esto ayuda a diagnosticar errores silenciosos como fallos de red, respuestas inesperadas del STS, etc.

## Trade-offs y consideraciones de diseño

### OBO vs. flujo de credenciales de cliente

- **OBO**: la API descendente ve la identidad del usuario original. Permite autorización granular basada en el usuario. Requiere consentimiento y tokens delegados.
- **Client credentials**: la API intermedia usa su propia identidad (sin usuario) para llamar a la descendente. Más simple, no requiere consentimiento de usuario, pero pierde el contexto de usuario. Adecuado para operaciones de background o cuando la API descendente no necesita distinguir usuarios.

### Impacto en latencia

Cada salto OBO implica una llamada adicional al STS (Azure AD). En una cadena de 3 APIs (A → B → C), B hace OBO para llamar a C, añadiendo latencia. Si la cadena es profunda, la latencia acumulada puede ser significativa. La caché de tokens mitiga esto en llamadas repetidas, pero la primera llamada siempre paga el costo.

### Límites de la cadena de delegación

No hay un límite técnico estricto en el número de saltos OBO, pero cada salto requiere que la API intermedia tenga permisos delegados sobre la siguiente. A partir de cierta profundidad, la gestión de consentimiento y la latencia se vuelven problemáticas. Se recomienda no exceder 2 o 3 saltos. Alternativas como eventos asíncronos o desacoplamiento con colas pueden reducir la necesidad de cadenas profundas.

### Alternativas

- **Token exchange con otros proveedores**: la RFC 8693 define un marco general. Azure AD implementa un perfil específico. Otros proveedores (Auth0, Okta) tienen sus propios mecanismos.
- **SPIFFE/SPIRE**: en mallas de servicio, se puede usar identidad basada en certificados SPIFFE para la comunicación entre servicios, manteniendo la identidad del usuario en metadata. No es un reemplazo directo de OBO, pero puede combinarse.
- **Arquitectura event-driven**: en lugar de llamadas encadenadas, la API intermedia puede publicar un evento con la identidad del usuario, y la API descendente lo consume y actúa con sus propios permisos de aplicación. Esto desacopla y elimina la necesidad de OBO, pero requiere un mecanismo de autorización diferente.

### Cuándo usar OBO

OBO es la opción correcta cuando:
- La API descendente necesita aplicar permisos delegados basados en el usuario original.
- La cadena de llamadas es corta (1-2 saltos).
- Se requiere auditoría completa de la identidad del usuario en todos los niveles.
- El ecosistema es Microsoft Identity Platform y las APIs son Azure AD protegidas.

Si la API descendente solo necesita datos que no dependen del usuario, o si la cadena es profunda, considerar client credentials o rediseñar la arquitectura.

## Ejemplo completo: API intermedia en C# que llama a Microsoft Graph

A continuación se presenta un proyecto completo que demuestra el flujo OBO con caché en Redis, validación de tokens y propagación de identidad.

### Estructura del proyecto y registro de apps

1. **API intermedia** (App ID: `api-intermedia`): expone un scope `access_as_user`. Configura permisos delegados a Microsoft Graph: `User.Read`, `Mail.Read`.
2. **Cliente** (App ID: `cliente-spa`): autorizado para solicitar `api://api-intermedia/access_as_user`.
3. **Microsoft Graph**: API descendente.

En Azure AD, en el manifiesto de la API intermedia, se establece `knownClientApplications` con el App ID del cliente para consentimiento combinado.

### Código de la API intermedia

Se usa ASP.NET Core 6+, con `Microsoft.Identity.Web` para validación automática y `Microsoft.Identity.Client` para OBO. La caché se serializa a Redis.

**Program.cs:**

```csharp
using Microsoft.Identity.Web;
using Microsoft.Identity.Client;
using StackExchange.Redis;

var builder = WebApplication.CreateBuilder(args);

// Configurar autenticación JWT con Microsoft.Identity.Web
builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddMicrosoftIdentityWebApi(builder.Configuration.GetSection("AzureAd"));

builder.Services.AddAuthorization();

// Registrar IConfidentialClientApplication como singleton con caché en Redis
builder.Services.AddSingleton<IConfidentialClientApplication>(sp =>
{
    var config = sp.GetRequiredService<IConfiguration>();
    var app = ConfidentialClientApplicationBuilder
        .Create(config["AzureAd:ClientId"])
        .WithClientSecret(config["AzureAd:ClientSecret"])
        .WithAuthority($"{config["AzureAd:Instance"]}{config["AzureAd:TenantId"]}")
        .Build();

    // Configurar serialización a Redis
    var redis = ConnectionMultiplexer.Connect(config["Redis:ConnectionString"]);
    var cache = app.UserTokenCache;
    cache.SetBeforeAccess(async (args) =>
    {
        var db = redis.GetDatabase();
        var key = $"msal:obo:{args.SuggestedCacheKey}";
        var data = await db.StringGetAsync(key);
        if (data.HasValue)
            args.TokenCache.DeserializeMsalV3(data);
    });
    cache.SetAfterAccess(async (args) =>
    {
        if (args.HasStateChanged)
        {
            var db = redis.GetDatabase();
            var key = $"msal:obo:{args.SuggestedCacheKey}";
            var data = args.TokenCache.SerializeMsalV3();
            await db.StringSetAsync(key, data, TimeSpan.FromDays(30));
        }
    });

    return app;
});

builder.Services.AddHttpClient();

var app = builder.Build();
app.UseAuthentication();
app.UseAuthorization();
app.MapControllers();
app.Run();
```

**Controlador ProfileController.cs:**

```csharp
[Authorize]
[ApiController]
[Route("api/[controller]")]
public class ProfileController : ControllerBase
{
    private readonly IConfidentialClientApplication _app;
    private readonly IHttpClientFactory _httpClientFactory;

    public ProfileController(IConfidentialClientApplication app, IHttpClientFactory httpClientFactory)
    {
        _app = app;
        _httpClientFactory = httpClientFactory;
    }

    [HttpGet]
    public async Task<IActionResult> Get()
    {
        // Obtener el token entrante validado por Microsoft.Identity.Web
        string incomingToken = await HttpContext.GetTokenAsync("access_token");
        if (string.IsNullOrEmpty(incomingToken))
            return Unauthorized();

        var userAssertion = new UserAssertion(incomingToken);
        var scopes = new[] { "https://graph.microsoft.com/User.Read" };

        AuthenticationResult result;
        try
        {
            result = await _app.AcquireTokenOnBehalfOf(scopes, userAssertion)
                .ExecuteAsync();
        }
        catch (MsalUiRequiredException ex)
        {
            // El consentimiento falta o el token de aserción no es válido
            return StatusCode(403, new { error = "consent_required", claims = ex.Claims });
        }
        catch (MsalServiceException ex) when (ex.ErrorCode == "invalid_grant")
        {
            return StatusCode(401, new { error = "invalid_assertion" });
        }

        // Llamar a Microsoft Graph
        var client = _httpClientFactory.CreateClient();
        client.DefaultRequestHeaders.Authorization =
            new AuthenticationHeaderValue("Bearer", result.AccessToken);
        var response = await client.GetAsync("https://graph.microsoft.com/v1.0/me");
        if (!response.IsSuccessStatusCode)
            return StatusCode((int)response.StatusCode, await response.Content.ReadAsStringAsync());

        var content = await response.Content.ReadAsStringAsync();
        return Content(content, "application/json");
    }
}
```

**appsettings.json:**

```json
{
  "AzureAd": {
    "Instance": "https://login.microsoftonline.com/",
    "TenantId": "your-tenant-id",
    "ClientId": "api-intermedia-app-id",
    "ClientSecret": "your-secret"
  },
  "Redis": {
    "ConnectionString": "your-redis-connection-string"
  }
}
```

### Demostración de propagación de identidad

El token emitido para Graph contiene los claims del usuario original (`oid`, `upn`, etc.). La respuesta de `/me` refleja el usuario autenticado inicialmente, no la identidad de la API intermedia. Si se añade el scope `Mail.Read`, la API intermedia podría leer el correo del usuario, demostrando que actúa en su nombre.

### Prueba con Postman

1. Obtener un token para la API intermedia usando el cliente (por ejemplo, con authorization code flow).
2. Llamar a `GET /api/profile` con el token.
3. La respuesta contiene el perfil del usuario desde Graph.

## Referencias y recursos adicionales

- [Microsoft Identity Platform y OAuth 2.0 On-Behalf-Of flow](https://learn.microsoft.com/en-us/azure/active-directory/develop/v2-oauth2-on-behalf-of-flow)
- [MSAL.NET documentation](https://learn.microsoft.com/en-us/azure/active-directory/develop/msal-net-overview)
- [MSAL Python documentation](https://learn.microsoft.com/en-us/azure/active-directory/develop/msal-python)
- [RFC 8693 – OAuth 2.0 Token Exchange](https://datatracker.ietf.org/doc/html/rfc8693)
- [Azure-Samples: active-directory-dotnet-native-aspnetcore-v2](https://github.com/Azure-Samples/active-directory-dotnet-native-aspnetcore-v2) (incluye OBO)
- [Herramienta jwt.ms para decodificar tokens](https://jwt.ms)
- [Microsoft.Identity.Web](https://github.com/AzureAD/microsoft-identity-web)