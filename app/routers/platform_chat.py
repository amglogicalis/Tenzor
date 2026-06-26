"""
platform_chat.py
Router de chat con agentes personalizados de la plataforma Arzor.
Implementado en Fase 6.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/platform/chat", tags=["platform-chat"])

# Los endpoints se implementarán en la Fase 6:
# POST /platform/chat/{agent_id}              - iniciar o continuar sesión de chat
# GET  /platform/chat/sessions                - listar sesiones del usuario
# GET  /platform/chat/sessions/{session_id}   - historial de una sesión
# DELETE /platform/chat/sessions/{session_id} - borrar sesión
