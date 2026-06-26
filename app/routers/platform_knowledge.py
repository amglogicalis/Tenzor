"""
platform_knowledge.py
Router de gestión de documentos / knowledge base por agente.
Implementado en Fase 5.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/platform/knowledge", tags=["platform-knowledge"])

# Los endpoints se implementarán en la Fase 5:
# POST   /platform/knowledge/{agent_id}/upload  - subir archivo
# GET    /platform/knowledge/{agent_id}/files   - listar archivos del agente
# DELETE /platform/knowledge/{agent_id}/files/{file_id} - borrar archivo
