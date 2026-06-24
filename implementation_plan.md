# Plan de Implementación: Arzor AIs Platform

Este plan detalla la evolución de **Tenzor** para albergar una subplataforma llamada **Arzor AIs Platform** (nombre que combina Arthur y Tenzor por el concepto central de la **Arzor Round Table**). Es un entorno donde cualquier usuario puede registrarse con usuario/contraseña, especializar una IA con instrucciones y documentos propios (PDFs, TXT, MD), compartirla en una biblioteca pública y organizar debates colaborativos (**Arzor Round Table**) protegidos contra fallos de API y saturación de cuotas.

---

## 💡 Concepto de Especialización Híbrida y Serverless

Para dar soporte a múltiples usuarios sin consumir tus créditos de Google Cloud y evitar bloqueos por rate-limit (429), utilizaremos:

1. **Matriz de Fallback Multi-Proveedor (Google, Groq y OpenRouter)**:
   - Agregamos **OpenRouter** como tercer proveedor principal de modelos.
   - Al crear un agente, el sistema asocia modelos de los **3 proveedores** clasificados según la necesidad del usuario:
     * **Inteligencia General (Pro)**: `gemini-2.5-pro` (Google), `llama-3.3-70b-instruct` (Groq), `qwen/qwen-2.5-72b-instruct` (OpenRouter).
     * **Equilibrio (Balanced)**: `gemini-2.5-flash` (Google), `qwen3.6-27b` (Groq), `microsoft/phi-4` o `qwen/qwen-2.5-32b-instruct` (OpenRouter).
     * **Velocidad/Eficiencia (Fast)**: `gemini-2.5-flash-lite` (Google), `llama-3.2-3b-preview` (Groq), `google/gemma-2-9b-it:free` (OpenRouter).
   - El usuario selecciona un modelo principal según su preferencia (Rapidez/Eficiencia/Equilibrio). Si al interactuar con el agente este falla o da error, el sistema conmuta automáticamente de forma transparente a los otros dos modelos de respaldo (configurados con el mismo RAG y Pseudo-LoRA).

2. **El Cerebro Núcleo / Vigilante de Sesión (Orquestador Asíncrono)**:
   - Se implementará un servicio de monitorización y orquestación inteligente para cada sesión de usuario.
   - **Clasificación Automática**: Al crear una especialización, el Vigilante hace una consulta rápida a un modelo ligero y económico (`gemini-2.5-flash-lite`) para que clasifique la especialidad y asigne de forma óptima los mejores modelos base por provider.
   - **Prevención de Colisión de API Keys**: Controla que en debates de la **Arzor Round Table**, los diferentes agentes activos no hagan llamadas utilizando la misma API key exactamente al mismo milisegundo (distribuye y desfasa los tiempos de llamada).
   - **Gestión de Errores e Hilos**: Captura activamente los errores 429 y conmuta los modelos en la matriz de fallback.

3. **Pool Rotativo de API Keys Descentralizado por Proveedor**:
   - Cada usuario (y el sistema de forma global) puede configurar una lista o pool de API Keys para cada proveedor (Google, Groq, OpenRouter).
   - El backend balanceará el uso de claves para evitar bloqueos por IP y límites de RPM de los proveedores.

4. **Adaptive Instruction Compilation (Motor de Emulated Fine-Tuning)**:
   - Basado en `gemini-2.5-pro`, analiza la descripción informal del usuario y destila las directrices maestras (`system_instructions`) y una matriz de pesos sintéticos (`pseudo_lora_weights` JSONB) con 10-15 ejemplos de interacción de pocas pasadas (*few-shot Q&A*) de alta calidad.

5. **Database-backed RAG (Subida de Archivos)**:
   - El usuario sube PDFs o archivos de texto plano. El backend extrae el texto, lo fragmenta y lo inserta en Supabase (`agent_knowledge`), recuperando contexto mediante búsqueda nativa rápida en Postgres.

6. **Navegación e Integración Dual Protegida**:
   - Arzor AIs Platform será accesible mediante enlace desde Tenzor AI y viceversa.
   - Para entrar a **Tenzor AI** (el chat individual privado original), se requerirá obligatoriamente tu API Key maestra del admin, garantizando la seguridad del portal personal.

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

### 📍 Fase 5: Arzor Round Table (Debates de Agentes)
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

### 📍 Fase 8: Arzor DevCrew CLI (Desarrollo Local Autónomo) [Fase 2 del Proyecto]
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
