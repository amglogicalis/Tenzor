"""
round_table.py
Router para los debates multi-agente Arzor Round Table.

Endpoints:
  POST   /platform/round-table                            → crear mesa
  GET    /platform/round-table                            → listar mesas del usuario
  GET    /platform/round-table/{table_id}                 → detalle de una mesa
  DELETE /platform/round-table/{table_id}                 → borrar mesa
  POST   /platform/round-table/{table_id}/members         → añadir agente
  DELETE /platform/round-table/{table_id}/members/{agent_id} → eliminar agente
  GET    /platform/round-table/{table_id}/members         → listar miembros
  POST   /platform/round-table/{table_id}/start           → iniciar debate
  GET    /platform/round-table/{table_id}/result          → obtener resultado
"""
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field

from app.middleware.platform_auth_middleware import require_platform_user
from app.services.round_table_service import RoundTableService, MIN_AGENTS, MAX_AGENTS, MIN_ROUNDS, MAX_ROUNDS

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platform/round-table", tags=["round-table"])

_rt_service = RoundTableService()


# ─── Modelos ──────────────────────────────────────────────────────────────────

class CreateTableRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Nombre de la mesa")
    description: Optional[str] = Field(None, max_length=500)
    topic: str = Field(..., min_length=10, max_length=2000, description="Tema del debate")


class AddMemberRequest(BaseModel):
    agent_id: str = Field(..., description="UUID del agente a añadir")
    turn_order: int = Field(0, ge=0, le=10, description="Orden de turno (0 = sin orden)")


class StartDebateRequest(BaseModel):
    rounds: int = Field(1, ge=MIN_ROUNDS, le=MAX_ROUNDS,
                        description=f"Número de rondas ({MIN_ROUNDS}-{MAX_ROUNDS})")


# ─── Endpoints: Mesas ─────────────────────────────────────────────────────────

@router.post(
    "",
    summary="Crear una nueva mesa de debate",
    status_code=status.HTTP_201_CREATED,
)
def create_table(
    req: CreateTableRequest,
    user: dict = Depends(require_platform_user),
):
    user_id = user["user_id"]
    try:
        table = _rt_service.create_table(
            user_id=user_id, name=req.name,
            description=req.description, topic=req.topic,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return table


@router.get(
    "",
    summary="Listar mesas del usuario",
    status_code=status.HTTP_200_OK,
)
def list_tables(
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_platform_user),
):
    tables = _rt_service.list_tables(user_id=user["user_id"], limit=limit)
    return {"tables": tables, "total": len(tables)}


@router.get(
    "/{table_id}",
    summary="Detalle de una mesa",
    status_code=status.HTTP_200_OK,
)
def get_table(
    table_id: str,
    user: dict = Depends(require_platform_user),
):
    try:
        return _rt_service.get_table(table_id=table_id, user_id=user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete(
    "/{table_id}",
    summary="Borrar mesa de debate",
    status_code=status.HTTP_200_OK,
)
def delete_table(
    table_id: str,
    user: dict = Depends(require_platform_user),
):
    try:
        _rt_service.delete_table(table_id=table_id, user_id=user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"detail": "Mesa eliminada.", "table_id": table_id}


# ─── Endpoints: Miembros ──────────────────────────────────────────────────────

@router.post(
    "/{table_id}/members",
    summary="Añadir agente a la mesa",
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    table_id: str,
    req: AddMemberRequest,
    user: dict = Depends(require_platform_user),
):
    try:
        member = _rt_service.add_member(
            table_id=table_id, user_id=user["user_id"],
            agent_id=req.agent_id, turn_order=req.turn_order,
        )
    except ValueError as e:
        msg = str(e)
        code = status.HTTP_404_NOT_FOUND if "no encontrad" in msg else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=msg)
    return member


@router.delete(
    "/{table_id}/members/{agent_id}",
    summary="Eliminar agente de la mesa",
    status_code=status.HTTP_200_OK,
)
def remove_member(
    table_id: str,
    agent_id: str,
    user: dict = Depends(require_platform_user),
):
    try:
        _rt_service.remove_member(
            table_id=table_id, user_id=user["user_id"], agent_id=agent_id
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"detail": "Agente eliminado de la mesa.", "agent_id": agent_id}


@router.get(
    "/{table_id}/members",
    summary="Listar miembros de la mesa",
    status_code=status.HTTP_200_OK,
)
def list_members(
    table_id: str,
    user: dict = Depends(require_platform_user),
):
    try:
        members = _rt_service.list_members(table_id=table_id, user_id=user["user_id"])
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    return {"table_id": table_id, "members": members, "total": len(members)}


# ─── Endpoints: Debate ────────────────────────────────────────────────────────

@router.post(
    "/{table_id}/start",
    summary="Iniciar el debate multi-agente",
    description=(
        "Inicia el debate de forma síncrona. Puede tardar varios segundos "
        "dependiendo del número de agentes y rondas. "
        f"Requiere al menos {MIN_AGENTS} agentes. Máximo {MAX_ROUNDS} rondas."
    ),
    status_code=status.HTTP_200_OK,
)
def start_debate(
    table_id: str,
    req: StartDebateRequest,
    user: dict = Depends(require_platform_user),
):
    try:
        result = _rt_service.start_debate(
            table_id=table_id, user_id=user["user_id"], rounds=req.rounds
        )
    except ValueError as e:
        msg = str(e)
        code = (
            status.HTTP_404_NOT_FOUND if "no encontrad" in msg
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=msg)
    except Exception as e:
        logger.error(f"Error inesperado en debate {table_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno durante el debate."
        )
    return result.to_dict()


@router.get(
    "/{table_id}/result",
    summary="Obtener resultado del debate",
    status_code=status.HTTP_200_OK,
)
def get_result(
    table_id: str,
    user: dict = Depends(require_platform_user),
):
    try:
        result = _rt_service.get_result(table_id=table_id, user_id=user["user_id"])
    except ValueError as e:
        msg = str(e)
        code = status.HTTP_404_NOT_FOUND if "no encontrad" in msg else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=msg)
    return result
