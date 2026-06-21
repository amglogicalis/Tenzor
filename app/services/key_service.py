import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from supabase import create_client, Client
from app import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class KeyService:
    def __init__(self):
        self.supabase: Optional[Client] = None
        self.dev_mode = True

        if config.SUPABASE_URL and config.SUPABASE_KEY:
            try:
                self.supabase = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
                self.dev_mode = False
                logger.info("Cliente Supabase inicializado correctamente. Modo producción activo.")
            except Exception as e:
                logger.error(f"Error inicializando Supabase: {e}. Se usará modo desarrollo.")
        else:
            logger.warning("SUPABASE_URL o SUPABASE_KEY faltantes. La API funcionará en MODO DESARROLLO (acepta cualquier API key que comience con 'tenzor-').")

    def validate_key(self, api_key: str) -> Dict[str, Any]:
        """
        Valida una API key y devuelve información sobre ella.
        Lanza ValueError si la clave es inválida o ha superado el límite.
        """
        if not api_key:
            raise ValueError("API Key faltante en la petición.")
        
        api_key = api_key.strip()

        if self.dev_mode:
            # En modo desarrollo, aceptamos cualquier clave que empiece por 'tenzor-'
            if api_key.startswith("tenzor-"):
                return {
                    "valid": True,
                    "owner_name": "Dev User",
                    "rate_limit": 100,
                    "requests_today": 0,
                    "allow_custom_model": True,
                    "dev_mode": True
                }
            raise ValueError("API Key inválida. En modo desarrollo debe comenzar con 'tenzor-'.")

        try:
            # 0. Limpieza en diferido: borrar claves ya expiradas de la BBDD
            now = datetime.now(timezone.utc)
            try:
                self.supabase.table("api_keys").delete().lt("expires_at", now.isoformat()).execute()
            except Exception as clean_err:
                logger.error(f"Error realizando limpieza en diferido de claves expiradas: {clean_err}")

            # Consultar en Supabase
            response = self.supabase.table("api_keys").select("*").eq("key", api_key).execute()
            data = response.data

            if not data:
                raise ValueError("API Key no registrada.")

            key_info = data[0]

            # Verificar si la clave ha expirado (en caso de no haber sido barrida aún)
            expires_at_str = key_info.get("expires_at")
            if expires_at_str:
                try:
                    expires_dt = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                    if now > expires_dt:
                        # Borrar de inmediato para limpiar la BBDD
                        self.supabase.table("api_keys").delete().eq("id", key_info["id"]).execute()
                        raise ValueError("API Key caducada y eliminada.")
                except ValueError as val_err:
                    raise val_err
                except Exception as ex:
                    logger.error(f"Error comprobando expiración de la clave: {ex}")

            if not key_info.get("is_active", True):
                raise ValueError("API Key desactivada por el administrador.")

            # Verificar y resetear el contador diario si ha cambiado el día
            requests_today = key_info.get("requests_today", 0)
            last_request_str = key_info.get("last_request_at")
            
            if last_request_str:
                try:
                    dt_str = last_request_str.replace("Z", "+00:00")
                    last_request_dt = datetime.fromisoformat(dt_str)
                    # Si el día ha cambiado en UTC, reseteamos a 0 el contador local
                    if last_request_dt.date() != now.date():
                        requests_today = 0
                except Exception as ex:
                    logger.error(f"Error parseando last_request_at: {ex}")

            rate_limit = key_info.get("rate_limit", 100)

            if requests_today >= rate_limit:
                raise ValueError("Límite de peticiones diarias excedido.")

            # Incrementar contadores en Supabase y actualizar last_request_at
            self._increment_counters(
                record_id=key_info["id"],
                next_today=requests_today + 1,
                next_total=key_info.get("total_requests", 0) + 1,
                now_timestamp=now.isoformat()
            )

            return {
                "valid": True,
                "owner_name": key_info.get("owner_name"),
                "rate_limit": rate_limit,
                "requests_today": requests_today + 1,
                "allow_custom_model": key_info.get("allow_custom_model", False),
                "dev_mode": False
            }

        except Exception as e:
            if isinstance(e, ValueError):
                raise e
            logger.error(f"Error consultando Supabase: {e}")
            raise ValueError("Error interno validando la clave.")

    def _increment_counters(self, record_id: str, next_today: int, next_total: int, now_timestamp: str):
        try:
            self.supabase.table("api_keys").update({
                "requests_today": next_today,
                "total_requests": next_total,
                "last_request_at": now_timestamp
            }).eq("id", record_id).execute()
        except Exception as e:
            logger.error(f"Error actualizando contadores de API Key: {e}")

    def create_api_key(
        self, 
        owner_name: str, 
        rate_limit: int = 100, 
        expires_in_days: Optional[int] = None,
        allow_custom_model: bool = False
    ) -> str:
        """
        Crea una nueva API key en Supabase.
        Lanza una excepción si Supabase no está configurado.
        """
        if self.dev_mode:
            raise RuntimeError("No se pueden crear llaves persistentes en modo desarrollo. Configura Supabase.")

        import secrets
        from datetime import timedelta
        
        # Generar una clave segura con prefijo
        new_key = f"tenzor-{secrets.token_hex(16)}"
        
        expires_at_dt = None
        if expires_in_days is not None:
            expires_at_dt = (datetime.now(timezone.utc) + timedelta(days=expires_in_days)).isoformat()
        
        try:
            self.supabase.table("api_keys").insert({
                "key": new_key,
                "owner_name": owner_name,
                "rate_limit": rate_limit,
                "is_active": True,
                "expires_at": expires_at_dt,
                "allow_custom_model": allow_custom_model
            }).execute()
            return new_key
        except Exception as e:
            logger.error(f"Error creando API Key en Supabase: {e}")
            raise RuntimeError("No se pudo insertar la API Key en la base de datos.")

    def list_api_keys(self):
        if self.dev_mode:
            return []
        try:
            # Limpieza en diferido al listar las claves para mantener limpia la BBDD
            try:
                now = datetime.now(timezone.utc)
                self.supabase.table("api_keys").delete().lt("expires_at", now.isoformat()).execute()
            except Exception:
                pass
                
            response = self.supabase.table("api_keys").select("*").execute()
            return response.data
        except Exception as e:
            logger.error(f"Error listando API Keys: {e}")
            return []

    def update_key_status(self, key_id: str, is_active: bool):
        if self.dev_mode:
            raise RuntimeError("Operación no permitida en modo desarrollo.")
        try:
            self.supabase.table("api_keys").update({"is_active": is_active}).eq("id", key_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error actualizando estado de la clave: {e}")
            return False
