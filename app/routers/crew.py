"""
crew.py
Router para Arzor DevCrew — asistente de desarrollo con IA.

Endpoints:
  POST /platform/crew/plan   → Genera un plan de implementación
  POST /platform/crew/write  → Genera código para un paso del plan
"""
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.middleware.platform_auth_middleware import require_platform_user
from app.services.crew_service import DevCrewService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platform/crew", tags=["devcrew"])

_crew = DevCrewService()


# ─── Modelos ──────────────────────────────────────────────────────────────────

class PlanRequest(BaseModel):
    task: str = Field(..., min_length=10, max_length=4000,
                      description="Descripción de la tarea de desarrollo")
    tech_stack: str = Field(
        "Python, FastAPI, Supabase",
        max_length=200,
        description="Tecnologías del proyecto"
    )
    context: str = Field(
        "",
        max_length=2000,
        description="Contexto adicional: arquitectura, restricciones, etc."
    )
    agent_id: Optional[str] = Field(
        None,
        description="UUID del agente a usar (opcional)"
    )
    tier: str = Field(
        "balanced",
        pattern=r"^(fast|balanced|pro)$",
        description="Tier del provider si no se especifica agente"
    )


class WriteRequest(BaseModel):
    step_title: str = Field(..., min_length=3, max_length=200,
                            description="Título del paso del plan")
    step_description: str = Field(..., min_length=10, max_length=2000,
                                  description="Descripción detallada del paso")
    files: List[str] = Field(
        default_factory=list,
        max_length=10,
        description="Rutas de los archivos a crear/modificar"
    )
    existing_code: str = Field(
        "",
        max_length=8000,
        description="Código existente en el archivo (contexto)"
    )
    agent_id: Optional[str] = Field(None, description="UUID del agente (opcional)")
    tier: str = Field(
        "balanced",
        pattern=r"^(fast|balanced|pro)$",
        description="Tier del provider"
    )


class AgentStepMessage(BaseModel):
    role: str = Field(..., description="Rol en el chat: user o assistant")
    content: str = Field(..., description="Contenido del mensaje")


class AgentStepRequest(BaseModel):
    messages: List[AgentStepMessage] = Field(..., description="Historial de mensajes de la conversación ReAct")
    tier: str = Field(
        "balanced",
        pattern=r"^(fast|balanced|pro)$",
        description="Tier del provider"
    )
    agent_id: Optional[str] = Field(None, description="UUID del agente a usar (opcional)")



# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post(
    "/plan",
    summary="Generar plan de implementación con IA",
    description=(
        "Analiza la descripción de la tarea y devuelve un plan de implementación "
        "estructurado con pasos ordenados, archivos afectados, estimación de tiempo "
        "y riesgos identificados."
    ),
    status_code=status.HTTP_200_OK,
)
def generate_plan(
    req: PlanRequest,
    user: dict = Depends(require_platform_user),
):
    try:
        plan = _crew.generate_plan(
            user_id=user["user_id"],
            task=req.task,
            tech_stack=req.tech_stack,
            context=req.context,
            agent_id=req.agent_id,
            tier=req.tier,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"DevCrew /plan error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al generar el plan."
        )
    return plan


@router.post(
    "/write",
    summary="Generar código para un paso del plan",
    description=(
        "Genera código completo y funcional para un paso concreto del plan. "
        "El código se devuelve listo para copiar, junto con notas de integración."
    ),
    status_code=status.HTTP_200_OK,
)
def generate_code(
    req: WriteRequest,
    user: dict = Depends(require_platform_user),
):
    try:
        result = _crew.generate_code(
            user_id=user["user_id"],
            step_title=req.step_title,
            step_description=req.step_description,
            files=req.files,
            existing_code=req.existing_code,
            agent_id=req.agent_id,
            tier=req.tier,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"DevCrew /write error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al generar el código."
        )
    return result


@router.post(
    "/agent-step",
    summary="Obtener el siguiente paso del agente ReAct local",
    description=(
        "Recibe el historial de la conversación del agente autónomo local, "
        "aplica el prompt de sistema del agente ReAct y devuelve el pensamiento y "
        "acción de la herramienta en formato estructurado."
    ),
    status_code=status.HTTP_200_OK,
)
def generate_agent_step(
    req: AgentStepRequest,
    user: dict = Depends(require_platform_user),
):
    try:
        # Convertir mensajes de Pydantic a lista de dicts
        msg_dicts = [{"role": m.role, "content": m.content} for m in req.messages]
        result = _crew.agent_step(
            user_id=user["user_id"],
            messages=msg_dicts,
            tier=req.tier,
            agent_id=req.agent_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"DevCrew /agent-step error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno en el agente autónomo."
        )
    return result

