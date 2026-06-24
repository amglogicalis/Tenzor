# Plan de Implementación: Tenzor AI Platform

Este plan detalla la evolución de **Tenzor** para albergar una subplataforma llamada **Tenzor AI Platform** (o **Tenzor Multi AIs Platform**), un entorno donde cualquier usuario puede registrarse con usuario/contraseña, especializar una IA con instrucciones y documentos propios (PDFs, TXT, MD), compartirla en una biblioteca pública y organizar debates colaborativos (**Tenzor Round Table**) sin costes de infraestructura centralizada.

---

## 💡 Concepto de Especialización Híbrida y Serverless

Para dar soporte a múltiples usuarios sin consumir tus créditos de Google Cloud en GPUs encendidas 24/7 y evitar bloqueos por rate-limit (429), utilizaremos:

1. **Arquitectura BYOK (Bring Your Own Key) Descentralizada**:
   - Los usuarios guardan de forma segura sus propias API Keys de Gemini y Groq desde el modal de Ajustes en el frontend (almacenadas en `localStorage` por privacidad).
   - Estas llaves se envían de forma dinámica en las cabeceras de cada petición al backend.
   - Toda la inferencia pesada (chats de agentes, debates de mesas redondas y emulaciones de tuning) se consume directamente contra las cuotas individuales de cada usuario, evitando costes y centralización de rate-limits en tu servidor.

2. **Adaptive Instruction Compilation (Motor de Emulated Fine-Tuning de Alta Capacidad)**:
   - **Programa Potente, Optimizado y Capaz**: El motor de síntesis de personalidad de cada agente debe ser sumamente robusto y estar bien optimizado. Estará basado en `gemini-2.5-pro` (o modelo avanzado equivalente en modo de salida estructurada JSON).
   - **Destilación de Directrices y Matriz Sintética**: A partir de la descripción informal del usuario, este programa destila de forma rápida y capaz las directrices maestras (`system_instructions`) y compila una matriz de pesos sintéticos (`pseudo_lora_weights` JSONB) con 10-15 ejemplos de interacción de pocas pasadas (*few-shot Q&A*) de altísima calidad y coherencia lógica.
   - **Esquema de Validación Estricta**: Se implementarán validadores semánticos y de esquema (Pydantic / Structured Outputs). Si el JSON resultante está incompleto, mal estructurado o carece de la profundidad técnica requerida, el backend realizará reintentos automáticos (máximo 3) ajustando la temperatura para asegurar un resultado potente y funcional que aporte valor real al comportamiento del agente.
   - **Optimización de Parsing**: Evitaremos overheads innecesarios utilizando parsers de JSON ultrarrápidos y cargando el contexto compilado en caché de memoria para peticiones subsiguientes.

3. **Database-backed RAG (Subida de Archivos)**:
   - El usuario sube PDFs o archivos de texto plano desde la interfaz.
   - El backend extrae el texto, lo divide en fragmentos y los inserta en Supabase (`agent_knowledge`).
   - Usamos la búsqueda de texto nativa de Postgres (`@@ to_tsquery`) para recuperar los fragmentos relevantes.

4. **Enrutamiento Dinámico de Modelos**:
   - **Generales / Ocio**: `gemini-2.5-flash-lite` (gratuito, límites de cuota amplios).
   - **Lógica / Programación / Rol Técnico**: `llama-3.3-70b-instruct` o `gemini-2.5-pro`.

