from fastapi import APIRouter, Depends, HTTPException, status
from app.models import ChatCompletionRequest, ChatCompletionResponse
from app.services.ai_service import AIService
from app.middleware.auth import verify_api_key
import logging

router = APIRouter(prefix="/v1", tags=["Chat"])
ai_service = AIService()
logger = logging.getLogger(__name__)

@router.post("/chat/completions", response_model=ChatCompletionResponse)
async def chat_completion(
    request: ChatCompletionRequest,
    key_info: dict = Depends(verify_api_key)
):
    """
    Endpoint compatible con el formato OpenAI Chat Completions.
    Requiere autenticación mediante Bearer Token (API Key de Tenzor).
    """
    logger.info(f"Petición de chat recibida de {key_info.get('owner_name')} (Modo Dev: {key_info.get('dev_mode')})")
    
    if not request.messages:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La lista de mensajes no puede estar vacía."
        )

    try:
        response = ai_service.generate_chat_completion(
            messages=request.messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens
        )
        return response
    except Exception as e:
        logger.error(f"Error procesando chat completion: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )

@router.get("/config")
async def get_config():
    """
    Devuelve la clave de cliente por defecto para el frontend.
    """
    from app import config
    return {
        "default_api_key": config.DEFAULT_CLIENT_KEY
    }
