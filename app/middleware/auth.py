import logging
from fastapi import Request, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.services.key_service import KeyService

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)
key_service = KeyService()

async def verify_api_key(credentials: HTTPAuthorizationCredentials = Security(security)):
    """
    Dependency para verificar la API key recibida en el Header.
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Falta el token de autorización (Bearer Token)."
        )
    
    api_key = credentials.credentials
    try:
        key_info = key_service.validate_key(api_key)
        return key_info
    except ValueError as e:
        error_msg = str(e)
        # Log masked key to help debug authentication errors
        masked_key = f"{api_key[:12]}..." if len(api_key) > 12 else "key-too-short"
        logger.warning(f"Fallo de autenticación con la clave {masked_key}: {error_msg}")
        if "límite" in error_msg.lower() or "excedido" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=error_msg
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=error_msg
        )
    except Exception as e:
        logger.error(f"Error interno verificando la autenticación: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno verificando la autenticación."
        )