5. **Resiliencia ante Errores 429 (Control Inteligente de Límites de API)**:
   - **Aislamiento por Clave (Multi-User Isolation)**: Dado que las API Keys de los usuarios son individuales, el backend aísla los límites por usuario. Si el usuario A satura su cuota y recibe un error 429, solo se pausarán sus peticiones individuales, manteniendo el servicio 100% disponible para el resto de usuarios en la plataforma.
   - **Detección Activa de 429 y Cálculo de Cooldown**: El backend interceptará los errores 429 de las APIs de Groq y Gemini. Extraerá el tiempo de espera de la cabecera `Retry-After` de la respuesta, o en su defecto aplicará un retroceso exponencial dinámico (comenzando en 30 segundos, duplicándose en fallos consecutivos).
   - **Pausa Elegante y Asíncrona**: En lugar de hacer fallar la sesión de chat o colgar el hilo del backend, el servidor detendrá de forma no bloqueante la ejecución mediante `asyncio.sleep` y devolverá un código de estado intermedio controlado al frontend.
   - **Visual Cooldown Grace Period (UI/UX Sci-Fi)**: Al recibir el evento de cooldown, el frontend deshabilitará el cuadro de texto del chat y mostrará una interfaz visual animada con temática sci-fi (por ejemplo, "Enfriamiento del Núcleo Cuántico en progreso...") con un temporizador dinámico. El chat se desbloqueará automáticamente al terminar el periodo, previniendo el spam del usuario que empeoraría el rate-limit.
   - **Cola de Inferencia Asíncrona con Prioridades (`asyncio.Queue`)**: Organiza de manera secuencial y ordenada las peticiones de debates en Mesas Redondas o chats grupales, evitando ráfagas y picos de tráfico simultáneos sobre un mismo token de usuario.
   - **Compresión Dinámica de Contexto**: En debates multigente, solo pasamos la pregunta base del usuario y los dos últimos turnos de conversación de forma deslizable para minimizar el consumo de tokens y maximizar la velocidad.
   - **Graceful Fallbacks de Clave**: Si el usuario configura múltiples API keys de fallback, o si el sistema detecta que el modelo premium está en cooldown prolongado, se le ofrecerá al usuario degradar temporalmente de forma elegante al modelo `gemini-2.5-flash-lite` con un aviso informativo.

---

## 🛠️ Esquema de Base de Datos (Supabase)

```sql
-- Perfiles de usuario vinculados al Auth clásico
CREATE TABLE profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    username VARCHAR(50) UNIQUE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL
);

-- Agentes personalizados creados por los usuarios
CREATE TABLE custom_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    category VARCHAR(50) NOT NULL,
    system_instructions TEXT NOT NULL,       -- Prompt maestro compilado
    pseudo_lora_weights JSONB NOT NULL,       -- Matriz de 10-15 ejemplos Q&A
    base_model VARCHAR(50) DEFAULT 'gemini-2.5-flash-lite' NOT NULL,
    is_public BOOLEAN DEFAULT FALSE NOT NULL,
    level INTEGER DEFAULT 1 NOT NULL,
    experience INTEGER DEFAULT 0 NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL
);

-- Fragmentos de conocimiento y mapa conceptual (GraphRAG)
CREATE TABLE agent_knowledge (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES custom_agents(id) ON DELETE CASCADE NOT NULL,
    concept_node VARCHAR(100) NOT NULL,       -- Nombre del nodo conceptual
    related_to VARCHAR(100),                  -- Relación con otro nodo
    content TEXT NOT NULL,                     -- Texto plano del fragmento
    tsv_content tsvector,                     -- Búsqueda por texto en Postgres
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL
);

-- Caché sináptico del agente para auto-aprendizaje y optimización
CREATE TABLE agent_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES custom_agents(id) ON DELETE CASCADE NOT NULL,
    query TEXT NOT NULL,
    response TEXT NOT NULL,
    user_feedback INTEGER DEFAULT 0,          -- +1 (pulgar arriba), -1 (abajo)
    times_used INTEGER DEFAULT 1 NOT NULL,
    last_used_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL
);

-- Estructura de Mesas Redondas (Round Tables)
CREATE TABLE round_tables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT TIMEZONE('utc'::text, NOW()) NOT NULL
);

-- Miembros de cada mesa redonda (IAs invitadas)
CREATE TABLE round_table_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_id UUID REFERENCES round_tables(id) ON DELETE CASCADE NOT NULL,
    agent_id UUID REFERENCES custom_agents(id) ON DELETE CASCADE NOT NULL
);
```

