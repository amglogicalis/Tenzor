-- ============================================================
-- Migration 005: Función RPC de búsqueda FTS para RAG por agente
-- Depende de: 003_knowledge.sql
-- Ejecutar manualmente en Supabase SQL Editor
-- ============================================================

-- Función de búsqueda full-text con ts_rank para el RAG por agente
CREATE OR REPLACE FUNCTION public.search_agent_knowledge(
    p_agent_id  UUID,
    p_tsquery   TEXT,
    p_top_k     INT DEFAULT 5
)
RETURNS TABLE (
    id              UUID,
    agent_id        UUID,
    file_id         UUID,
    chunk_index     INT,
    heading         TEXT,
    concept_node    TEXT,
    content         TEXT,
    metadata        JSONB,
    created_at      TIMESTAMPTZ,
    rank            FLOAT4
)
LANGUAGE plpgsql
STABLE
AS $$
BEGIN
    RETURN QUERY
        SELECT
            ak.id,
            ak.agent_id,
            ak.file_id,
            ak.chunk_index,
            ak.heading,
            ak.concept_node,
            ak.content,
            ak.metadata,
            ak.created_at,
            ts_rank(ak.tsv_content, to_tsquery('spanish', p_tsquery)) AS rank
        FROM public.agent_knowledge ak
        WHERE
            ak.agent_id = p_agent_id
            AND ak.tsv_content @@ to_tsquery('spanish', p_tsquery)
        ORDER BY rank DESC
        LIMIT p_top_k;
END;
$$;

-- Comentario para documentar la función
COMMENT ON FUNCTION public.search_agent_knowledge IS
    'Búsqueda full-text en la knowledge base de un agente usando ts_rank. '
    'p_tsquery debe ser una tsquery válida de PostgreSQL (palabras unidas por & | !). '
    'La función respeta las políticas RLS de agent_knowledge.';

-- Función alternativa: búsqueda por keyword directo (más permisiva, para fallback)
CREATE OR REPLACE FUNCTION public.search_agent_knowledge_simple(
    p_agent_id  UUID,
    p_keyword   TEXT,
    p_top_k     INT DEFAULT 5
)
RETURNS TABLE (
    id              UUID,
    agent_id        UUID,
    file_id         UUID,
    chunk_index     INT,
    heading         TEXT,
    content         TEXT,
    metadata        JSONB
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        id, agent_id, file_id, chunk_index, heading, content, metadata
    FROM public.agent_knowledge
    WHERE
        agent_id = p_agent_id
        AND content ILIKE '%' || p_keyword || '%'
    LIMIT p_top_k;
$$;

-- ============================================================
-- ROLLBACK:
-- DROP FUNCTION IF EXISTS public.search_agent_knowledge CASCADE;
-- DROP FUNCTION IF EXISTS public.search_agent_knowledge_simple CASCADE;
-- ============================================================
