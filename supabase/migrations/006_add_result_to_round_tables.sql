-- ============================================================
-- Migration 006: Add result column to round_tables
-- ============================================================

ALTER TABLE public.round_tables ADD COLUMN IF NOT EXISTS result TEXT;
