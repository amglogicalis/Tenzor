# Plan de Implementacion: Arzor AIs Platform sobre Tenzor

Este documento define la evolucion de Tenzor hacia **Arzor AIs Platform**: una plataforma multiusuario para crear agentes de IA especializados, alimentarlos con documentos propios, compartirlos en una biblioteca publica y coordinar debates multi-agente mediante **Arzor Round Table**.

Tenzor AI actual debe mantenerse como chat tecnico privado y API compatible con OpenAI. Arzor se implementara como una subplataforma separada, accesible desde `/platform`, sin romper los endpoints existentes de Tenzor.

---

## Vision del Producto

Arzor AIs Platform debe permitir:

- Registro/login de usuarios.
- Creacion de agentes personalizados con instrucciones, ejemplos y documentos.
- RAG por agente con documentos PDF, TXT, MD y codigo.
- Biblioteca publica de agentes.
- Chat individual con agentes personalizados.
- Fallback multi-proveedor: Google, Groq y OpenRouter.
- Pool de API keys por proveedor, con claves globales y claves del usuario.
- Control de 429, cooldowns, backoff y aislamiento de cuotas.
- Debates multi-agente en Arzor Round Table.
- En una fase posterior, CLI local para generar proyectos con equipos de agentes.

---

## Principio Tecnico: AFT / Adaptive Fractal Tuning

Arzor utilizara **AFT (Adaptive Fractal Tuning)** como modelo propio de refinamiento de agentes. AFT no es fine-tuning de pesos ni LoRA literal: es una capa de especializacion dinamica que compila perfiles de agente, recupera contexto, aplica memoria versionada y ejecuta evaluacion continua para adaptar el comportamiento del modelo sin modificar sus pesos.

El termino "fractal" indica que el mismo patron de ajuste se repite por capas:

- Capa global de Tenzor.
- Capa de plataforma Arzor.
- Capa del agente.
- Capa del usuario.
- Capa de sesion.
- Capa de tarea.
- Capa de evidencia/RAG.
- Capa de evaluacion y feedback.

Cada agente se representa mediante un **AFT Profile** versionado:

- `system_instructions`: prompt maestro compilado.
- `behavior_examples`: 10-15 ejemplos few-shot de alta calidad.
- `style_rules`: reglas de tono, limites, formato y decision.
- `domain_constraints`: alcance tecnico, restricciones y fuentes preferidas.
- `retrieval_profile`: estrategia RAG del agente.
- `tool_policy`: que herramientas o proveedores puede usar.
- `memory_hints`: cache y aprendizajes aprobados por el usuario.
- `evaluation_suite`: pruebas que validan si el agente conserva su comportamiento esperado.

AFT busca conseguir una especializacion muy fiel sin entrenar pesos, combinando:

- Buen prompt maestro.
- Few-shot consistente.
- RAG de calidad.
- Memoria verificada.
- Versionado y rollback.
- Feedback del usuario.
- Evaluaciones automaticas.
- Sintesis controlada de nuevas versiones del perfil.

AFT no debe presentarse como LoRA real ni como fine-tuning de pesos. Debe presentarse como un sistema de especializacion operacional, auditable y reversible. Si un agente acumula suficientes ejemplos validados, AFT podra exportar un dataset para fine-tuning real en una fase posterior.

---

## Arquitectura de Alto Nivel

### Modulos Backend

- `app/routers/platform_auth.py`: autenticacion de usuarios de plataforma.
- `app/routers/platform_agents.py`: CRUD de agentes.
- `app/routers/platform_knowledge.py`: subida y gestion de documentos.
- `app/routers/platform_chat.py`: chat con agentes personalizados.
- `app/routers/round_table.py`: debates multi-agente.
- `app/services/platform_auth_service.py`: sesiones, perfiles y permisos.
- `app/services/agent_service.py`: agentes, versiones y visibilidad.
- `app/services/instruction_compiler_service.py`: compilacion de perfiles.
- `app/services/provider_router_service.py`: routing Google/Groq/OpenRouter.
- `app/services/provider_key_pool_service.py`: pools, cooldowns y rotacion.
- `app/services/platform_rag_service.py`: RAG por agente.
- `app/services/round_table_service.py`: orquestacion de debates.
- `app/services/cooldown_service.py`: control de 429 y backoff.

### Separacion de Productos

- **Tenzor AI actual**: chat tecnico privado, API keys, Nova/Meteor, RAG interno.
- **Arzor Platform**: plataforma multiusuario, agentes, documentos, biblioteca.
- **Arzor Round Table**: debates multi-agente.
- **Arzor DevCrew CLI**: cliente local posterior para generar proyectos.

---

## Expansion Manual en Supabase

La expansion de base de datos debe hacerse de forma manual y controlada por el usuario desde Supabase.

Flujo recomendado:

