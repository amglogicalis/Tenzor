"""
platform_agents.py
Router CRUD de agentes personalizados para la plataforma Arzor.
Implementado en Fase 2.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/platform/agents", tags=["platform-agents"])

# Los endpoints se implementarán en la Fase 2:
# GET    /platform/agents              - listar mis agentes
# POST   /platform/agents              - crear agente
# GET    /platform/agents/{agent_id}   - obtener agente
# PATCH  /platform/agents/{agent_id}   - editar agente
# DELETE /platform/agents/{agent_id}   - borrar agente (soft-delete)
# POST   /platform/agents/{agent_id}/publish   - publicar agente
# GET    /platform/agents/library      - biblioteca pública
