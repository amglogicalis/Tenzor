from fastapi import Request, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.services.key_service import KeyService

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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno verificando la autenticación."
        )
