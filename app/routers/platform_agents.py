"""
platform_agents.py
Router CRUD de agentes personalizados — Arzor AIs Platform.
Fase 2: endpoints completos con autenticación y versionado.
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status, Query

from app.models_platform import (
    CreateAgentRequest,
    UpdateAgentRequest,
    AgentResponse,
    AgentListResponse,
    AgentVersionResponse,
    NewVersionRequest,
)
from app.services.agent_service import agent_service
from app.middleware.platform_auth_middleware import require_platform_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platform/agents", tags=["platform-agents"])


# ─── GET /platform/agents ─────────────────────────────────────────────────────
@router.get(
    "",
    response_model=AgentListResponse,
    summary="Listar mis agentes",
)
async def list_my_agents(current_user: dict = Depends(require_platform_user)):
    """Devuelve todos los agentes activos del usuario autenticado."""
    agents = agent_service.list_my_agents(user_id=current_user["user_id"])
    return {"agents": agents, "total": len(agents)}


# ─── GET /platform/agents/library ─────────────────────────────────────────────
@router.get(
    "/library",
    response_model=AgentListResponse,
    summary="Biblioteca pública de agentes",
)
async def list_public_agents(
    category: Optional[str] = Query(None, description="Filtrar por categoría: dev, data, ops, creative, science, custom"),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Lista agentes públicos ordenados por nivel (más experimentados primero).
    No requiere autenticación.
    """
    agents = agent_service.list_public_agents(category=category, limit=limit)
    return {"agents": agents, "total": len(agents)}


# ─── POST /platform/agents ────────────────────────────────────────────────────
@router.post(
    "",
    response_model=AgentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear nuevo agente personalizado",
)
async def create_agent(
    body: CreateAgentRequest,
    current_user: dict = Depends(require_platform_user),
):
    """
    Crea un agente personalizado con su perfil AFT versión 1.
    Las instrucciones se guardan directamente (en Fase 3 serán compiladas por AFT).
    """
    try:
        agent = agent_service.create_agent(
            user_id=current_user["user_id"],
            name=body.name,
            description=body.description,
            category=body.category,
            base_tier=body.base_tier,
            system_instructions=body.system_instructions,
            is_public=body.is_public,
            preferred_provider=body.preferred_provider,
            preferred_model=body.preferred_model,
        )
        return agent
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error inesperado creando agente: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Error interno al crear el agente.")


# ─── GET /platform/agents/{agent_id} ─────────────────────────────────────────
@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Obtener agente por ID",
)
async def get_agent(
    agent_id: str,
    current_user: dict = Depends(require_platform_user),
):
    """
    Devuelve un agente con su versión activa.
    El usuario debe ser el dueño o el agente debe ser público.
    """
    try:
        return agent_service.get_agent(agent_id=agent_id, user_id=current_user["user_id"])
    except ValueError as e:
        status_code = status.HTTP_404_NOT_FOUND if "encontrado" in str(e) else status.HTTP_403_FORBIDDEN
        raise HTTPException(status_code=status_code, detail=str(e))


# ─── PATCH /platform/agents/{agent_id} ───────────────────────────────────────
@router.patch(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Actualizar metadatos de un agente",
)
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    current_user: dict = Depends(require_platform_user),
):
    """Actualiza nombre, descripción, categoría, tier o visibilidad del agente."""
    try:
        return agent_service.update_agent(
            agent_id=agent_id,
            user_id=current_user["user_id"],
            fields=body.model_dump(exclude_none=True),
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ─── DELETE /platform/agents/{agent_id} ──────────────────────────────────────
@router.delete(
    "/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar agente (soft-delete)",
)
async def delete_agent(
    agent_id: str,
    current_user: dict = Depends(require_platform_user),
):
    """
    Marca el agente como borrado (soft-delete). No se elimina de la base de datos.
    Los documentos y versiones quedan preservados.
    """
    try:
        agent_service.delete_agent(agent_id=agent_id, user_id=current_user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ─── POST /platform/agents/{agent_id}/publish ────────────────────────────────
@router.post(
    "/{agent_id}/publish",
    response_model=AgentResponse,
    summary="Publicar agente en la biblioteca",
)
async def publish_agent(
    agent_id: str,
    current_user: dict = Depends(require_platform_user),
):
    """Hace público el agente para que aparezca en la biblioteca."""
    try:
        return agent_service.publish_agent(
            agent_id=agent_id, user_id=current_user["user_id"], is_public=True
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ─── POST /platform/agents/{agent_id}/unpublish ──────────────────────────────
@router.post(
    "/{agent_id}/unpublish",
    response_model=AgentResponse,
    summary="Hacer privado el agente",
)
async def unpublish_agent(
    agent_id: str,
    current_user: dict = Depends(require_platform_user),
):
    """Retira el agente de la biblioteca pública."""
    try:
        return agent_service.publish_agent(
            agent_id=agent_id, user_id=current_user["user_id"], is_public=False
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


# ─── GET /platform/agents/{agent_id}/versions ────────────────────────────────
@router.get(
    "/{agent_id}/versions",
    response_model=list[AgentVersionResponse],
    summary="Historial de versiones del agente",
)
async def list_versions(
    agent_id: str,
    current_user: dict = Depends(require_platform_user),
):
    """Lista todas las versiones del perfil AFT del agente, de más reciente a más antigua."""
    try:
        return agent_service.list_versions(agent_id=agent_id, user_id=current_user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))


# ─── POST /platform/agents/{agent_id}/versions ───────────────────────────────
@router.post(
    "/{agent_id}/versions",
    response_model=AgentVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear nueva versión del perfil del agente",
)
async def create_new_version(
    agent_id: str,
    body: NewVersionRequest,
    current_user: dict = Depends(require_platform_user),
):
    """
    Crea una nueva versión del perfil AFT y la establece como activa.
    La versión anterior queda preservada para rollback.
    """
    try:
        return agent_service.create_new_version(
            agent_id=agent_id,
            user_id=current_user["user_id"],
            system_instructions=body.system_instructions,
            behavior_examples=body.behavior_examples,
            style_rules=body.style_rules,
            domain_constraints=body.domain_constraints,
            retrieval_profile=body.retrieval_profile,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
