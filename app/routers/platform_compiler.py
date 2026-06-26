"""
platform_compiler.py
Router del compilador AFT (Adaptive Fractal Tuning) — Arzor AIs Platform.
Fase 3: endpoint para compilar el perfil de un agente desde su descripción informal.
"""
import logging
from fastapi import APIRouter, HTTPException, Depends, status, BackgroundTasks

from app.services.aft_models import CompileProfileRequest
from app.services.instruction_compiler_service import compile_aft_profile, compile_and_save
from app.services.agent_service import agent_service
from app.middleware.platform_auth_middleware import require_platform_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platform/compiler", tags=["aft-compiler"])


# ─── POST /platform/compiler/preview ─────────────────────────────────────────
@router.post(
    "/preview",
    summary="Compilar perfil AFT (sin guardar)",
    description=(
        "Genera y devuelve el perfil AFT compilado a partir de la descripción del agente. "
        "No guarda nada — útil para previsualizar antes de confirmar."
    ),
)
async def preview_profile(
    body: CompileProfileRequest,
    current_user: dict = Depends(require_platform_user),
):
    """
    Compila el perfil AFT sin guardarlo.
    El usuario puede revisar el resultado antes de aplicarlo al agente.
    """
    try:
        profile = compile_aft_profile(body)
        return {
            "status": "compiled",
            "profile": profile.model_dump(),
            "summary": {
                "system_instructions_length": len(profile.system_instructions),
                "behavior_examples_count": len(profile.behavior_examples),
                "style_tone": profile.style_rules.tone,
                "expertise_level": profile.domain_constraints.expertise_level,
                "trigger_keywords_count": len(profile.retrieval_profile.trigger_keywords),
            },
        }
    except RuntimeError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error inesperado en /compiler/preview: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno durante la compilación AFT.",
        )


# ─── POST /platform/compiler/agents/{agent_id}/compile ───────────────────────
@router.post(
    "/agents/{agent_id}/compile",
    status_code=status.HTTP_201_CREATED,
    summary="Compilar y guardar perfil AFT como nueva versión del agente",
    description=(
        "Compila el perfil AFT y lo guarda como nueva versión del agente. "
        "La versión anterior queda preservada para rollback."
    ),
)
async def compile_agent(
    agent_id: str,
    body: CompileProfileRequest,
    current_user: dict = Depends(require_platform_user),
):
    """
    Flujo completo:
    1. Verifica que el usuario es el dueño del agente.
    2. Compila el perfil AFT (hasta 3 intentos con backoff).
    3. Guarda el resultado como nueva versión en agent_versions.
    4. Actualiza current_version_id del agente.
    5. Devuelve el perfil compilado + metadatos de la versión guardada.
    """
    user_id = current_user["user_id"]

    # Verificar que el agente existe y pertenece al usuario
    try:
        agent_service.get_agent(agent_id=agent_id, user_id=user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if "encontrado" in str(e) else status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )

    try:
        result = compile_and_save(
            req=body,
            agent_id=agent_id,
            user_id=user_id,
        )
        return {
            "status": "compiled_and_saved",
            "agent_id": agent_id,
            "version": result["version"],
            "profile_summary": {
                "system_instructions_length": len(result["profile"]["system_instructions"]),
                "behavior_examples_count": len(result["profile"]["behavior_examples"]),
                "style_tone": result["profile"]["style_rules"]["tone"],
                "expertise_level": result["profile"]["domain_constraints"]["expertise_level"],
                "trigger_keywords": result["profile"]["retrieval_profile"]["trigger_keywords"][:5],
                "aft_version": result["profile"]["aft_version"],
                "compiled_at": result["profile"]["compiled_at"],
            },
        }
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except Exception as e:
        logger.error(f"Error inesperado compilando agente {agent_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno durante la compilación AFT.",
        )
