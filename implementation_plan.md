# Plan de Implementación: Tenzor AI Platform

Este plan detalla la evolución de **Tenzor** para albergar una subplataforma llamada **Tenzor AI Platform** (o **Tenzor Multi AIs Platform**), un entorno donde cualquier usuario puede registrarse con usuario/contraseña, especializar una IA con instrucciones y documentos propios (PDFs, TXT, MD), compartirla en una biblioteca pública y organizar debates colaborativos (**Tenzor Round Table**) sin costes.

---

## 💡 Concepto de Especialización Híbrida y Serverless

Para dar soporte a múltiples usuarios sin consumir tus créditos de Google Cloud en GPUs encendidas 24/7 y evitar bloqueos por rate-limit (429), utilizaremos:
1. **Arquitectura BYOK (Bring Your Own Key) Descentralizada**:
   - Los usuarios guardan de forma segura sus propias API Keys de Gemini y Groq desde el modal de Ajustes en el frontend (almacenadas en `localStorage` por privacidad).
   - Estas llaves se envían de forma dinámica en las cabeceras de cada petición al backend.
   - Toda la inferencia pesada (chats de agentes, debates de mesas redondas y emulaciones de tuning) se consume directamente contra las cuotas gratuitas e individuales de cada usuario, evitando costes y centralización de rate-limits en tu servidor.
2. **Adaptive Instruction Compilation**: Un modelo avanzado (`gemini-2.5-pro`) destila y optimiza la descripción que da el usuario para generar un *System Prompt* estructurado con ejemplos few-shot específicos del rol (cocina, baile, IT, etc.).
3. **Database-backed RAG (Subida de Archivos)**:
   - El usuario sube PDFs o archivos de texto plano desde la interfaz.
   - El backend extrae el texto, lo divide en fragmentos y los inserta en Supabase (`agent_knowledge`).
   - Usamos la búsqueda de texto nativa de Postgres (`@@ to_tsquery`) para recuperar los fragmentos relevantes.
4. **Enrutamiento Dinámico de Modelos**:
   - **Generales / Ocio**: `gemini-2.5-flash-lite` (gratuito, límites de cuota amplios).
   - **Lógica / Programación / Rol Técnico**: `llama-3.3-70b-instruct` o `gemini-2.5-pro`.
5. **Resiliencia ante Errores 429 (Límites de API)**:
   - **Cola de Inferencia Asíncrona (`asyncio.Queue`)**: Todas las peticiones de debates y chats grupales se procesan secuencialmente a través de un limitador de tasa de peticiones del lado del servidor para evitar ráfagas simultáneas.
   - **Pool Rotativo de Keys con Estado de Cooldown**: El backend rotará a través de múltiples API Keys gratuitas. Si una clave recibe un error 429, se marca "on cooldown" por 60 segundos y se usa la siguiente.
   - **Compresión de Contexto**: En debates multigente, solo pasamos la pregunta base del usuario y los dos últimos turnos de conversación de forma deslizable para minimizar el consumo de tokens y maximizar la velocidad.


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

### 📍 Fase 2: El Sintetizador de Agentes (Pseudo-LoRA)
* **Objetivo**: Programar el backend de creación de IAs que toma la descripción informal del usuario y genera de forma asíncrona la personalidad compilada (`system_instructions`) y la matriz de pesos sintéticos (`pseudo_lora_weights` JSONB).
* **Componentes**:
  - `app/routers/platform_agents.py` [NEW] (Ruta `POST /platform/agents`).
  - Lógica de Meta-Prompting con `gemini-2.5-pro` para generar el JSONB de ejemplos Q&A de interacción.
* **Verificación**:
  - Test unitario: Crear un agente y verificar que el campo `pseudo_lora_weights` contiene un array válido con 10 ejemplos de Q&A consistentes.

### 📍 Fase 3: RAG con Subida de Archivos y Mapa Sináptico
* **Objetivo**: Integrar la subida de PDFs/Textos desde la UI, extraer el contenido, segmentar y construir el grafo de relaciones conceptuales en la base de datos.
* **Componentes**:
  - Integrar lector de PDFs en FastAPI.
  - Generador de grafos conceptuales: Extraer entidades clave y asociarlas (`concept_node` -> `related_to`).
  - Lógica de búsqueda semántica/léxica nativa en Postgres.
* **Verificación**:
  - Subir un PDF de prueba de 10 páginas, verificar que se guarda indexado en Supabase y que las búsquedas a través del chat recuperan los chunks correspondientes.

### 📍 Fase 4: Chat Personalizado con Inferencia de Atención Dinámica
* **Objetivo**: Actualizar el motor de chat para agentes personalizados, calculando la relevancia de los pesos sintéticos de comportamiento y los chunks de RAG para inyectarlos en el prompt en tiempo real.
* **Componentes**:
  - `app/routers/platform_chat.py` [NEW] (Ruta `/platform/chat`).
  - Lógica de ordenamiento semántico rápido en memoria para los pesos Pseudo-LoRA.
* **Verificación**:
  - Realizar 10 preguntas a un agente especializado en cocina y certificar que todas sus respuestas contienen el tono y formato dictado por los ejemplos de su matriz sintética.

### 📍 Fase 5: Tenzor Round Table (Debates de Agentes)
* **Objetivo**: Diseñar la lógica de orquestación de discusiones grupales.
* **Componentes**:
  - `app/routers/round_table.py` [NEW]
  - Bucle secuencial de inferencia de debates: Agente A responde -> Agente B recibe la respuesta previa y la analiza -> Agente C consolida.
* **Verificación**:
  - Iniciar una Mesa Redonda con un Programador y un Tester sobre un fragmento de código, validando que el output final sea una conversación coherente entre ambos agentes.

### 📍 Fase 6: Caché de Memoria y Evolución Autónoma
* **Objetivo**: Programar el sistema de ahorro de tokens mediante la comprobación del historial y el auto-ajuste de comportamiento basado en el feedback del usuario.
* **Componentes**:
  - Lógica de interceptación en chat: Verificar `agent_cache` antes de llamar a las APIs.
  - Tarea en segundo plano para re-sintetizar pesos Pseudo-LoRA si un agente recibe retroalimentación negativa (-1) en un chat.
* **Verificación**:
  - Enviar una pregunta idéntica dos veces. Verificar mediante los logs del servidor que la segunda llamada se sirve directamente desde la base de datos consumiendo 0 tokens de API.

### 📍 Fase 7: Interfaz Visual "Neural Sandbox Console" y Pool de Keys
* **Objetivo**: Diseñar y maquetar la web en `/platform` (`platform.html`, CSS, JS) con temática Sci-Fi, el lienzo animado del Mapa Sináptico en Canvas, las Salas de Debate y activar la rotación de API Keys en el backend.
* **Componentes**:
  - Vista del panel de control de agentes (Studio & Marketplace).
  - Canvas dinámico en JS para renderizado de grafos conceptuales mediante fuerzas físicas.
  - Implementación del pool rotatorio de API keys en `ai_service.py` con control de errores 429.
* **Verificación**:
  - Test de estrés: 20 peticiones concurrentes para forzar límites y confirmar que la rotación de claves mantiene el servicio activo sin fallar.

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

