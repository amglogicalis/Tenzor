"""
platform_rag_service.py
RAG por agente: subida, extracción, chunking e indexación de documentos.
Búsqueda full-text via tsv_content (PostgreSQL GIN + Supabase).
Fase 4 completa.

Flujo de ingesta:
  1. Usuario sube archivo (PDF / TXT / MD / DOCX básico)
  2. Se inserta registro en agent_files (status='processing')
  3. Se extrae el texto crudo
  4. Se divide en chunks con solapamiento configurable
  5. Se insertan los chunks en agent_knowledge
  6. Se actualiza el status a 'ready'

Flujo de recuperación:
  1. La query del usuario se limpia y tokeniza
  2. Se ejecuta búsqueda FTS en tsv_content (postgres tsquery)
  3. Se ordena por relevancia (ts_rank)
  4. Se devuelven los top_k chunks con metadata
"""
import io
import re
import logging
from typing import Optional, List, Dict, Any

from supabase import Client
from app import config
from app.db import supabase_admin

logger = logging.getLogger(__name__)

# ─── Configuración de chunking ─────────────────────────────────────────────────
DEFAULT_CHUNK_SIZE = 600      # caracteres por chunk (aprox 150 tokens)
DEFAULT_CHUNK_OVERLAP = 120   # solapamiento entre chunks
MAX_CHUNKS_PER_FILE = 500     # límite de seguridad
MAX_FILE_SIZE_MB = 10         # límite de tamaño de archivo


# ─── Clase resultado de búsqueda ──────────────────────────────────────────────
class KnowledgeChunk:
    def __init__(self, chunk_id: str, agent_id: str, file_id: Optional[str],
                 chunk_index: int, heading: Optional[str],
                 concept_node: Optional[str], content: str,
                 metadata: dict, rank: float = 0.0):
        self.chunk_id = chunk_id
        self.agent_id = agent_id
        self.file_id = file_id
        self.chunk_index = chunk_index
        self.heading = heading
        self.concept_node = concept_node
        self.content = content
        self.metadata = metadata
        self.rank = rank

    def to_context_string(self) -> str:
        parts = []
        if self.heading:
            parts.append(f"[{self.heading}]")
        if self.concept_node:
            parts.append(f"({self.concept_node})")
        parts.append(self.content)
        return " ".join(parts)


