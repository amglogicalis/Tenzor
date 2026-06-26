-- ============================================================
-- Migration 002: Custom Agents, Versions, Cache & Round Tables
-- Depende de: 001_platform_core.sql
-- Ejecutar manualmente en Supabase SQL Editor
-- ============================================================

-- ------------------------------------------------
-- 1. custom_agents
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS public.custom_agents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES public.profiles(id) ON DELETE CASCADE NOT NULL,
    name                VARCHAR(100) NOT NULL,
    description         TEXT,
    category            VARCHAR(50)  NOT NULL,       -- dev | data | ops | creative | science | custom
    current_version_id  UUID,                        -- FK añadida tras crear agent_versions
    base_tier           VARCHAR(20)  DEFAULT 'balanced' NOT NULL,  -- fast | balanced | pro
    is_public           BOOLEAN      DEFAULT FALSE NOT NULL,
    level               INTEGER      DEFAULT 1 NOT NULL,
    experience          INTEGER      DEFAULT 0 NOT NULL,
    created_at          TIMESTAMPTZ  DEFAULT NOW() NOT NULL,
    updated_at          TIMESTAMPTZ  DEFAULT NOW() NOT NULL,
    deleted_at          TIMESTAMPTZ                  -- soft-delete
);

CREATE TRIGGER custom_agents_updated_at
    BEFORE UPDATE ON public.custom_agents
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ------------------------------------------------
-- 2. agent_versions  (AFT profiles versionados)
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS public.agent_versions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id            UUID REFERENCES public.custom_agents(id) ON DELETE CASCADE NOT NULL,
    version             INTEGER NOT NULL,
    system_instructions TEXT    NOT NULL,
    behavior_examples   JSONB   NOT NULL DEFAULT '[]'::jsonb,
    style_rules         JSONB   NOT NULL DEFAULT '{}'::jsonb,
    domain_constraints  JSONB   NOT NULL DEFAULT '{}'::jsonb,
    retrieval_profile   JSONB   NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    UNIQUE(agent_id, version)
);

-- Ahora podemos añadir la FK que apunta a agent_versions
ALTER TABLE public.custom_agents
    ADD CONSTRAINT fk_current_version
    FOREIGN KEY (current_version_id) REFERENCES public.agent_versions(id)
    ON DELETE SET NULL;

-- ------------------------------------------------
-- 3. agent_cache
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS public.agent_cache (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id       UUID REFERENCES public.custom_agents(id) ON DELETE CASCADE NOT NULL,
    query_hash     TEXT    NOT NULL,
    query          TEXT    NOT NULL,
    response       TEXT    NOT NULL,
    user_feedback  INTEGER DEFAULT 0,   -- +1 positivo / -1 negativo / 0 neutro
    times_used     INTEGER DEFAULT 1   NOT NULL,
    last_used_at   TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    UNIQUE(agent_id, query_hash)
);

-- ------------------------------------------------
-- 4. round_tables  &  round_table_members
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS public.round_tables (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES public.profiles(id) ON DELETE CASCADE NOT NULL,
    name        VARCHAR(100) NOT NULL,
    description TEXT,
    topic       TEXT,
    status      TEXT DEFAULT 'idle' NOT NULL,  -- idle | running | done
    created_at  TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TRIGGER round_tables_updated_at
    BEFORE UPDATE ON public.round_tables
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

CREATE TABLE IF NOT EXISTS public.round_table_members (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    table_id    UUID REFERENCES public.round_tables(id) ON DELETE CASCADE NOT NULL,
    agent_id    UUID REFERENCES public.custom_agents(id) ON DELETE CASCADE NOT NULL,
    turn_order  INTEGER DEFAULT 0 NOT NULL,
    UNIQUE(table_id, agent_id)
);

-- ------------------------------------------------
-- Índices
-- ------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_custom_agents_user     ON public.custom_agents(user_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_custom_agents_public   ON public.custom_agents(is_public) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_agent_versions_agent   ON public.agent_versions(agent_id, version DESC);
CREATE INDEX IF NOT EXISTS idx_agent_cache_agent      ON public.agent_cache(agent_id, query_hash);
CREATE INDEX IF NOT EXISTS idx_round_tables_user      ON public.round_tables(user_id, status);

-- ------------------------------------------------
-- Row Level Security
-- ------------------------------------------------
ALTER TABLE public.custom_agents        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_versions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_cache          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.round_tables         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.round_table_members  ENABLE ROW LEVEL SECURITY;

-- custom_agents
CREATE POLICY "agents_select_own_or_public" ON public.custom_agents
    FOR SELECT USING (user_id = auth.uid() OR is_public = TRUE);
CREATE POLICY "agents_insert_own" ON public.custom_agents
    FOR INSERT WITH CHECK (user_id = auth.uid());
CREATE POLICY "agents_update_own" ON public.custom_agents
    FOR UPDATE USING (user_id = auth.uid());
CREATE POLICY "agents_delete_own" ON public.custom_agents
    FOR DELETE USING (user_id = auth.uid());

-- agent_versions: accesibles si el agente es tuyo o es público
CREATE POLICY "agent_versions_select" ON public.agent_versions
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.custom_agents a
            WHERE a.id = agent_id AND (a.user_id = auth.uid() OR a.is_public = TRUE)
        )
    );
CREATE POLICY "agent_versions_insert" ON public.agent_versions
    FOR INSERT WITH CHECK (
        EXISTS (SELECT 1 FROM public.custom_agents a WHERE a.id = agent_id AND a.user_id = auth.uid())
    );

-- agent_cache: solo el dueño del agente
CREATE POLICY "agent_cache_select_own" ON public.agent_cache
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM public.custom_agents a WHERE a.id = agent_id AND a.user_id = auth.uid())
    );

-- round_tables
CREATE POLICY "round_tables_select_own" ON public.round_tables
    FOR SELECT USING (user_id = auth.uid());
CREATE POLICY "round_tables_insert_own" ON public.round_tables
    FOR INSERT WITH CHECK (user_id = auth.uid());
CREATE POLICY "round_tables_update_own" ON public.round_tables
    FOR UPDATE USING (user_id = auth.uid());
CREATE POLICY "round_tables_delete_own" ON public.round_tables
    FOR DELETE USING (user_id = auth.uid());

-- round_table_members
CREATE POLICY "rtm_select_own" ON public.round_table_members
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM public.round_tables rt WHERE rt.id = table_id AND rt.user_id = auth.uid())
    );
CREATE POLICY "rtm_insert_own" ON public.round_table_members
    FOR INSERT WITH CHECK (
        EXISTS (SELECT 1 FROM public.round_tables rt WHERE rt.id = table_id AND rt.user_id = auth.uid())
    );
CREATE POLICY "rtm_delete_own" ON public.round_table_members
    FOR DELETE USING (
        EXISTS (SELECT 1 FROM public.round_tables rt WHERE rt.id = table_id AND rt.user_id = auth.uid())
    );

-- ============================================================
-- ROLLBACK:
-- DROP TABLE IF EXISTS public.round_table_members CASCADE;
-- DROP TABLE IF EXISTS public.round_tables CASCADE;
-- DROP TABLE IF EXISTS public.agent_cache CASCADE;
-- DROP TABLE IF EXISTS public.agent_versions CASCADE;
-- ALTER TABLE public.custom_agents DROP CONSTRAINT IF EXISTS fk_current_version;
-- DROP TABLE IF EXISTS public.custom_agents CASCADE;
-- ============================================================
