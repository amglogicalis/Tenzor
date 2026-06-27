# Plan de Implementacion Refinado — Arzor AIs Platform

Este documento recoge todas las decisiones de diseno y mejoras acordadas, ordenadas
por prioridad y dependencias logicas. Cada fase debe completarse antes de pasar a la siguiente.

---

## FASE 0 — Quick Wins (sin dependencias, se pueden hacer en cualquier momento)

### 0.1 — Favicon / icono de pestana y bookmarks
- Anadir `<link rel="icon" href="/static/logo_arzor.png" type="image/png">` al `<head>` de
  `app/static/platform/index.html`.
- Idealmente generar un `.ico` multi-resolucion (16x16, 32x32, 48x48) y un `apple-touch-icon`
  para iOS.
- **Impacto**: minimo. **Esfuerzo**: 5 minutos.

---

## FASE 1 — Investigacion exhaustiva de providers compatibles (Investigar, NO implementar)

### 1.1 — Objetivo
Antes de tocar arquitectura, obtener un cuadro comparativo actualizado y oficial de todos los
providers de LLM que:
- Tienen **free tier** real (no solo trial de creditos)
- Usan la **OpenAI API spec** (mismo formato de llamada que OpenRouter/Groq) O tienen una API
  documentada que podemos adaptar
- Ofrecen modelos de calidad suficiente para ser utiles en produccion

### 1.2 — Providers conocidos a investigar
Los siguientes son punto de partida, NO lista definitiva:

| Provider | URL | Notas iniciales |
|---|---|---|
| **Groq** | groq.com | Ya integrado. Free tier muy limitado en tokens/dia |
| **Google Gemini** | ai.google.dev | Ya integrado. Free tier generoso en RPM/tokens |
| **OpenRouter** | openrouter.ai | Ya integrado. Modelos `:free` compartidos, saturados |
| **Cerebras** | inference.cerebras.ai | Velocidad extrema. Investigar free tier y compatibilidad |
| **NVIDIA NIM** | build.nvidia.com | Modelos premium. Investigar free tier disponible |
| **Cohere** | cohere.com | Command models. API propia. Investigar free tier |
| **SambaNova** | sambanova.ai | Alta velocidad. Investigar free tier y compatibilidad |
| **Together AI** | together.ai | OpenAI-compatible. Investigar free tier |
| **Mistral** | mistral.ai | OpenAI-compatible. Free tier con Codestral API |
| **Cloudflare AI** | developers.cloudflare.com/workers-ai | Free tier generoso |
| **Hugging Face Inference** | huggingface.co/inference-api | Gratis con limites |
| **Fireworks AI** | fireworks.ai | OpenAI-compatible. Investigar free tier |
| **DeepSeek** | platform.deepseek.com | Modelos potentes y baratos. OpenAI-compatible |
| **xAI (Grok)** | x.ai/api | Investigar si tiene free tier real |
| **Perplexity** | docs.perplexity.ai | Modelos con acceso a internet |

### 1.3 — Lo que necesitamos saber de cada provider
Para cada uno:
- Tiene free tier permanente o solo creditos de prueba?
- Cuantos tokens/dia o RPM en free?
- Usa OpenAI API spec (base_url + Bearer token)? -> Categoria A (facil integrar)
- Usa API propia? -> Categoria B (necesita adaptador)
- Que modelos especificos tiene en free?
- Requiere tarjeta de credito para el free tier?
- Calidad subjetiva de los modelos

### 1.4 — Resultado esperado
Un documento `provider_research.md` con la tabla completa y decision final:
- Lista priorizada de providers a integrar
- Para cada uno: tipo de integracion (A o B), tier recomendado de uso

---

## FASE 2 — Ampliar modelos gratuitos en OpenRouter

### 2.1 — Problema actual
Actualmente solo se usa `meta-llama/llama-3.3-70b-instruct:free` para balanced.
Ese modelo es compartido entre todos los usuarios de OpenRouter -> saturacion constante.

### 2.2 — Solucion
Crear una lista de modelos `:free` de OpenRouter a intentar en secuencia:
- Si el modelo primario da 429 -> intentar el siguiente modelo `:free` automaticamente
- Mantener un cooldown por modelo, no solo por key
- Lista de modelos a evaluar (basada en la investigacion de la Fase 1)

### 2.3 — Cambios necesarios en `provider_key_pool_service.py`
- `PROVIDER_MODEL_MAP` pasa de un solo modelo por tier a una **lista de modelos por tier**
- El router intenta el primero, si falla con 429 prueba el siguiente del mismo provider

---

