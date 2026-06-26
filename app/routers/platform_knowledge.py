"""
platform_knowledge.py
Router de gestión de documentos / knowledge base por agente.
Fase 4: subida de archivos, listado, borrado y estadísticas.
"""
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Query, status

from app.services.platform_rag_service import platform_rag_service
from app.services.agent_service import agent_service
from app.middleware.platform_auth_middleware import require_platform_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platform/knowledge", tags=["platform-knowledge"])


# ─── POST /platform/knowledge/{agent_id}/upload ───────────────────────────────
@router.post(
    "/{agent_id}/upload",
    status_code=status.HTTP_201_CREATED,
    summary="Subir documento a la knowledge base del agente",
)
async def upload_document(
    agent_id: str,
    file: UploadFile = File(..., description="Archivo PDF, TXT o MD (máx. 10 MB)"),
    chunk_size: int = Query(600, ge=100, le=2000, description="Tamaño de chunk en chars"),
    chunk_overlap: int = Query(120, ge=0, le=400, description="Solapamiento entre chunks"),
    current_user: dict = Depends(require_platform_user),
):
    """
    Sube un archivo y lo indexa en la knowledge base del agente.

    Flujo interno:
    1. Verifica que el usuario es dueño del agente.
    2. Lee el archivo en memoria.
    3. Extrae el texto (PDF/TXT/MD).
    4. Divide en chunks con solapamiento.
    5. Inserta chunks en `agent_knowledge` con índice full-text tsv.
    6. Devuelve estadísticas de indexación.

    > Una vez indexado, el agente usará estos documentos como contexto RAG
    > cuando la consulta del usuario active palabras clave del `retrieval_profile`.
    """
    user_id = current_user["user_id"]

    # 1. Verificar que el agente existe y el usuario es el dueño
    try:
        agent_service.get_agent(agent_id=agent_id, user_id=user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if "encontrado" in str(e) else status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )

    # 2. Leer el archivo
    try:
        raw_bytes = await file.read()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se pudo leer el archivo: {e}",
        )

    if not raw_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo está vacío.",
        )

    # 3. Indexar
    try:
        result = platform_rag_service.ingest_file(
            agent_id=agent_id,
            user_id=user_id,
            filename=file.filename or "documento.txt",
            content_type=file.content_type or "text/plain",
            raw_bytes=raw_bytes,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        return {
            "message": f"Archivo indexado correctamente con {result['chunks_created']} chunks.",
            **result,
        }
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error inesperado indexando archivo para agente {agent_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno procesando el archivo.",
        )


# ─── GET /platform/knowledge/{agent_id}/files ─────────────────────────────────
@router.get(
    "/{agent_id}/files",
    summary="Listar archivos indexados del agente",
)
async def list_files(
    agent_id: str,
    current_user: dict = Depends(require_platform_user),
):
    """
    Lista todos los archivos indexados en la knowledge base del agente,
    con su estado (processing / ready / error) y estadísticas.
    """
    user_id = current_user["user_id"]
    try:
        agent_service.get_agent(agent_id=agent_id, user_id=user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if "encontrado" in str(e) else status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    files = platform_rag_service.list_files(agent_id=agent_id, user_id=user_id)
    return {"files": files, "total": len(files)}


# ─── GET /platform/knowledge/{agent_id}/stats ─────────────────────────────────
@router.get(
    "/{agent_id}/stats",
    summary="Estadísticas de la knowledge base del agente",
)
async def get_stats(
    agent_id: str,
    current_user: dict = Depends(require_platform_user),
):
    """
    Devuelve estadísticas de la knowledge base:
    número de archivos (por estado) y total de chunks indexados.
    """
    user_id = current_user["user_id"]
    try:
        agent_service.get_agent(agent_id=agent_id, user_id=user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if "encontrado" in str(e) else status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    stats = platform_rag_service.get_agent_knowledge_stats(agent_id=agent_id)
    return {"agent_id": agent_id, **stats}


# ─── DELETE /platform/knowledge/{agent_id}/files/{file_id} ────────────────────
@router.delete(
    "/{agent_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Borrar archivo de la knowledge base",
)
async def delete_file(
    agent_id: str,
    file_id: str,
    current_user: dict = Depends(require_platform_user),
):
    """
    Borra un archivo y todos sus chunks (CASCADE).
    Sólo el dueño del agente puede borrar.
    """
    user_id = current_user["user_id"]
    try:
        platform_rag_service.delete_file(file_id=file_id, user_id=user_id)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Error borrando archivo {file_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno al borrar el archivo.",
        )


# ─── POST /platform/knowledge/{agent_id}/search ───────────────────────────────
@router.post(
    "/{agent_id}/search",
    summary="Búsqueda en la knowledge base del agente (debug/test)",
)
async def search_knowledge(
    agent_id: str,
    query: str = Query(..., min_length=3, description="Texto a buscar"),
    top_k: int = Query(5, ge=1, le=20),
    current_user: dict = Depends(require_platform_user),
):
    """
    Endpoint de prueba para buscar directamente en la knowledge base.
    Útil para verificar que los documentos se indexaron correctamente
    antes de conectarlos al chat del agente.
    """
    user_id = current_user["user_id"]
    try:
        agent_service.get_agent(agent_id=agent_id, user_id=user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND if "encontrado" in str(e) else status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )

    chunks = platform_rag_service.search(
        agent_id=agent_id,
        query=query,
        top_k=top_k,
    )
    return {
        "query": query,
        "results_count": len(chunks),
        "results": [
            {
                "chunk_id": c.chunk_id,
                "rank": round(c.rank, 4),
                "heading": c.heading,
                "concept_node": c.concept_node,
                "content_preview": c.content[:300] + ("..." if len(c.content) > 300 else ""),
                "metadata": c.metadata,
            }
            for c in chunks
        ],
    }
