-- ============================================================
-- Migration 004: Chat Sessions & Messages
-- Depende de: 001 y 002
-- Ejecutar manualmente en Supabase SQL Editor
-- ============================================================

-- ------------------------------------------------
-- 1. chat_sessions
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS public.chat_sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES public.profiles(id) ON DELETE CASCADE NOT NULL,
    agent_id    UUID REFERENCES public.custom_agents(id) ON DELETE SET NULL,
    title       TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW() NOT NULL,
    updated_at  TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE TRIGGER chat_sessions_updated_at
    BEFORE UPDATE ON public.chat_sessions
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ------------------------------------------------
-- 2. chat_messages
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS public.chat_messages (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID REFERENCES public.chat_sessions(id) ON DELETE CASCADE NOT NULL,
    role        TEXT NOT NULL,      -- user | assistant | system
    content     TEXT NOT NULL,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,  -- provider, model, tokens, latency, cached
    created_at  TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- ------------------------------------------------
-- Índices
-- ------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user   ON public.chat_sessions(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_agent  ON public.chat_sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON public.chat_messages(session_id, created_at ASC);

-- ------------------------------------------------
-- Row Level Security
-- ------------------------------------------------
ALTER TABLE public.chat_sessions  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_messages  ENABLE ROW LEVEL SECURITY;

-- chat_sessions
CREATE POLICY "chat_sessions_select_own" ON public.chat_sessions
    FOR SELECT USING (user_id = auth.uid());
CREATE POLICY "chat_sessions_insert_own" ON public.chat_sessions
    FOR INSERT WITH CHECK (user_id = auth.uid());
CREATE POLICY "chat_sessions_update_own" ON public.chat_sessions
    FOR UPDATE USING (user_id = auth.uid());
CREATE POLICY "chat_sessions_delete_own" ON public.chat_sessions
    FOR DELETE USING (user_id = auth.uid());

-- chat_messages: accesible si la sesión es tuya
CREATE POLICY "chat_messages_select_own" ON public.chat_messages
    FOR SELECT USING (
        EXISTS (SELECT 1 FROM public.chat_sessions s WHERE s.id = session_id AND s.user_id = auth.uid())
    );
CREATE POLICY "chat_messages_insert_own" ON public.chat_messages
    FOR INSERT WITH CHECK (
        EXISTS (SELECT 1 FROM public.chat_sessions s WHERE s.id = session_id AND s.user_id = auth.uid())
    );

-- ============================================================
-- ROLLBACK:
-- DROP TABLE IF EXISTS public.chat_messages CASCADE;
-- DROP TABLE IF EXISTS public.chat_sessions CASCADE;
-- ============================================================
