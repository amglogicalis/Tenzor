"""
platform_auth.py
Router de autenticación para la plataforma Arzor.
Endpoints: /platform/auth/register, /login, /me, /profile
"""
import logging
from fastapi import APIRouter, HTTPException, Depends, status
from app.models_platform import (
    RegisterRequest,
    LoginRequest,
    AuthResponse,
    ProfileResponse,
    UpdateProfileRequest,
)
from app.services.platform_auth_service import platform_auth_service
from app.middleware.platform_auth_middleware import require_platform_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platform/auth", tags=["platform-auth"])


# ─── POST /platform/auth/register ─────────────────────────────────────────────
@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Registrar nuevo usuario en la plataforma Arzor",
)
async def register(body: RegisterRequest):
    """
    Crea una cuenta nueva con email + contraseña y genera su perfil.
    Devuelve un access_token de Supabase listo para usar.
    """
    try:
        result = platform_auth_service.register(
            email=body.email,
            password=body.password,
            username=body.username,
            display_name=body.display_name,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error inesperado en /register: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno al registrar.")


# ─── POST /platform/auth/login ────────────────────────────────────────────────
@router.post(
    "/login",
    response_model=AuthResponse,
    summary="Iniciar sesión en la plataforma Arzor",
)
async def login(body: LoginRequest):
    """
    Autentica al usuario con email y contraseña.
    Devuelve el JWT de Supabase para usar en las llamadas posteriores.
    """
    try:
        result = platform_auth_service.login(
            email=body.email,
            password=body.password,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    except Exception as e:
        logger.error(f"Error inesperado en /login: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno al iniciar sesión.")


# ─── POST /platform/auth/resend-confirmation ──────────────────────────────────
from app.models_platform import ResendConfirmationRequest

@router.post(
    "/resend-confirmation",
    summary="Reenviar correo de confirmación de registro en la plataforma Arzor",
)
async def resend_confirmation(body: ResendConfirmationRequest):
    """
    Reenvía el enlace de verificación al correo especificado.
    """
    try:
        platform_auth_service.resend_confirmation(body.email)
        return {"message": "Correo de confirmación reenviado con éxito."}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error inesperado en /resend-confirmation: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno al reenviar correo.")


# ─── POST /platform/auth/recover-password ──────────────────────────────────────
from app.models_platform import RecoverPasswordRequest

@router.post(
    "/recover-password",
    summary="Solicitar enlace de recuperación/restablecimiento de contraseña",
)
async def recover_password(body: RecoverPasswordRequest):
    """
    Solicita a Supabase Auth el envío de un correo para restablecer la contraseña.
    """
    try:
        platform_auth_service.recover_password(body.email, body.redirect_to)
        return {"message": "Correo de restablecimiento enviado con éxito."}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error inesperado en /recover-password: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno al procesar recuperación.")


# ─── POST /platform/auth/update-password ───────────────────────────────────────
from app.models_platform import ResetPasswordRequest
from fastapi import Header

@router.post(
    "/update-password",
    summary="Actualizar contraseña de usuario usando token de restablecimiento",
)
async def update_password(body: ResetPasswordRequest, authorization: str = Header(...)):
    """
    Actualiza la contraseña en Supabase Auth usando el token JWT provisto en las cabeceras.
    """
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token inválido o malformado.")
    token = authorization.split(" ")[1]
    try:
        platform_auth_service.update_password(token, body.password)
        return {"message": "Contraseña actualizada correctamente."}
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error inesperado en /update-password: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno al actualizar contraseña.")




# ─── GET /platform/auth/me ────────────────────────────────────────────────────
@router.get(
    "/me",
    response_model=ProfileResponse,
    summary="Obtener perfil del usuario autenticado",
)
async def get_me(current_user: dict = Depends(require_platform_user)):
    """
    Devuelve el perfil completo del usuario autenticado.
    Requiere Bearer token válido.
    """
    try:
        profile = platform_auth_service.get_profile(current_user["user_id"])
        return profile
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ─── PATCH /platform/auth/me ──────────────────────────────────────────────────
@router.patch(
    "/me",
    response_model=ProfileResponse,
    summary="Actualizar perfil del usuario autenticado",
)
async def update_me(
    body: UpdateProfileRequest,
    current_user: dict = Depends(require_platform_user),
):
    """
    Actualiza campos opcionales del perfil: display_name, bio, avatar_url.
    """
    try:
        updated = platform_auth_service.update_profile(
            user_id=current_user["user_id"],
            fields=body.model_dump(exclude_none=True),
        )
        return updated
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