# ─── Servicio principal ────────────────────────────────────────────────────────
class PlatformRAGService:
    """
    Gestiona la knowledge base por agente:
    - Subida y procesamiento de documentos (PDF, TXT, MD)
    - Chunking con solapamiento
    - Indexación full-text en Supabase (tsv_content / GIN)
    - Búsqueda semántica FTS (ts_rank)
    - Listado y borrado de archivos
    """

    def __init__(self):
        self.supabase: Optional[Client] = supabase_admin
        if not self.supabase:
            logger.warning("PlatformRAGService: Supabase no configurado.")
        else:
            logger.info("PlatformRAGService: usando cliente admin (service_role).")

    # ──────────────────────────────────────────────────────────────────────────
    # INGESTA DE ARCHIVOS
    # ──────────────────────────────────────────────────────────────────────────

    def ingest_file(
        self,
        agent_id: str,
        user_id: str,
        filename: str,
        content_type: str,
        raw_bytes: bytes,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> Dict[str, Any]:
        """
        Procesa un archivo completo: extrae texto, lo divide en chunks
        y los indexa en Supabase. Devuelve el file_record con estadísticas.

        Args:
            agent_id:     UUID del agente al que pertenece este conocimiento.
            user_id:      UUID del dueño (para RLS).
            filename:     Nombre original del archivo.
            content_type: MIME type: 'application/pdf', 'text/plain', 'text/markdown'.
            raw_bytes:    Contenido binario del archivo.
            chunk_size:   Tamaño de cada chunk en caracteres.
            chunk_overlap: Solapamiento entre chunks consecutivos.

        Returns:
            dict con file_id, chunks_created, status.

        Raises:
            ValueError: si el archivo es demasiado grande o el tipo no está soportado.
        """
        self._require_supabase()

        # 1. Validar tamaño
        size_mb = len(raw_bytes) / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            raise ValueError(
                f"El archivo supera el límite de {MAX_FILE_SIZE_MB} MB ({size_mb:.1f} MB)."
            )

        # 2. Validar tipo
        supported_types = {
            "application/pdf", "text/plain", "text/markdown",
            "text/x-markdown", "application/octet-stream",
        }
        # También aceptar por extensión si el MIME es genérico
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        ext_map = {"pdf": "application/pdf", "txt": "text/plain",
                   "md": "text/markdown", "markdown": "text/markdown"}
        resolved_type = content_type if content_type in supported_types else ext_map.get(ext)
        if not resolved_type:
            raise ValueError(
                f"Tipo de archivo no soportado: '{content_type}' (.{ext}). "
                "Se aceptan: PDF, TXT, MD."
            )

        # 3. Crear registro en agent_files (status=processing)
        try:
            file_resp = (
                self.supabase.table("agent_files")
                .insert({
                    "agent_id": agent_id,
                    "user_id": user_id,
                    "filename": filename,
                    "content_type": resolved_type,
                    "file_size_bytes": len(raw_bytes),
                    "status": "processing",
                })
                .execute()
            )
            file_record = file_resp.data[0]
            file_id = file_record["id"]
        except Exception as e:
            logger.error(f"Error creando registro de archivo: {e}")
            raise ValueError("No se pudo registrar el archivo.")

        # 4. Extraer texto
        try:
            text = self._extract_text(raw_bytes, resolved_type, filename)
        except Exception as e:
            self._mark_file_error(file_id, str(e))
            raise ValueError(f"Error extrayendo texto del archivo: {e}")

        if not text.strip():
            self._mark_file_error(file_id, "El archivo no contiene texto extraíble.")
            raise ValueError("El archivo parece estar vacío o no tiene texto extraíble.")

        # 5. Dividir en chunks
        chunks = self._chunk_text(text, chunk_size=chunk_size, overlap=chunk_overlap)
        if not chunks:
            self._mark_file_error(file_id, "No se pudieron generar chunks del texto.")
            raise ValueError("No se pudieron generar chunks del texto.")

        chunks = chunks[:MAX_CHUNKS_PER_FILE]
        logger.info(f"RAG: {len(chunks)} chunks generados de '{filename}'")

        # 6. Insertar chunks en agent_knowledge
        try:
            chunk_records = []
            for i, chunk in enumerate(chunks):
                heading = self._extract_heading(chunk)
                concept = self._extract_concept(chunk)
                chunk_records.append({
                    "agent_id": agent_id,
                    "file_id": file_id,
                    "chunk_index": i,
                    "heading": heading,
                    "concept_node": concept,
                    "content": chunk,
                    "metadata": {
                        "filename": filename,
                        "char_start": sum(len(c) for c in chunks[:i]),
                        "char_count": len(chunk),
                        "chunk_size": chunk_size,
                        "overlap": chunk_overlap,
                    },
                })

            # Insertar en batches de 50 para evitar payloads enormes
            batch_size = 50
            inserted = 0
            for batch_start in range(0, len(chunk_records), batch_size):
                batch = chunk_records[batch_start:batch_start + batch_size]
                self.supabase.table("agent_knowledge").insert(batch).execute()
                inserted += len(batch)

        except Exception as e:
            self._mark_file_error(file_id, f"Error indexando chunks: {e}")
            logger.error(f"Error insertando chunks en agent_knowledge: {e}")
            raise ValueError("Error indexando el contenido del archivo.")

        # 7. Marcar archivo como listo
        try:
            self.supabase.table("agent_files").update({
                "status": "ready",
            }).eq("id", file_id).execute()
        except Exception as e:
            logger.error(f"Error actualizando status del archivo {file_id}: {e}")

        logger.info(f"RAG: archivo '{filename}' indexado. {inserted} chunks en agente {agent_id}.")
        return {
            "file_id": file_id,
            "filename": filename,
            "chunks_created": inserted,
            "file_size_bytes": len(raw_bytes),
            "status": "ready",
        }

    # ──────────────────────────────────────────────────────────────────────────
    # BÚSQUEDA
    # ──────────────────────────────────────────────────────────────────────────

    def search(
        self,
        agent_id: str,
        query: str,
        top_k: int = 5,
        relevance_threshold: float = 0.0,
    ) -> List[KnowledgeChunk]:
        """
        Búsqueda full-text en la knowledge base del agente.
        Usa PostgreSQL tsquery con ts_rank para ordenar por relevancia.

        Args:
            agent_id:           UUID del agente.
            query:              Texto de búsqueda del usuario.
            top_k:              Máximo de chunks a devolver.
            relevance_threshold: Umbral mínimo de ts_rank (0=desactivado).

        Returns:
            Lista de KnowledgeChunk ordenados por relevancia descendente.
        """
        self._require_supabase()

        if not query.strip():
            return []

        tsquery = self._build_tsquery(query)
        if not tsquery:
            return []

        try:
            # Usar RPC de Supabase para pasar la tsquery directamente
            # Equivale a: SELECT *, ts_rank(tsv_content, to_tsquery('spanish', tsquery)) as rank
            #              FROM agent_knowledge
            #              WHERE agent_id = $1 AND tsv_content @@ to_tsquery('spanish', tsquery)
            #              ORDER BY rank DESC LIMIT top_k
            resp = self.supabase.rpc(
                "search_agent_knowledge",
                {
                    "p_agent_id": agent_id,
                    "p_tsquery": tsquery,
                    "p_top_k": min(top_k, 20),
                }
            ).execute()

            results = []
            for row in (resp.data or []):
                rank = float(row.get("rank", 0.0))
                if rank < relevance_threshold:
                    continue
                results.append(KnowledgeChunk(
                    chunk_id=row["id"],
                    agent_id=row["agent_id"],
                    file_id=row.get("file_id"),
                    chunk_index=row["chunk_index"],
                    heading=row.get("heading"),
                    concept_node=row.get("concept_node"),
                    content=row["content"],
                    metadata=row.get("metadata", {}),
                    rank=rank,
                ))
            return results

        except Exception as e:
            logger.error(f"Error en búsqueda RAG para agente {agent_id}: {e}")
            # Fallback: búsqueda simple por LIKE si la RPC falla
            return self._fallback_search(agent_id, query, top_k)

    def _fallback_search(self, agent_id: str, query: str, top_k: int) -> List[KnowledgeChunk]:
        """
        Búsqueda de respaldo simple con ILIKE si la RPC no está disponible.
        Menos relevancia pero funciona sin la función SQL custom.
        """
        try:
            keywords = [w.strip() for w in query.split() if len(w.strip()) > 3][:3]
            if not keywords:
                return []
            # Buscar por el primer keyword relevante
            resp = (
                self.supabase.table("agent_knowledge")
                .select("*")
                .eq("agent_id", agent_id)
                .ilike("content", f"%{keywords[0]}%")
                .limit(top_k)
                .execute()
            )
            return [
                KnowledgeChunk(
                    chunk_id=row["id"],
                    agent_id=row["agent_id"],
                    file_id=row.get("file_id"),
                    chunk_index=row["chunk_index"],
                    heading=row.get("heading"),
                    concept_node=row.get("concept_node"),
                    content=row["content"],
                    metadata=row.get("metadata", {}),
                    rank=0.5,  # rank genérico para fallback
                )
                for row in (resp.data or [])
            ]
        except Exception as e:
            logger.error(f"Fallback search también falló: {e}")
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # GESTIÓN DE ARCHIVOS
    # ──────────────────────────────────────────────────────────────────────────

    def list_files(self, agent_id: str, user_id: str) -> List[Dict[str, Any]]:
        """Lista los archivos indexados de un agente."""
        self._require_supabase()
        try:
            resp = (
                self.supabase.table("agent_files")
                .select("id, filename, content_type, file_size_bytes, status, error_message, created_at")
                .eq("agent_id", agent_id)
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .execute()
            )
            return resp.data or []
        except Exception as e:
            logger.error(f"Error listando archivos del agente {agent_id}: {e}")
            return []

    def delete_file(self, file_id: str, user_id: str) -> None:
        """
        Borra un archivo y todos sus chunks (CASCADE via FK).
        Verifica que el usuario sea el dueño.
        """
        self._require_supabase()
        try:
            # Verificar propiedad
            check = (
                self.supabase.table("agent_files")
                .select("id")
                .eq("id", file_id)
                .eq("user_id", user_id)
                .execute()
            )
            if not check.data:
                raise ValueError("Archivo no encontrado o sin permiso para borrarlo.")
            # Borrar (CASCADE borra agent_knowledge automáticamente)
            self.supabase.table("agent_files").delete().eq("id", file_id).execute()
            logger.info(f"RAG: archivo {file_id} borrado por user {user_id}")
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error borrando archivo {file_id}: {e}")
            raise ValueError("No se pudo borrar el archivo.")

    def get_agent_knowledge_stats(self, agent_id: str) -> Dict[str, Any]:
        """Devuelve estadísticas de la knowledge base del agente."""
        self._require_supabase()
        try:
            files_resp = (
                self.supabase.table("agent_files")
                .select("id, status", count="exact")
                .eq("agent_id", agent_id)
                .execute()
            )
            chunks_resp = (
                self.supabase.table("agent_knowledge")
                .select("id", count="exact")
                .eq("agent_id", agent_id)
                .execute()
            )
            files = files_resp.data or []
            ready_count = sum(1 for f in files if f.get("status") == "ready")
            return {
                "total_files": files_resp.count or 0,
                "ready_files": ready_count,
                "processing_files": sum(1 for f in files if f.get("status") == "processing"),
                "error_files": sum(1 for f in files if f.get("status") == "error"),
                "total_chunks": chunks_resp.count or 0,
            }
        except Exception as e:
            logger.error(f"Error obteniendo stats de {agent_id}: {e}")
            return {}

    # ──────────────────────────────────────────────────────────────────────────
    # EXTRACCIÓN DE TEXTO
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_text(self, raw_bytes: bytes, content_type: str, filename: str) -> str:
        """Extrae texto plano de PDF, TXT o MD."""
        if content_type == "application/pdf":
            return self._extract_pdf(raw_bytes)
        elif content_type in ("text/plain", "text/markdown", "text/x-markdown"):
            # Decodificar intentando UTF-8, fallback latin-1
            for encoding in ("utf-8", "latin-1", "cp1252"):
                try:
                    return raw_bytes.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return raw_bytes.decode("utf-8", errors="replace")
        else:
            # Intentar como texto
            return raw_bytes.decode("utf-8", errors="replace")

    def _extract_pdf(self, raw_bytes: bytes) -> str:
        """Extrae texto de PDF usando pypdf."""
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
            pages = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    pages.append(text.strip())
            return "\n\n".join(pages)
        except ImportError:
            raise ValueError("pypdf no está instalado. Añádelo con: pip install pypdf")
        except Exception as e:
            raise ValueError(f"Error leyendo el PDF: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # CHUNKING
    # ──────────────────────────────────────────────────────────────────────────

    def _chunk_text(
        self,
        text: str,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> List[str]:
        """
        Divide el texto en chunks con solapamiento.
        Estrategia: primero intenta dividir por párrafos/secciones naturales;
        si el párrafo es demasiado largo, lo divide por sentences o chars.
        """
        # Normalizar saltos de línea
        text = re.sub(r"\r\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

        # Intentar dividir primero por bloques naturales (párrafos / secciones MD)
        blocks = self._split_by_natural_blocks(text)

        chunks = []
        current_chunk = ""

        for block in blocks:
            block = block.strip()
            if not block:
                continue

            # Si el bloque cabe en el chunk actual (con margen de solapamiento)
            if len(current_chunk) + len(block) + 1 <= chunk_size:
                current_chunk = (current_chunk + "\n\n" + block).strip()
            else:
                # Guardar chunk actual si tiene contenido
                if current_chunk.strip():
                    chunks.append(current_chunk.strip())

                # Si el bloque es más grande que chunk_size, dividir
                if len(block) > chunk_size:
                    sub_chunks = self._split_by_chars(block, chunk_size, overlap)
                    chunks.extend(sub_chunks[:-1])
                    current_chunk = sub_chunks[-1] if sub_chunks else ""
                else:
                    # Solapamiento: tomar los últimos `overlap` chars del chunk anterior
                    if chunks and overlap > 0:
                        tail = chunks[-1][-overlap:] if len(chunks[-1]) > overlap else chunks[-1]
                        current_chunk = (tail + "\n\n" + block).strip()
                    else:
                        current_chunk = block

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

        # Filtrar chunks demasiado cortos (< 50 chars, probablemente basura)
        return [c for c in chunks if len(c.strip()) >= 50]

    def _split_by_natural_blocks(self, text: str) -> List[str]:
        """Divide por bloques naturales: encabezados MD, párrafos dobles."""
        # Primero por encabezados markdown
        parts = re.split(r"(?m)^(#{1,4}\s+.+)$", text)
        if len(parts) > 3:
            # Reagrupar: encabezado + su contenido
            blocks = []
            i = 0
            while i < len(parts):
                if i + 1 < len(parts):
                    blocks.append((parts[i] + "\n" + parts[i + 1]).strip())
                    i += 2
                else:
                    blocks.append(parts[i].strip())
                    i += 1
            return [b for b in blocks if b]

        # Si no hay encabezados, dividir por párrafos dobles
        return [p.strip() for p in text.split("\n\n") if p.strip()]

    def _split_by_chars(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """Divide un texto largo por caracteres con solapamiento."""
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + chunk_size, len(text))
            # Intentar cortar en un espacio para no partir palabras
            if end < len(text):
                space_idx = text.rfind(" ", start, end)
                if space_idx > start:
                    end = space_idx
            chunks.append(text[start:end].strip())
            start = end - overlap if end - overlap > start else end
        return [c for c in chunks if c.strip()]

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS DE METADATA
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_heading(self, chunk: str) -> Optional[str]:
        """Extrae el encabezado Markdown del chunk si existe."""
        match = re.match(r"^(#{1,4})\s+(.+)", chunk.strip())
        if match:
            return match.group(2).strip()[:200]
        # Primera línea si es corta y parece un título
        first_line = chunk.strip().split("\n")[0]
        if len(first_line) < 80 and not first_line.endswith("."):
            return first_line[:200]
        return None

    def _extract_concept(self, chunk: str) -> Optional[str]:
        """
        Intenta etiquetar semánticamente el chunk con una palabra clave.
        Simple heurística: palabra más frecuente que no sea stopword.
        """
        stopwords = {
            "de", "la", "que", "el", "en", "y", "a", "los", "del", "se", "las",
            "por", "un", "para", "con", "no", "una", "su", "al", "lo", "como",
            "más", "pero", "sus", "este", "es", "son", "esta", "esto",
        }
        words = re.findall(r"\b[a-záéíóúñ]{4,}\b", chunk.lower())
        freq: Dict[str, int] = {}
        for w in words:
            if w not in stopwords:
                freq[w] = freq.get(w, 0) + 1
        if not freq:
            return None
        top_word = max(freq, key=lambda k: freq[k])
        return top_word[:100]

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS DE BÚSQUEDA
    # ──────────────────────────────────────────────────────────────────────────

    def _build_tsquery(self, query: str) -> str:
        """
        Convierte una query de texto en una tsquery de PostgreSQL.
        Ej: "cómo configurar Docker" -> "configurar & docker"
        """
        stopwords = {
            "de", "la", "que", "el", "en", "y", "a", "los", "del", "se", "las",
            "por", "un", "para", "con", "no", "una", "su", "al", "lo", "como",
            "cómo", "qué", "cuál", "cuáles", "dónde", "cuándo", "por", "más",
        }
        # Normalizar: minúsculas, quitar acentos básicos
        text = query.lower()
        for accented, plain in [("á","a"),("é","e"),("í","i"),("ó","o"),("ú","u"),("ñ","n")]:
            text = text.replace(accented, plain)

        # Extraer palabras alfanuméricas de 3+ chars
        words = re.findall(r"\b[a-z0-9]{3,}\b", text)
        keywords = [w for w in words if w not in stopwords]

        if not keywords:
            return ""

        # Limitar a 8 keywords para no saturar la query
        keywords = keywords[:8]
        return " & ".join(keywords)

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS INTERNOS
    # ──────────────────────────────────────────────────────────────────────────

    def _mark_file_error(self, file_id: str, error_msg: str) -> None:
        try:
            self.supabase.table("agent_files").update({
                "status": "error",
                "error_message": error_msg[:500],
            }).eq("id", file_id).execute()
        except Exception as e:
            logger.error(f"No se pudo marcar el archivo {file_id} como error: {e}")

    def _require_supabase(self):
        if not self.supabase:
            raise ValueError("El servicio RAG no está disponible. Supabase no configurado.")


# Singleton global
platform_rag_service = PlatformRAGService()