## FASE 3 — Sistema BYOK: el usuario aporta sus propias API keys

### 3.1 — Concepto
Cada usuario puede anadir en su perfil las API keys de los providers que quiera usar.
Estas keys tienen **prioridad maxima** sobre las keys de sistema (ya implementado en el pool).
El usuario paga su propio uso con sus propias keys -> sin limite de tokens compartido.

### 3.2 — UI de configuracion de keys (Perfil del usuario)
Actualmente al hacer clic en el avatar/icono del usuario en la topbar no ocurre nada util.
Debe navegar a una seccion de **Perfil / Configuracion** donde el usuario pueda:
- Ver los providers disponibles (lista de la Fase 1)
- Anadir / editar / eliminar su API key para cada provider
- Ver el estado de cada key (activa, en cooldown, invalida)
- Las keys se guardan cifradas en Supabase (ya implementado con AES-GCM)

### 3.3 — Lista de providers disponibles para el usuario
Se mantiene una **lista blanca de providers compatibles** con Arzor, con:
- Nombre y logo del provider
- Enlace a su pagina de API keys
- Nota sobre que tier/modelo se usara con esa key
- Indicador de compatibilidad (A: OpenAI-spec | B: adaptador propio)

---

## FASE 4 — Cambio de paradigma: de "tier" a "proveedor del usuario"

### 4.1 — El cambio conceptual
El concepto de `fast / balanced / pro` desaparece de cara al usuario.
En su lugar, el usuario **elige que provider quiere usar** para sus agentes.

La seleccion funciona asi:
1. El usuario tiene sus keys configuradas en el perfil (Fase 3)
2. Al crear o editar un agente, elige el **provider principal** de entre sus keys configuradas
3. El sistema usa ese provider como primera opcion para ese agente
4. Si el provider falla (429, error, sin cuota) -> **fallback automatico** a los providers
   de sistema default (Groq -> Gemini -> OpenRouter modelos free) en ese orden

### 4.2 — Agentes de la biblioteca publica
Cuando un usuario quiere **clonar o usar un agente publicado en la biblioteca**, el sistema
debe verificar que el usuario tiene configurado un provider compatible.
- Si el agente original usaba Gemini y el usuario no tiene key de Gemini -> avisar y pedir
  que configure una key (o usar los defaults del sistema si los hay disponibles)
- Si el usuario tiene su propia key del provider compatible -> usarla con prioridad

### 4.3 — AFT Compiler con multiples providers
Cuando un agente se compila con AFT (Agent Fine-Tuning), las instrucciones del sistema
se optimizan para el provider principal del usuario.
Los providers de **fallback tambien reciben el system prompt compilado**, asegurando
coherencia de comportamiento aunque el provider principal falle:
- El perfil AFT se compila una vez con el modelo principal
- Se guarda en `agent_versions` como ahora
- El fallback (Groq/Gemini/OpenRouter default) usa el mismo system prompt compilado -> coherencia garantizada
- No hay que recompilar por provider (el system prompt es agnostico al modelo)

### 4.4 — Cambios en UI
- Modal "Crear Agente": campo "Tier" -> campo "Provider" (dropdown con los providers del usuario)
- Si el usuario no tiene keys -> mostrar mensaje "Configura un provider en tu perfil primero"
  con enlace a la seccion de perfil, o usar el pool de sistema como default
- Topbar: el icono del usuario -> lleva a pagina de Perfil con las keys

---

## FASE 5 — Arquitectura del router con el nuevo modelo de providers

### 5.1 — Nuevo flujo de inferencia
```
Usuario envia mensaje al agente X (que tiene provider_preference = "groq")
  -> Buscar provider principal del agente (key del usuario para groq)
  -> Si key disponible -> intentar con esa key/modelo
  -> Si falla -> fallback 1: siguiente key del mismo provider (si el usuario tiene varias)
  -> Si falla -> fallback 2: Groq sistema (sys-groq-1)
  -> Si falla -> fallback 3: Gemini sistema (sys-google-1)
  -> Si falla -> fallback 4: OpenRouter modelos free (lista de modelos de Fase 2)
  -> Si todo falla -> InferenceError con mensaje claro al usuario
```

### 5.2 — Cambios en `provider_router_service.py`
- El metodo `infer()` recibe `preferred_provider` y `preferred_model` opcionales
- El `key_pool` ya tiene el sistema de prioridad de keys de usuario sobre sistema
- Anadir logica de "preferred provider first, then system fallbacks"

