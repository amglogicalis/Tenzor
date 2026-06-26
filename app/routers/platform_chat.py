"""
platform_chat.py
Router de chat con agentes personalizados de la plataforma Arzor.

Endpoints:
  POST   /platform/chat/{agent_id}              → enviar mensaje / iniciar sesión
  GET    /platform/chat/sessions                → listar sesiones del usuario
  GET    /platform/chat/sessions/{session_id}   → historial completo de una sesión
  DELETE /platform/chat/sessions/{session_id}   → borrar sesión + mensajes
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field

from app.middleware.platform_auth_middleware import require_platform_user
from app.services.platform_chat_service import PlatformChatService
from app.services.agent_cache_service import AgentCacheService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platform/chat", tags=["platform-chat"])

# Singletons
_chat_service = PlatformChatService()
_cache_service = AgentCacheService()


# ─── Modelos de request / response ────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000,
                         description="Mensaje del usuario al agente")
    session_id: Optional[str] = Field(
        None,
        description="UUID de sesión existente. Si es None se crea una nueva sesión."
    )
    temperature: float = Field(
        0.7, ge=0.0, le=2.0,
        description="Temperatura de generación (0=determinista, 2=muy creativo)"
    )
    max_tokens: Optional[int] = Field(
        None, ge=1, le=8192,
        description="Límite de tokens de salida (None = default del provider)"
    )
    force_provider: Optional[str] = Field(
        None, pattern=r"^(groq|google|openrouter)$",
        description="Forzar un provider concreto (solo para debug)"
    )
    use_cache: bool = Field(
        True,
        description="Si False, ignora el cache y llama siempre al LLM"
    )


class FeedbackRequest(BaseModel):
    value: int = Field(..., description="+1 para positivo, -1 para negativo")


class ChatMessageResponse(BaseModel):
    session_id: str
    message_id: str
    content: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    rag_chunks_used: int


class SessionSummary(BaseModel):
    id: str
    agent_id: Optional[str]
    title: Optional[str]
    created_at: str
    updated_at: str


class HistoryMessage(BaseModel):
    id: str
    role: str
    content: str
    metadata: dict
    created_at: str


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post(
    "/{agent_id}",
    response_model=ChatMessageResponse,
    summary="Enviar mensaje a un agente",
    description=(
        "Envía un mensaje al agente y recibe su respuesta. "
        "Si no se proporciona session_id, se crea una nueva sesión automáticamente. "
        "El agente debe ser tuyo o público."
    ),
    status_code=status.HTTP_200_OK,
)
def send_message(
    agent_id: str,
    req: ChatRequest,
    user: dict = Depends(require_platform_user),
):
    user_id = user["user_id"]
    try:
        response = _chat_service.chat(
            user_id=user_id,
            agent_id=agent_id,
            user_message=req.message,
            session_id=req.session_id,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            force_provider=req.force_provider,
        )
    except ValueError as e:
        msg = str(e)
        if "no encontrado" in msg.lower() or "acceso" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=msg)
    except Exception as e:
        logger.error(f"Error inesperado en chat agent={agent_id} user={user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor."
        )

    return ChatMessageResponse(
        session_id=response.session_id,
        message_id=response.message_id,
        content=response.content,
        provider=response.provider,
        model=response.model,
        tokens_in=response.tokens_in,
        tokens_out=response.tokens_out,
        latency_ms=response.latency_ms,
        rag_chunks_used=response.rag_chunks_used,
    )


@router.get(
    "/sessions",
    summary="Listar sesiones de chat del usuario",
    status_code=status.HTTP_200_OK,
)
def list_sessions(
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_platform_user),
):
    user_id = user["user_id"]
    sessions = _chat_service.list_sessions(user_id=user_id, limit=limit)
    return {"sessions": sessions, "total": len(sessions)}


@router.get(
    "/sessions/{session_id}",
    summary="Historial de una sesión",
    status_code=status.HTTP_200_OK,
)
def get_session_history(
    session_id: str,
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(require_platform_user),
):
    user_id = user["user_id"]
    try:
        messages = _chat_service.get_session_history(
            session_id=session_id, user_id=user_id, limit=limit
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"session_id": session_id, "messages": messages, "total": len(messages)}


@router.delete(
    "/sessions/{session_id}",
    summary="Borrar una sesión de chat",
    status_code=status.HTTP_200_OK,
)
def delete_session(
    session_id: str,
    user: dict = Depends(require_platform_user),
):
    user_id = user["user_id"]
    try:
        _chat_service.delete_session(session_id=session_id, user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"detail": "Sesión eliminada correctamente.", "session_id": session_id}


# ─── Feedback y Cache ─────────────────────────────────────────────────────────

@router.post(
    "/messages/{message_id}/feedback",
    summary="Dar feedback a una respuesta (+1 / -1)",
    status_code=status.HTTP_200_OK,
)
def submit_feedback(
    message_id: str,
    agent_id: str = Query(..., description="UUID del agente al que pertenece el mensaje"),
    req: FeedbackRequest = ...,
    user: dict = Depends(require_platform_user),
):
    user_id = user["user_id"]
    if req.value not in (1, -1):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El valor de feedback debe ser +1 o -1."
        )
    try:
        result = _cache_service.submit_feedback(
            message_id=message_id,
            agent_id=agent_id,
            user_id=user_id,
            value=req.value,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return result


@router.get(
    "/{agent_id}/cache/stats",
    summary="Estadísticas del cache del agente",
    status_code=status.HTTP_200_OK,
)
def get_cache_stats(
    agent_id: str,
    user: dict = Depends(require_platform_user),
):
    stats = _cache_service.get_cache_stats(agent_id=agent_id)
    return {"agent_id": agent_id, **stats}


@router.delete(
    "/{agent_id}/cache",
    summary="Invalidar cache del agente (usar tras re-síntesis)",
    status_code=status.HTTP_200_OK,
)
def invalidate_cache(
    agent_id: str,
    user: dict = Depends(require_platform_user),
):
    count = _cache_service.invalidate_cache(agent_id=agent_id)
    return {"agent_id": agent_id, "entries_removed": count}


@router.get(
    "/{agent_id}/resynthesis/prepare",
    summary="Preparar contexto para re-síntesis del agente",
    description=(
        "Analiza los feedbacks negativos y devuelve el contexto para mejorar el agente "
        "vía AFT Compiler. El usuario debe llamar manualmente a /platform/compiler para aplicarlo."
    ),
    status_code=status.HTTP_200_OK,
)
def prepare_resynthesis(
    agent_id: str,
    current_instructions: str = Query(..., description="Instrucciones actuales del agente"),
    user: dict = Depends(require_platform_user),
):
    user_id = user["user_id"]
    context = _cache_service.prepare_resynthesis_context(
        agent_id=agent_id,
        user_id=user_id,
        current_instructions=current_instructions,
    )
    return {"agent_id": agent_id, **context}
