"""
platform_auth_middleware.py
Dependency de FastAPI para verificar el JWT de Supabase en los endpoints de la plataforma Arzor.
Uso: agregar `current_user: dict = Depends(require_platform_user)` al endpoint.
"""
import logging
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.services.platform_auth_service import platform_auth_service

logger = logging.getLogger(__name__)
_bearer = HTTPBearer(auto_error=False)


async def require_platform_user(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> dict:
    """
    Verifica el Bearer token (JWT de Supabase) para endpoints de la plataforma Arzor.
    Devuelve el dict del usuario autenticado: {"user_id": str, "email": str}.
    Lanza 401 si el token es inválido o está ausente.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere autenticación. Incluye tu token en el header Authorization: Bearer <token>.",
        )

    try:
        user_data = platform_auth_service.verify_token(credentials.credentials)
        return user_data
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error interno verificando token de plataforma: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno verificando el token de autenticación.",
        )