### 5.3 — Anadir providers Categoria A (OpenAI-spec)
Los providers de la Fase 1 clasificados como Categoria A (OpenAI-compatible) se integran
con la funcion generica `_call_openai_compatible()` reutilizando el codigo de `_call_openrouter`
pero parametrizando el `base_url`:
```python
def _call_openai_compatible(messages, model, api_key, base_url, temperature, max_tokens, system_prompt):
    # mismo codigo que _call_openrouter pero con base_url configurable
    # esto permite anadir cualquier provider OpenAI-compatible simplemente con su base_url
```

### 5.4 — Anadir providers Categoria B (API propia)
Para Cohere, NVIDIA NIM, etc. que tienen su propia spec:
- Implementar `_call_cohere()`, `_call_nvidia()`, etc. segun necesidad
- Anadirlos al `_dispatch()` del router

---

## FASE 6 — Mejoras de UX y calidad de vida

### 6.1 — Pagina de Perfil completa
- Seccion de API keys por provider con estado visual
- Estadisticas de uso (tokens consumidos por key)
- Estado de cada key en tiempo real (disponible / en cooldown / invalida)

### 6.2 — Mensaje de error mejorado al usuario
Actualmente cuando todos los providers fallan -> "503 Service Unavailable" generico.
Mejorar para mostrar:
- "Tu provider principal (Groq) esta temporalmente saturado. El sistema intento 3 alternativas."
- Boton de reintentar
- Enlace a configurar mas providers en el perfil

### 6.3 — Indicador de provider en el chat
En cada respuesta del asistente, mostrar que provider/modelo respondio (ya hay metadata).

---

## FASE 7 — Investigar y resolver 403 de Gemini en Render (pendiente de diagnostico)

### 7.1 — Contexto del problema
La key `AQ.Ab8RN6...` de Google AI Studio es valida y sin restricciones configuradas.
Localmente da 429 (quota free tier agotada). En Render da 403 (forbidden).
Misma key en ambos entornos segun el usuario. El problema persiste tras cambiar a REST transport.

### 7.2 — Hipotesis a investigar
1. El servicio de Render tiene bloqueadas salidas a `generativelanguage.googleapis.com`?
2. Hay algo en el formato de la peticion que Render modifica (headers, User-Agent, IP)?
3. El SDK `google-generativeai` con `transport="rest"` envia la key diferente a un raw HTTP request?
4. La quota de Google AI Studio es por proyecto y ya esta agotada globalmente?
5. El 403 es en realidad un error de configuracion del proyecto Google Cloud (API no habilitada)?

### 7.3 — Prueba definitiva a implementar
Anadir un endpoint de diagnostico temporal en el servidor (`/platform/debug/gemini-test`)
que haga una peticion minima a Gemini directamente con httpx y devuelva el status code
y headers exactos de la respuesta para ver que recibe Render de Google.

---

## Orden de ejecucion recomendado

| Paso | Tarea | Fase | Tiempo estimado |
|---|---|---|---|
| 1 | Favicon / icono de pestana | 0.1 | 10 min |
| 2 | Investigacion exhaustiva de providers | 1 | 2-3 horas |
| 3 | Ampliar modelos free en OpenRouter | 2 | 1 hora |
| 4 | UI de perfil + gestion de keys de usuario | 3 | 3-4 horas |
| 5 | Cambio tier -> provider en UI y modal de agente | 4 | 2 horas |
| 6 | Integrar providers Categoria A (OpenAI-spec) | 5.3 | 2 horas |
| 7 | Nuevo flujo de router con preferred provider + fallbacks | 5.1/5.2 | 3 horas |
| 8 | Integrar providers Categoria B si los hay | 5.4 | variable |
| 9 | Mejoras UX (errores, indicadores) | 6 | 2 horas |
| 10 | Investigar y resolver 403 Gemini en Render | 7 | variable |

---

## Notas importantes

- **No implementar nada de las Fases 3-5 sin antes tener el resultado de la Fase 1** (investigacion).
  El diseno del sistema de providers depende de que providers van a integrarse.
- El sistema de cifrado de keys de usuario ya esta implementado (`ARZOR_ENCRYPTION_KEY` + AES-GCM).
  Solo falta la UI y la logica de seleccion de provider preferido.
- El `provider_key_pool_service.py` ya tiene el 80% de la arquitectura necesaria.
  Los cambios son evolutivos, no una reescritura.
- La funcion RAG y el compilador AFT son **agnosticos al provider** -> no requieren cambios
  cuando se anaden nuevos providers.
- El sistema de fallback esta disenado para que el usuario nunca note un error si al menos
  un provider del pool esta disponible. Con mas providers, mayor resiliencia.