1. Codex genera archivos SQL de migracion versionados, por ejemplo:
   - `supabase/migrations/001_platform_core.sql`
   - `supabase/migrations/002_agents.sql`
   - `supabase/migrations/003_knowledge.sql`
   - `supabase/migrations/004_provider_keys.sql`
2. El usuario revisa el SQL.
3. El usuario lo ejecuta manualmente en Supabase SQL Editor o mediante Supabase CLI si lo prefiere.
4. Codex no debe modificar produccion automaticamente sin confirmacion explicita.
5. Cada fase debe incluir SQL reversible o, como minimo, instrucciones de rollback.

Requisitos obligatorios:

- Row Level Security activado en tablas multiusuario.
- Politicas RLS por `user_id`.
- Indices adecuados.
- `created_at`, `updated_at` y, cuando aplique, `deleted_at`.
- No guardar API keys en texto plano si van a ser persistentes.
- Separar claves globales del sistema y claves aportadas por usuarios.

---

## Esquema Base Propuesto

El esquema inicial debe evolucionar el plan original con tablas adicionales:

```sql
CREATE TABLE profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    username VARCHAR(50) UNIQUE NOT NULL,
    display_name VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TABLE custom_agents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    category VARCHAR(50) NOT NULL,
    current_version_id UUID,
    base_tier VARCHAR(20) DEFAULT 'balanced' NOT NULL,
    is_public BOOLEAN DEFAULT FALSE NOT NULL,
    level INTEGER DEFAULT 1 NOT NULL,
    experience INTEGER DEFAULT 0 NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    deleted_at TIMESTAMPTZ
);

CREATE TABLE agent_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES custom_agents(id) ON DELETE CASCADE NOT NULL,
    version INTEGER NOT NULL,
    system_instructions TEXT NOT NULL,
    behavior_examples JSONB NOT NULL,
    style_rules JSONB NOT NULL DEFAULT '{}'::jsonb,
    domain_constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
    retrieval_profile JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    UNIQUE(agent_id, version)
);

CREATE TABLE agent_files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES custom_agents(id) ON DELETE CASCADE NOT NULL,
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
    filename TEXT NOT NULL,
    content_type TEXT,
    storage_path TEXT,
    status TEXT DEFAULT 'processing' NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TABLE agent_knowledge (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES custom_agents(id) ON DELETE CASCADE NOT NULL,
    file_id UUID REFERENCES agent_files(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    heading TEXT,
    concept_node TEXT,
    related_to TEXT,
    content TEXT NOT NULL,
    tsv_content TSVECTOR,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TABLE provider_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    key_label TEXT NOT NULL,
    encrypted_key TEXT NOT NULL,
    scope TEXT DEFAULT 'user' NOT NULL,
    is_active BOOLEAN DEFAULT TRUE NOT NULL,
    cooldown_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TABLE provider_usage_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE SET NULL,
    provider_key_id UUID REFERENCES provider_keys(id) ON DELETE SET NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    error_code TEXT,
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    latency_ms INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TABLE chat_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
    agent_id UUID REFERENCES custom_agents(id) ON DELETE SET NULL,
    title TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TABLE chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID REFERENCES chat_sessions(id) ON DELETE CASCADE NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TABLE agent_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES custom_agents(id) ON DELETE CASCADE NOT NULL,
    query_hash TEXT NOT NULL,
    query TEXT NOT NULL,
    response TEXT NOT NULL,
    user_feedback INTEGER DEFAULT 0,
    times_used INTEGER DEFAULT 1 NOT NULL,
    last_used_at TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    UNIQUE(agent_id, query_hash)
);

CREATE TABLE round_tables (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES profiles(id) ON DELETE CASCADE NOT NULL,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TABLE round_table_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_id UUID REFERENCES round_tables(id) ON DELETE CASCADE NOT NULL,
    agent_id UUID REFERENCES custom_agents(id) ON DELETE CASCADE NOT NULL,
    turn_order INTEGER DEFAULT 0 NOT NULL
);
```

---

## Orden Correcto de Implementacion

### Fase 0: Base Tecnica y Migraciones

Objetivo:
Preparar el proyecto para crecer sin romper Tenzor AI actual.

Componentes:

- Definir estructura de routers/services/modelos.
- Crear carpeta `supabase/migrations`.
- Generar SQL de tablas base.
- Documentar variables de entorno.
- Definir contratos API iniciales.

Verificacion:

- Tests existentes siguen pasando.
- SQL revisado manualmente por el usuario antes de ejecutarse en Supabase.

---

### Fase 1: Auth, Profiles y Seguridad Multiusuario

Objetivo:
Habilitar login/registro y aislamiento por usuario.

Componentes:

- `app/routers/platform_auth.py`
- `app/services/platform_auth_service.py`
- Integracion con Supabase Auth.
- RLS en `profiles`.
- Sesion por cookie segura o bearer token de Supabase.

Verificacion:

