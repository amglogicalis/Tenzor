-- ============================================================
-- Migration 001: Platform Core
-- Tablas base: profiles, provider_keys, provider_usage_events
-- Ejecutar manualmente en Supabase SQL Editor
-- ============================================================

-- ------------------------------------------------
-- 1. Tabla profiles
--    Una fila por usuario registrado (vinculada a auth.users)
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS public.profiles (
    id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    username    VARCHAR(50)  UNIQUE NOT NULL,
    display_name VARCHAR(100),
    bio         TEXT,
    avatar_url  TEXT,
    plan        VARCHAR(20)  DEFAULT 'free' NOT NULL,  -- free | pro
    created_at  TIMESTAMPTZ  DEFAULT NOW() NOT NULL,
    updated_at  TIMESTAMPTZ  DEFAULT NOW() NOT NULL
);

-- Auto-actualizar updated_at
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER profiles_updated_at
    BEFORE UPDATE ON public.profiles
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

-- ------------------------------------------------
-- 2. Tabla provider_keys
--    Claves de API por proveedor (globales y de usuario)
--    Nunca se guarda la clave en claro: usar encrypted_key.
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS public.provider_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID REFERENCES public.profiles(id) ON DELETE CASCADE,  -- NULL = clave global del sistema
    provider        TEXT NOT NULL,          -- google | groq | openrouter
    key_label       TEXT NOT NULL,          -- etiqueta legible
    encrypted_key   TEXT NOT NULL,          -- clave cifrada (AES-GCM en backend)
    scope           TEXT DEFAULT 'user' NOT NULL,  -- system | user
    is_active       BOOLEAN DEFAULT TRUE NOT NULL,
    cooldown_until  TIMESTAMPTZ,            -- NULL = disponible ahora
    daily_limit     INTEGER DEFAULT 0,      -- 0 = sin límite
    tokens_used_today INTEGER DEFAULT 0,
    last_reset_at   TIMESTAMPTZ DEFAULT NOW(),
    created_at      TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- ------------------------------------------------
-- 3. Tabla provider_usage_events
--    Log de cada inferencia para auditoría y análisis.
-- ------------------------------------------------
CREATE TABLE IF NOT EXISTS public.provider_usage_events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
    provider_key_id  UUID REFERENCES public.provider_keys(id) ON DELETE SET NULL,
    provider         TEXT NOT NULL,
    model            TEXT NOT NULL,
    status           TEXT NOT NULL,   -- success | rate_limited | error | fallback
    error_code       TEXT,
    tokens_in        INTEGER DEFAULT 0,
    tokens_out       INTEGER DEFAULT 0,
    latency_ms       INTEGER,
    created_at       TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

-- ------------------------------------------------
-- Índices
-- ------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_provider_keys_user       ON public.provider_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_provider_keys_provider   ON public.provider_keys(provider, is_active);
CREATE INDEX IF NOT EXISTS idx_usage_events_user        ON public.provider_usage_events(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_usage_events_key         ON public.provider_usage_events(provider_key_id, created_at DESC);

-- ------------------------------------------------
-- Row Level Security
-- ------------------------------------------------
ALTER TABLE public.profiles             ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.provider_keys        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.provider_usage_events ENABLE ROW LEVEL SECURITY;

-- profiles: cada usuario solo ve y edita su propio perfil
CREATE POLICY "profiles_select_own" ON public.profiles
    FOR SELECT USING (auth.uid() = id);
CREATE POLICY "profiles_update_own" ON public.profiles
    FOR UPDATE USING (auth.uid() = id);
CREATE POLICY "profiles_insert_own" ON public.profiles
    FOR INSERT WITH CHECK (auth.uid() = id);

-- provider_keys: el usuario ve sus propias claves; las globales (user_id IS NULL) las gestiona el admin
CREATE POLICY "provider_keys_select_own" ON public.provider_keys
    FOR SELECT USING (user_id = auth.uid() OR user_id IS NULL);
CREATE POLICY "provider_keys_insert_own" ON public.provider_keys
    FOR INSERT WITH CHECK (user_id = auth.uid());
CREATE POLICY "provider_keys_update_own" ON public.provider_keys
    FOR UPDATE USING (user_id = auth.uid());
CREATE POLICY "provider_keys_delete_own" ON public.provider_keys
    FOR DELETE USING (user_id = auth.uid());

-- usage_events: cada usuario solo ve sus propios eventos
CREATE POLICY "usage_events_select_own" ON public.provider_usage_events
    FOR SELECT USING (user_id = auth.uid());

-- ============================================================
-- ROLLBACK (si necesitas deshacer):
-- DROP TABLE IF EXISTS public.provider_usage_events CASCADE;
-- DROP TABLE IF EXISTS public.provider_keys CASCADE;
-- DROP TABLE IF EXISTS public.profiles CASCADE;
-- DROP FUNCTION IF EXISTS public.set_updated_at CASCADE;
-- ============================================================
