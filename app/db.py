"""
db.py
Clientes Supabase centralizados para la plataforma Arzor.

- `supabase_anon`    → cliente con anon key (para Auth sign_up/sign_in)
- `supabase_admin`   → cliente con service_role key (bypass RLS, operaciones de backend)

Uso recomendado en todos los servicios de plataforma:
    from app.db import supabase_admin as sb
"""
import logging
from supabase import create_client, Client
from app import config

logger = logging.getLogger(__name__)

supabase_anon: Client = None   # type: ignore
supabase_admin: Client = None  # type: ignore

if config.SUPABASE_URL and config.SUPABASE_KEY:
    try:
        supabase_anon = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
        logger.info("db: cliente Supabase anon inicializado.")
    except Exception as e:
        logger.error(f"db: error cliente anon: {e}")

if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
    try:
        supabase_admin = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
        logger.info("db: cliente Supabase admin (service_role) inicializado.")
    except Exception as e:
        logger.warning(f"db: error cliente admin: {e}")
        supabase_admin = supabase_anon  # fallback gracioso
else:
    logger.warning("db: SUPABASE_SERVICE_KEY no configurada — usando anon como fallback (RLS activo).")
    supabase_admin = supabase_anon
