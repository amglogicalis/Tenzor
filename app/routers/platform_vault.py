import io
import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, status, UploadFile, File, Form, Query
from pydantic import BaseModel

from app.middleware.platform_auth_middleware import require_platform_user
from app.services.agent_vault_service import AgentVaultService
from app.db import supabase_admin

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platform/agents/{agent_id}/vault", tags=["platform-vault"])
vault_service = AgentVaultService()

# ─── Modelos Pydantic para Sincronización Incremental ──────────────────────────
class VaultSyncItem(BaseModel):
    file_name: str
    content: str
    file_type: str

class VaultSyncRequest(BaseModel):
    files: List[VaultSyncItem]

# ─── Helper de validación de propiedad del agente ──────────────────────────────
def validate_agent_ownership(agent_id: str, user_id: str, allow_public_read: bool = False) -> Dict[str, Any]:
    """
    Valida que el agente exista y pertenezca al usuario actual.
    Si allow_public_read es True, permite lectura si el agente es público.
    """
    res = supabase_admin.table("custom_agents")\
        .select("id, user_id, is_public")\
        .eq("id", agent_id)\
        .execute()
    
    if not res.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agente personalizado no encontrado."
        )
    
    agent = res.data[0]
    if agent["user_id"] != user_id:
        if allow_public_read and agent["is_public"]:
            return agent
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para modificar este agente."
        )
    return agent

# ─── GET /platform/agents/{agent_id}/vault ────────────────────────────────────
@router.get(
    "",
    summary="Listar archivos del cerebro del agente",
)
async def list_vault_files(
    agent_id: str,
    current_user: dict = Depends(require_platform_user)
):
    """Devuelve la lista de documentos de conocimiento indexados para este agente."""
    validate_agent_ownership(agent_id, current_user["user_id"], allow_public_read=True)
    
    res = supabase_admin.table("agent_vault_documents")\
        .select("id, file_name, file_type, content_hash, tags, created_at, updated_at")\
        .eq("agent_id", agent_id)\
        .order("file_name")\
        .execute()
        
    return {"files": res.data or [], "total": len(res.data or [])}

# ─── POST /platform/agents/{agent_id}/vault/upload ────────────────────────────
@router.post(
    "/upload",
    summary="Subir y procesar un archivo para el RAG del agente",
)
async def upload_vault_file(
    agent_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(require_platform_user)
):
    """Sube un archivo (PDF, MD o TXT), lo segmenta y calcula sus embeddings vectoriales."""
    validate_agent_ownership(agent_id, current_user["user_id"])
    
    filename = file.filename
    content_type = file.content_type
    
    # Determinar tipo por extensión
    ext = filename.split(".")[-1].lower() if "." in filename else ""
    if ext not in ("pdf", "md", "txt"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de archivo no soportado. Debe ser .pdf, .md o .txt"
        )
        
    raw_bytes = await file.read()
    
    # Extraer texto crudo
    content_str = ""
    if ext == "pdf":
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
            text_parts = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
            content_str = "\n".join(text_parts)
        except ImportError:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Soporte PDF no disponible (pypdf no instalado)."
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error al leer el archivo PDF: {e}"
            )
    else:
        # Markdown / TXT
        try:
            content_str = raw_bytes.decode("utf-8", errors="replace")
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Error de codificación de texto: {e}"
            )
            
    if not content_str.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo está vacío o no contiene texto legible."
        )
        
    try:
        result = vault_service.ingest_file(
            agent_id=agent_id,
            filename=filename,
            file_type=ext,
            content=content_str
        )
        return result
    except Exception as e:
        logger.exception("Error al procesar archivo en el Vault")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error en el servidor al indexar el RAG: {e}"
        )

# ─── POST /platform/agents/{agent_id}/vault/sync ──────────────────────────────
@router.post(
    "/sync",
    summary="Sincronización incremental de archivos (para el CLI)",
)
async def sync_vault_files(
    agent_id: str,
    payload: VaultSyncRequest,
    current_user: dict = Depends(require_platform_user)
):
    """Procesa un lote de archivos de texto crudo (Markdown/TXT) sincronizándolos con el RAG."""
    validate_agent_ownership(agent_id, current_user["user_id"])
    
    results = []
    for item in payload.files:
        if item.file_type not in ("md", "txt"):
            results.append({"file_name": item.file_name, "status": "error", "detail": "Solo .md y .txt son soportados en sync masivo."})
            continue
        try:
            res = vault_service.ingest_file(
                agent_id=agent_id,
                filename=item.file_name,
                file_type=item.file_type,
                content=item.content
            )
            results.append({"file_name": item.file_name, "status": res["status"], "document_id": res.get("document_id")})
        except Exception as e:
            logger.error(f"Error sincronizando {item.file_name}: {e}")
            results.append({"file_name": item.file_name, "status": "error", "detail": str(e)})
            
    return {"results": results}

# ─── DELETE /platform/agents/{agent_id}/vault/files/{file_id} ─────────────────
@router.delete(
    "/files/{file_id}",
    summary="Eliminar archivo del cerebro del agente",
)
async def delete_vault_file(
    agent_id: str,
    file_id: str,
    current_user: dict = Depends(require_platform_user)
):
    """Elimina el archivo y limpia todas sus referencias y embeddings de Supabase."""
    validate_agent_ownership(agent_id, current_user["user_id"])
    
    # Comprobar que pertenece al agente
    check = supabase_admin.table("agent_vault_documents")\
        .select("id")\
        .eq("id", file_id)\
        .eq("agent_id", agent_id)\
        .execute()
        
    if not check.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Archivo no encontrado en el Vault de este agente."
        )
        
    # Eliminar (la cascada en Postgres limpia embeddings y relaciones de forma transparente)
    supabase_admin.table("agent_vault_documents").delete().eq("id", file_id).execute()
    return {"status": "deleted", "file_id": file_id}
