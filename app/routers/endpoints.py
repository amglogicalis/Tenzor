from fastapi import APIRouter, Depends, HTTPException, status
from app.routers.chat import ai_service
from app.middleware.auth import verify_api_key
import logging

router = APIRouter(prefix="/v1/model", tags=["Model Lifecycle"])
logger = logging.getLogger(__name__)

@router.get("/status")
async def get_model_status(
    key_info: dict = Depends(verify_api_key)
):
    """
    Obtiene el estado actual del modelo en Vertex AI:
    - 'sleep': El modelo está apagado (no cuesta nada).
    - 'waking': El modelo se está desplegando (despertando la GPU T4).
    - 'active': El modelo está encendido y listo para chatear.
    """
    try:
        current_status = ai_service.get_model_status()
        return {
            "status": current_status,
            "allow_custom_model": key_info.get("allow_custom_model", False)
        }
    except Exception as e:
        logger.error(f"Error al obtener estado del modelo: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error consultando el estado en GCP: {str(e)}"
        )

@router.post("/wake")
async def wake_model(
    key_info: dict = Depends(verify_api_key)
):
    """
    Inicia la activación del modelo desplegándolo en una GPU Tesla T4 ($0.35/hora).
    Tarda entre 3-5 minutos en estar activo.
    """
    if not key_info.get("allow_custom_model", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu API Key no tiene permisos para acceder al modelo personalizado."
        )
    
    try:
        result = ai_service.wake_model()
        if result.get("status") == "error":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("message")
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al despertar el modelo: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno al solicitar encendido: {str(e)}"
        )

@router.post("/sleep")
async def sleep_model(
    key_info: dict = Depends(verify_api_key)
):
    """
    Fuerza el apagado inmediato del modelo (undeploy) para liberar la GPU y evitar costes.
    """
    if not key_info.get("allow_custom_model", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tu API Key no tiene permisos para gestionar el modelo personalizado."
        )

    try:
        result = ai_service.sleep_model()
        if result.get("status") == "error":
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.get("message")
            )
        return result
    except Exception as e:
        logger.error(f"Error al apagar el modelo: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno al solicitar apagado: {str(e)}"
        )
