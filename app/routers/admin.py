from fastapi import APIRouter, Depends, HTTPException, Header, status
from typing import List
from app.models import APIKeyCreate, APIKeyResponse
from app.services.key_service import KeyService
from app import config

router = APIRouter(prefix="/admin", tags=["Admin"])
key_service = KeyService()

async def verify_admin_key(x_admin_secret: str = Header(..., alias="X-Admin-Secret")):
    """
    Dependency para verificar la clave de administración.
    """
    if x_admin_secret != config.ADMIN_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Clave de administración incorrecta."
        )
    return True

@router.post("/keys", response_model=str)
async def create_key(
    payload: APIKeyCreate,
    admin_auth: bool = Depends(verify_admin_key)
):
    """
    Genera una nueva API Key persistente en Supabase.
    """
    try:
        new_key = key_service.create_api_key(
            owner_name=payload.owner_name,
            rate_limit=payload.rate_limit,
            expires_in_days=payload.expires_in_days,
            allow_custom_model=payload.allow_custom_model
        )
        return new_key
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.get("/keys", response_model=List[APIKeyResponse])
async def list_keys(
    admin_auth: bool = Depends(verify_admin_key)
):
    """
    Lista todas las API Keys registradas en Supabase.
    """
    return key_service.list_api_keys()

@router.patch("/keys/{key_id}/status")
async def update_key_status(
    key_id: str,
    is_active: bool,
    admin_auth: bool = Depends(verify_admin_key)
):
    """
    Activa o desactiva una API Key específica usando su UUID.
    """
    success = key_service.update_key_status(key_id, is_active)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="API Key no encontrada o no se pudo actualizar."
        )
    return {"message": f"Estado de API Key actualizado a {'activo' if is_active else 'inactivo'}."}
