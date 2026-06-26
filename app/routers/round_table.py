"""
round_table.py
Router para los debates multi-agente Arzor Round Table.
Implementado en Fase 8.
"""
from fastapi import APIRouter

router = APIRouter(prefix="/platform/round-table", tags=["round-table"])

# Los endpoints se implementarán en la Fase 8:
# POST /platform/round-table              - crear nueva mesa
# GET  /platform/round-table             - listar mesas del usuario
# POST /platform/round-table/{table_id}/members  - añadir agente a la mesa
# POST /platform/round-table/{table_id}/start    - iniciar debate
# GET  /platform/round-table/{table_id}/result   - obtener resultado del debate