- Registro y login de usuario.
- Usuario A no puede leer datos de usuario B.
- Tests de permisos.

---

### Fase 2: CRUD de Agentes Personalizados

Objetivo:
Permitir crear, editar, listar, borrar y publicar agentes.

Componentes:

- `app/routers/platform_agents.py`
- `app/services/agent_service.py`
- Tablas `custom_agents` y `agent_versions`.
- Versionado del perfil de agente.

Verificacion:

- Crear agente privado.
- Publicar agente.
- Crear nueva version sin perder la anterior.

---

### Fase 3: AFT Compiler / Adaptive Fractal Tuning

Objetivo:
Compilar una descripcion informal en un perfil estructurado.

Componentes:

- `instruction_compiler_service.py`
- Salida Pydantic validada:
  - `system_instructions`
  - `behavior_examples`
  - `style_rules`
  - `domain_constraints`
  - `retrieval_profile`
- Reintentos con backoff.
- Validacion de que haya 10-15 ejemplos utiles.

Verificacion:

- Test unitario con un agente tecnico.
- La salida debe ser JSON valido.
- No guardar perfiles incompletos.

---

### Fase 4: Provider Router, API Key Pools y Anti-429

Objetivo:
Crear un motor comun para enrutar inferencias a Google, Groq y OpenRouter.

Componentes:

- `provider_router_service.py`
- `provider_key_pool_service.py`
- `cooldown_service.py`
- Tabla `provider_keys`.
- Tabla `provider_usage_events`.
- Fallback por tier:
  - `pro`
  - `balanced`
  - `fast`

Verificacion:

- Simular 429 en una key.
- Marcar cooldown.
- Reintentar con otro provider/key.
- Registrar uso y error.

---

### Fase 5: RAG por Agente con Subida de Archivos

Objetivo:
Permitir subir documentos y consultarlos desde el agente.

Componentes:

- `platform_knowledge.py`
- `platform_rag_service.py`
- Tablas `agent_files` y `agent_knowledge`.
- Extraccion PDF/TXT/MD.
- Chunking.
- `tsvector` e indices.

Verificacion:

- Subir PDF de prueba.
- Comprobar chunks.
- Consulta recupera contexto correcto.

---

### Fase 6: Chat con Agentes Personalizados

Objetivo:
Unir agente + instruction pack + RAG + provider router.

Componentes:

- `platform_chat.py`
- `chat_sessions`
- `chat_messages`
- Inyeccion de contexto.
- Cache opcional.

Verificacion:

- Chatear con agente privado.
- Usar RAG si hay documentos.
- Fallar de forma controlada si no hay claves disponibles.

---

### Fase 7: Cache, Feedback y Versionado de Evolucion

Objetivo:
Ahorrar tokens y permitir mejora controlada.

Componentes:

- `agent_cache`.
- Feedback +1/-1.
- Re-sintesis manual o asistida, nunca silenciosa.
- Nueva version del agente para cada cambio importante.

Verificacion:

- Pregunta repetida se sirve desde cache.
- Feedback negativo crea propuesta de nueva version, no modifica el agente activo sin aprobacion.

---

### Fase 8: Arzor Round Table

Objetivo:
Orquestar debates multi-agente.

Componentes:

- `round_table.py`
- `round_table_service.py`
- Cola secuencial o turnos controlados.
- Cooldown entre turnos.
- Limite de tokens por ronda.

Verificacion:

- Debate entre Programador y Tester.
- Output coherente.
- Sin llamadas simultaneas que saturen cuotas.

---

### Fase 9: UI Platform

Objetivo:
Construir `/platform` como interfaz multiusuario.

Componentes:

- Login/register.
- Biblioteca de agentes.
- Editor de agente.
- Subida de documentos.
- Chat por agente.
- Vista de cooldown.
- Panel de provider keys.

Verificacion:

- Flujo completo: registrarse, crear agente, subir documento, chatear.

---

### Fase 10: Arzor DevCrew CLI

Objetivo:
CLI local para planificar y escribir proyectos usando agentes del servidor.

Componentes:

- `cli/tenzor_crew.py`
- `/platform/crew/plan`
- `/platform/crew/write`
- Backoff local.
- Debouncer cliente-servidor.
- Contexto por stubs.

Verificacion:

- Generar microservicio FastAPI completo.
- Crear estructura de archivos.
- No saturar proveedores.

---

## Instruccion de Arranque Rapido

Cuando el usuario diga:

**"pon el plan implementation_plan.md de la raiz sobre tenzor platform en marcha"**

El agente debe:

1. Crear `task.md` con checklist por fases.
2. Empezar por Fase 0.
3. Generar migraciones SQL, pero no ejecutarlas automaticamente en Supabase.
4. Pedir confirmacion antes de cualquier cambio manual en Supabase o accion irreversible.
5. Implementar fase por fase con tests.
6. Mantener Tenzor AI actual funcionando.
