import logging
from typing import List, Dict, Any, Optional
from supabase import Client
from app.db import supabase_admin
from app.services.encryption_service import encryption_service

logger = logging.getLogger(__name__)

class ProviderKeysDbService:
    def __init__(self):
        self.supabase: Optional[Client] = supabase_admin
        if not self.supabase:
            logger.warning("ProviderKeysDbService: Supabase no configurado.")

    def add_key(self, user_id: str, provider: str, key_label: str, raw_key: str) -> Dict[str, Any]:
        """
        Cifra y guarda una clave de API del proveedor en la base de datos Supabase.
        """
        if not self.supabase:
            raise ValueError("Base de datos no disponible.")
        
        provider = provider.lower().strip()
        valid_providers = (
            "google", "groq", "openrouter", "xai", "perplexity", 
            "deepseek", "together", "fireworks", "mistral", 
            "sambanova", "cerebras", "siliconflow"
        )
        if provider not in valid_providers:
            raise ValueError(f"Proveedor no soportado. Debe ser uno de: {', '.join(valid_providers)}.")

        if not raw_key.strip():
            raise ValueError("La clave no puede estar vacía.")

        # Cifrar clave
        encrypted = encryption_service.encrypt(raw_key.strip())

        try:
            resp = (
                self.supabase.table("provider_keys")
                .insert({
                    "user_id": user_id,
                    "provider": provider,
                    "key_label": key_label.strip() or f"Clave de {provider}",
                    "encrypted_key": encrypted,
                    "scope": "user",
                    "is_active": True
                })
                .execute()
            )
            data = resp.data[0]
            # Devolver enmascarada
            return {
                "id": data["id"],
                "provider": data["provider"],
                "key_label": data["key_label"],
                "is_active": data["is_active"],
                "created_at": data["created_at"],
                "masked_key": self._mask_key(raw_key)
            }
        except Exception as e:
            logger.error(f"Error guardando clave de proveedor para user {user_id}: {e}")
            raise ValueError("No se pudo guardar la clave de API.")

    def list_keys(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Lista las claves de proveedor de un usuario, enmascarando los valores cifrados.
        """
        if not self.supabase:
            return []
        try:
            resp = (
                self.supabase.table("provider_keys")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .execute()
            )
            keys = resp.data or []
            result = []
            for k in keys:
                # Intentamos descifrar para obtener el valor enmascarado
                try:
                    decrypted = encryption_service.decrypt(k["encrypted_key"])
                    masked = self._mask_key(decrypted)
                except Exception:
                    masked = "****"
                
                result.append({
                    "id": k["id"],
                    "provider": k["provider"],
                    "key_label": k["key_label"],
                    "is_active": k["is_active"],
                    "created_at": k["created_at"],
                    "masked_key": masked
                })
            return result
        except Exception as e:
            logger.error(f"Error listando claves de proveedor para user {user_id}: {e}")
            return []

    def delete_key(self, user_id: str, key_id: str) -> bool:
        """
        Elimina una clave de proveedor perteneciente al usuario.
        """
        if not self.supabase:
            return False
        try:
            # Primero verificar propiedad
            check = (
                self.supabase.table("provider_keys")
                .select("id")
                .eq("id", key_id)
                .eq("user_id", user_id)
                .execute()
            )
            if not check.data:
                raise ValueError("Clave no encontrada o no tienes permiso para eliminarla.")
            
            self.supabase.table("provider_keys").delete().eq("id", key_id).execute()
            return True
        except Exception as e:
            logger.error(f"Error eliminando clave {key_id} para user {user_id}: {e}")
            raise ValueError(str(e))

    def get_decrypted_user_keys(self, user_id: str) -> List[Dict[str, Any]]:
        """
        Obtiene y descifra todas las claves activas de un usuario para cargarlas en el pool.
        """
        if not self.supabase:
            return []
        try:
            resp = (
                self.supabase.table("provider_keys")
                .select("*")
                .eq("user_id", user_id)
                .eq("is_active", True)
                .execute()
            )
            keys = resp.data or []
            decrypted_keys = []
            for k in keys:
                try:
                    raw_key = encryption_service.decrypt(k["encrypted_key"])
                    decrypted_keys.append({
                        "key_id": k["id"],
                        "provider": k["provider"],
                        "api_key": raw_key,
                        "key_label": k["key_label"]
                    })
                except Exception as dec_err:
                    logger.error(f"Error descifrando clave {k['id']} para pool: {dec_err}")
            return decrypted_keys
        except Exception as e:
            logger.error(f"Error cargando claves descifradas para user {user_id}: {e}")
            return []

    def _mask_key(self, key: str) -> str:
        """Enmascara una clave para que no se exponga."""
        if len(key) <= 8:
            return "****"
        return f"{key[:4]}...{key[-4:]}"

# Singleton global
provider_keys_db_service = ProviderKeysDbService()