---

## 🗺️ Fases de Implementación y Puntos de Verificación

Para evitar la saturación de código y garantizar la máxima calidad, el proyecto se dividirá en 7 fases consecutivas. Cada fase requerirá pruebas automáticas y manuales para avanzar.

### 📍 Fase 1: Autenticación, Base de Datos y Rutas Base
* **Objetivo**: Configurar el esquema de Supabase, habilitar el registro/login con usuario y contraseña, y crear el esqueleto de endpoints de administración en FastAPI.
* **Componentes**:
  - `app/routers/platform_auth.py` [NEW]
  - `app/services/platform_key_service.py` [NEW] (Gestión de usuarios y tokens en base a cookies/sesiones JWT).
* **Verificación**:
  - Validar registro y login de usuarios de prueba.
  - Asegurar que las llamadas a base de datos se aíslen correctamente por `user_id`.

### 📍 Fase 2: El Sintetizador de Agentes Optimizado (Pseudo-LoRA Engine)
* **Objetivo**: Programar el motor de compilación de agentes robusto y potente. Recibe la descripción informal y de forma asíncrona genera el set de directrices y la matriz JSONB (`pseudo_lora_weights`) usando Pydantic, reintentos en caliente y validación lógica.
* **Componentes**:
  - `app/routers/platform_agents.py` [NEW] (Ruta `POST /platform/agents`).
  - Lógica de Meta-Prompting avanzado en `gemini-2.5-pro` estructurado, con control de temperatura.
* **Verificación**:
  - Test unitario: Crear un agente técnico y verificar que la matriz `pseudo_lora_weights` contiene de 10 a 15 ejemplos Q&A válidos, con alta consistencia de comportamiento y formato correcto.

### 📍 Fase 3: RAG con Subida de Archivos y Mapa Sináptico
* **Objetivo**: Integrar la subida de PDFs/Textos desde la UI, extraer el contenido, segmentar y construir el grafo de relaciones conceptuales en la base de datos.
* **Componentes**:
  - Integrar lector de PDFs en FastAPI.
  - Generador de grafos conceptuales: Extraer entidades clave y asociarlas (`concept_node` -> `related_to`).
  - Lógica de búsqueda semántica/léxica nativa en Postgres.
* **Verificación**:
  - Subir un PDF de prueba de 10 páginas, verificar que se guarda indexado en Supabase y que las búsquedas a través del chat recuperan los chunks correspondientes.

### 📍 Fase 4: Chat con Control Inteligente de 429 y Fallback
* **Objetivo**: Actualizar el motor de chat para soportar agentes personalizados, ordenando de forma rápida en memoria los pesos Pseudo-LoRA, e implementando el middleware detector de 429 con cooldown dinámico y aislamiento de cuotas.
* **Componentes**:
  - `app/routers/platform_chat.py` [NEW] (Ruta `/platform/chat`).
  - Modificación de `app/services/ai_service.py` [MODIFY] para recibir API Keys del usuario en cada petición y enrutar la inferencia.
  - Capturador de excepciones de API (Groq y Gemini) para capturar 429 y reaccionar devolviendo códigos de control.
* **Verificación**:
  - Test de stress: Forzar llamadas consecutivas rápidas simulando error 429 en una clave, y verificar que el backend devuelve un evento de cooldown estructurado (`status: "cooldown"`, `retry_after: N`) sin romper el contexto del chat.

### 📍 Fase 5: Tenzor Round Table (Debates de Agentes)
* **Objetivo**: Diseñar la lógica de orquestación de discusiones grupales.
* **Componentes**:
  - `app/routers/round_table.py` [NEW]
  - Bucle secuencial de inferencia de debates con cola asíncrona (`asyncio.Queue`) para evitar saturación de 429 en turnos consecutivos.
* **Verificación**:
  - Iniciar una Mesa Redonda con un Programador y un Tester sobre un fragmento de código, validando que el output final sea una conversación coherente entre ambos agentes.

