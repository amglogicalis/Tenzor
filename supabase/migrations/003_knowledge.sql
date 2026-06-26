-- ============================================================
-- Migration 003: Knowledge Base (RAG por Agente)
-- Depende de: 001 y 002
-- Ejecutar manualmente en Supabase SQL Editor
-- ============================================================

-- ------------------------------------------------
-- 1. agent_files
--    Metadatos de los archivos subidos por el usuario.
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS public.agent_files (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID REFERENCES public.custom_agents(id) ON DELETE CASCADE NOT NULL,
    user_id         UUID REFERENCES public.profiles(id) ON DELETE CASCADE NOT NULL,
    filename        TEXT    NOT NULL,
    content_type    TEXT,                             -- application/pdf | text/plain | text/markdown
    storage_path    TEXT,                             -- ruta en Supabase Storage
    file_size_bytes INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'processing' NOT NULL,  -- processing | ready | error
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- ------------------------------------------------
-- 2. agent_knowledge
--    Chunks extraídos de los archivos para búsqueda full-text.
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS public.agent_knowledge (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID REFERENCES public.custom_agents(id) ON DELETE CASCADE NOT NULL,
    file_id         UUID REFERENCES public.agent_files(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    heading         TEXT,           -- encabezado del bloque, si existe
    concept_node    TEXT,           -- etiqueta semántica (ej: "arquitectura", "API")
    related_to      TEXT,           -- relaciones entre chunks (opcional)
    content         TEXT    NOT NULL,
    tsv_content     TSVECTOR,       -- índice full-text generado
    metadata        JSONB   NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- ------------------------------------------------
-- 3. Trigger para mantener tsv_content actualizado
-- ------------------------------------------------
CREATE OR REPLACE FUNCTION public.update_knowledge_tsv()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.tsv_content = to_tsvector('spanish', COALESCE(NEW.heading, '') || ' ' || COALESCE(NEW.content, ''));
    RETURN NEW;
END;
$$;

CREATE TRIGGER agent_knowledge_tsv_update
    BEFORE INSERT OR UPDATE ON public.agent_knowledge
    FOR EACH ROW EXECUTE FUNCTION public.update_knowledge_tsv();

-- ------------------------------------------------
-- Índices
-- ------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_agent_files_agent         ON public.agent_files(agent_id, status);
CREATE INDEX IF NOT EXISTS idx_agent_files_user          ON public.agent_files(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_knowledge_agent     ON public.agent_knowledge(agent_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_agent_knowledge_file      ON public.agent_knowledge(file_id);
CREATE INDEX IF NOT EXISTS idx_agent_knowledge_tsv       ON public.agent_knowledge USING GIN(tsv_content);

-- ------------------------------------------------
-- Row Level Security
-- ------------------------------------------------
ALTER TABLE public.agent_files      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.agent_knowledge  ENABLE ROW LEVEL SECURITY;

-- agent_files
CREATE POLICY "agent_files_select_own" ON public.agent_files
    FOR SELECT USING (user_id = auth.uid());
CREATE POLICY "agent_files_insert_own" ON public.agent_files
    FOR INSERT WITH CHECK (user_id = auth.uid());
CREATE POLICY "agent_files_delete_own" ON public.agent_files
    FOR DELETE USING (user_id = auth.uid());

-- agent_knowledge: accesible si el agente es tuyo o es público
CREATE POLICY "knowledge_select" ON public.agent_knowledge
    FOR SELECT USING (
        EXISTS (
            SELECT 1 FROM public.custom_agents a
            WHERE a.id = agent_id AND (a.user_id = auth.uid() OR a.is_public = TRUE)
        )
    );
CREATE POLICY "knowledge_insert_own" ON public.agent_knowledge
    FOR INSERT WITH CHECK (
        EXISTS (SELECT 1 FROM public.custom_agents a WHERE a.id = agent_id AND a.user_id = auth.uid())
    );
CREATE POLICY "knowledge_delete_own" ON public.agent_knowledge
    FOR DELETE USING (
        EXISTS (SELECT 1 FROM public.custom_agents a WHERE a.id = agent_id AND a.user_id = auth.uid())
    );

-- ============================================================
-- ROLLBACK:
-- DROP TABLE IF EXISTS public.agent_knowledge CASCADE;
-- DROP TABLE IF EXISTS public.agent_files CASCADE;
-- DROP FUNCTION IF EXISTS public.update_knowledge_tsv CASCADE;
-- ============================================================
