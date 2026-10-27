-- Run once in the Supabase SQL Editor before using device registration or digest sending.
-- No existing news tables are altered by this migration.

CREATE TABLE IF NOT EXISTS public.devices (
    token TEXT PRIMARY KEY,
    platform TEXT NOT NULL CHECK (platform IN ('ios', 'android')),
    lang TEXT NOT NULL CHECK (lang IN ('ar', 'en')),
    timezone TEXT NOT NULL DEFAULT 'Asia/Amman',
    digest_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    digest_hour_local SMALLINT NOT NULL DEFAULT 8 CHECK (digest_hour_local BETWEEN 0 AND 23),
    categories TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    last_digest_sent_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS devices_digest_due_idx
    ON public.devices (digest_enabled, digest_hour_local, last_digest_sent_date)
    WHERE digest_enabled = TRUE;