### 📍 Fase 6: Caché de Memoria y Evolución Autónoma
* **Objetivo**: Programar el sistema de ahorro de tokens mediante la comprobación del historial y el auto-ajuste de comportamiento basado en el feedback del usuario.
* **Componentes**:
  - Lógica de interceptación en chat: Verificar `agent_cache` antes de llamar a las APIs.
  - Tarea en segundo plano para re-sintetizar pesos Pseudo-LoRA si un agente recibe retroalimentación negativa (-1) en un chat.
* **Verificación**:
  - Enviar una pregunta idéntica dos veces. Verificar mediante los logs del servidor que la segunda llamada se sirve directamente desde la base de datos consumiendo 0 tokens de API.

### 📍 Fase 7: Interfaz Visual "Neural Sandbox Console" y UX Antirruido
* **Objetivo**: Diseñar y maquetar la interfaz web en `/platform` (`platform.html`, CSS, JS) con estilo visual Sci-Fi premium, Canvas para el Mapa Sináptico y los controles del Pool de Keys.
* **UX Anti-429**:
  - Desactivación y bloqueo visual en chat al recibir eventos de cooldown.
  - Cuenta atrás sci-fi en tiempo real animada en el área del prompt.
* **Verificación**:
  - Ejecutar múltiples usuarios simultáneos, bloquear a uno por límite de cuota (429 simulado) y certificar que la interfaz de dicho usuario entra en pausa visual elegante mientras que el resto de usuarios chatea normalmente.

### 📍 Fase 8: Tenzor DevCrew CLI (Desarrollo Local Autónomo) [Fase 2 del Proyecto]
* **Objetivo**: Desarrollar la herramienta de terminal para la creación física de proyectos locales guiada por debates multi-agente en el servidor, con control estricto de cuotas para evitar errores 429.
* **Componentes**:
  - `cli/tenzor_crew.py` [NEW]: Cliente CLI local en Python.
  - Endpoints del servidor `/platform/crew/plan` (Debate y estructuración de JSON) y `/platform/crew/write` (Generación de código por archivo).
* **Mecanismos Anti-429 & Ahorro**:
  - **Debouncer Cliente-Servidor**: El CLI local inyecta pausas obligatorias de 1.5 a 3 segundos entre peticiones de creación de archivos.
  - **Backoff Exponencial Local**: Si la API del servidor devuelve un error 429, el CLI local reintenta automáticamente duplicando el tiempo de espera (e.g., 2s, 4s, 8s, 16s...) y mostrando telemetría en tiempo real: *"Rate limit alcanzado. Reintentando en X segundos..."*.
  - **Compresión por Stubs (Firmas de Código)**: Para que los agentes escriban un archivo sin consumir memoria innecesaria, el CLI no envía el código completo de todo el proyecto. Genera stubs ligeros (cabeceras de funciones/clases sin lógica) de los demás archivos y los envía como contexto de referencia técnica.
* **Verificación**:
  - Ejecutar el CLI local para generar un microservicio completo (FastAPI + base de datos) y certificar que escribe correctamente la estructura de directorios y los archivos funcionales sin disparar errores 429.

---

## 🚀 Instrucción de Arranque Rápido para el Agente

Cuando el usuario dé la orden directa:
**"pon el plan implementation_plan.md de la raiz sobre tenzor platform en marcha"**

El agente de turno debe proceder de la siguiente manera de forma inmediata y autónoma:
1. **Inicializar la Tarea**: Crear el archivo `task.md` en la carpeta de la conversación (copiando el plan base estructurado) para llevar el control de tareas en progreso `[/]` y completadas `[x]`.
2. **Crear Scripts y Estructura**: Iniciar la **Fase 1**, configurando las tablas necesarias en Supabase y creando el esqueleto de autenticación en FastAPI.
3. **Reportar Avance**: No detenerse a preguntar a menos que ocurra un error fatal o un cambio crítico de diseño no contemplado. Ejecutar fase por fase informando periódicamente del avance al usuario.
