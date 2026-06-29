"""
platform_auth_service.py
Servicio de autenticación para la plataforma Arzor.
Usa Supabase Auth para registro/login y la tabla `profiles` para datos de usuario.
"""
import logging
from typing import Optional, Dict, Any
from supabase import create_client, Client
from app import config

logger = logging.getLogger(__name__)


class PlatformAuthService:
    """
    Gestiona registro, login, logout y perfil de usuarios de la plataforma Arzor.
    Delega la autenticación a Supabase Auth (JWT nativo).
    """

    def __init__(self):
        self.supabase: Optional[Client] = None
        self._admin: Optional[Client] = None  # service_role: bypass RLS

        if config.SUPABASE_URL and config.SUPABASE_KEY:
            try:
                self.supabase = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
                logger.info("PlatformAuthService: cliente Supabase (anon) inicializado.")
            except Exception as e:
                logger.error(f"PlatformAuthService: error al inicializar Supabase: {e}")
        else:
            logger.warning("PlatformAuthService: Supabase no configurado. Auth de plataforma inoperativa.")

        # Cliente admin para escribir profiles sin restricciones de RLS
        if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
            try:
                self._admin = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
                logger.info("PlatformAuthService: cliente admin (service_role) inicializado.")
            except Exception as e:
                logger.warning(f"PlatformAuthService: no se pudo crear cliente admin: {e}")
                self._admin = self.supabase  # fallback al anon
        else:
            self._admin = self.supabase  # fallback

    # ─── Registro ──────────────────────────────────────────────────────────────

    def register(self, email: str, password: str, username: str, display_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Registra un nuevo usuario en Supabase Auth y crea su perfil en `profiles`.
        Devuelve el access_token y datos básicos del usuario.
        Lanza ValueError con mensaje legible si algo falla.
        """
        self._require_supabase()

        # 1. Verificar que el username no esté ya tomado
        existing = (
            self.supabase.table("profiles")
            .select("id")
            .eq("username", username)
            .execute()
        )
        if existing.data:
            raise ValueError(f"El nombre de usuario '{username}' ya está en uso.")

        # 2. Crear el usuario en Supabase Auth
        try:
            auth_response = self.supabase.auth.sign_up({
                "email": email,
                "password": password,
            })
        except Exception as e:
            logger.error(f"Error en sign_up de Supabase Auth: {e}")
            raise ValueError("No se pudo crear la cuenta. El email puede estar ya registrado.")

        user = auth_response.user
        if not user:
            raise ValueError("Error al crear la cuenta. Inténtalo de nuevo.")

        user_id = user.id
        session = auth_response.session

        # 3. Insertar perfil en la tabla `profiles` usando service_role (bypass RLS)
        admin_client = self._admin or self.supabase
        try:
            admin_client.table("profiles").insert({
                "id": user_id,
                "username": username,
                "display_name": display_name or username,
            }).execute()
        except Exception as e:
            logger.error(f"Error insertando perfil para user {user_id}: {e}")
            raise ValueError("Cuenta creada pero el perfil no pudo guardarse. Contacta al soporte.")

        access_token = session.access_token if session else ""
        email_pending = session is None  # Supabase requiere confirmación de email

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user_id": user_id,
            "username": username,
            "display_name": display_name or username,
            "email_confirmation_required": email_pending,
        }

    # ─── Login ─────────────────────────────────────────────────────────────────

    def login(self, email: str, password: str) -> Dict[str, Any]:
        """
        Autentica al usuario con email/contraseña.
        Devuelve el access_token JWT de Supabase y datos del perfil.
        """
        self._require_supabase()

        try:
            auth_response = self.supabase.auth.sign_in_with_password({
                "email": email,
                "password": password,
            })
        except Exception as e:
            err_str = str(e).lower()
            logger.warning(f"Fallo de login para {email}: {e}")
            if "email not confirmed" in err_str or "email_not_confirmed" in err_str:
                raise ValueError(
                    "Debes confirmar tu email antes de iniciar sesión. "
                    "Revisa tu bandeja de entrada (y spam)."
                )
            raise ValueError("Email o contraseña incorrectos.")

        user = auth_response.user
        session = auth_response.session

        if not user or not session:
            raise ValueError("Email o contraseña incorrectos.")

        # Obtener perfil
        profile = self._get_profile_by_id(user.id)

        return {
            "access_token": session.access_token,
            "token_type": "bearer",
            "user_id": user.id,
            "username": profile.get("username", ""),
            "display_name": profile.get("display_name"),
        }

    def resend_confirmation(self, email: str) -> None:
        """
        Reenvía el correo de confirmación de registro (signup) usando Supabase Auth.
        """
        self._require_supabase()
        try:
            self.supabase.auth.resend({
                "type": "signup",
                "email": email
            })
        except Exception as e:
            logger.error(f"Error reenviando correo de confirmación para {email}: {e}")
            raise ValueError("No se pudo reenviar el correo de confirmación. Verifica tu email.")

    # ─── Perfil ────────────────────────────────────────────────────────────────


    def get_profile(self, user_id: str) -> Dict[str, Any]:
        """Devuelve el perfil del usuario."""
        self._require_supabase()
        profile = self._get_profile_by_id(user_id)
        if not profile:
            raise ValueError("Perfil no encontrado.")
        return profile

    def update_profile(self, user_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Actualiza campos del perfil del usuario."""
        self._require_supabase()

        allowed = {"display_name", "bio", "avatar_url"}
        update_data = {k: v for k, v in fields.items() if k in allowed and v is not None}

        if not update_data:
            raise ValueError("No hay campos válidos para actualizar.")

        try:
            resp = (
                self.supabase.table("profiles")
                .update(update_data)
                .eq("id", user_id)
                .execute()
            )
            return resp.data[0] if resp.data else {}
        except Exception as e:
            logger.error(f"Error actualizando perfil {user_id}: {e}")
            raise ValueError("No se pudo actualizar el perfil.")

    # ─── Verificación de token ─────────────────────────────────────────────────

    def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verifica un JWT de Supabase y devuelve los datos del usuario.
        Usado por el middleware de autenticación de la plataforma.
        """
        self._require_supabase()

        try:
            user_response = self.supabase.auth.get_user(token)
            user = user_response.user
            if not user:
                raise ValueError("Token inválido o expirado.")
            return {
                "user_id": user.id,
                "email": user.email,
            }
        except Exception as e:
            logger.warning(f"Token de plataforma inválido: {e}")
            raise ValueError("Token inválido o expirado.")

    # ─── Helpers ───────────────────────────────────────────────────────────────

    def _get_profile_by_id(self, user_id: str) -> Dict[str, Any]:
        try:
            resp = (
                self.supabase.table("profiles")
                .select("*")
                .eq("id", user_id)
                .single()
                .execute()
            )
            return resp.data or {}
        except Exception as e:
            logger.error(f"Error consultando perfil {user_id}: {e}")
            return {}

    def _require_supabase(self):
        if not self.supabase:
            raise ValueError("El servicio de autenticación no está disponible. Supabase no configurado.")


# Instancia global (singleton) para reusar en routers
platform_auth_service = PlatformAuthService()
