import os
import re
import hashlib
import logging
import math
from typing import List, Dict, Any, Optional

from app import config
from app.db import supabase_admin

logger = logging.getLogger(__name__)

# Configuración del segmentador
DEFAULT_VAULT_CHUNK_SIZE = 1000
DEFAULT_VAULT_CHUNK_OVERLAP = 150

class AgentVaultService:
    """
    Servicio para gestionar las Bóvedas de Conocimiento de los Agentes (Second Brain RAG).
    Soporta formatos Markdown (.md), PDF y Texto Plano (.txt).
    Realiza chunking adaptativo, embeddings vectoriales e interconexiones semánticas (wikilinks).
    """

    def __init__(self):
        self.supabase = supabase_admin

    def _generate_synthetic_embedding(self, text: str) -> List[float]:
        """
        Genera un vector sintético determinista de 1536 dimensiones
        a partir del contenido del texto. Útil para tests locales y fallbacks sin API Keys.
        """
        # Calcular MD5 del texto
        h = hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()
        # Generar 1536 valores deterministas
        vector = []
        for i in range(1536):
            # Obtener una semilla a partir del hash rotado
            char_idx = i % len(h)
            val = ord(h[char_idx]) * (i + 1)
            vector.append(math.sin(val))
        
        # Normalizar el vector (distancia coseno espera vectores unitarios)
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector

    def get_embedding(self, text: str) -> List[float]:
        """
        Genera el embedding vectorial de 1536 dimensiones.
        Prioriza Gemini (si hay claves de API o en el config), de lo contrario OpenAI,
        y finalmente cae de forma segura en un vector sintético determinista.
        """
        # Intentar con Google Gemini primero (embedding-001)
        gemini_key = os.getenv("GEMINI_API_KEY") or config.GEMINI_API_KEY
        if gemini_key and gemini_key.strip().startswith("AIzaSy"):
            try:
                import google.generativeai as genai
                genai.configure(api_key=gemini_key)
                response = genai.embed_content(
                    model="models/embedding-001",
                    content=text,
                    task_type="retrieval_document"
                )
                embedding_768 = response.get("embedding", [])
                if len(embedding_768) == 768:
                    # Duplicar y normalizar a 1536
                    v_1536 = embedding_768 + embedding_768
                    norm = math.sqrt(sum(x*x for x in v_1536))
                    return [x / norm for x in v_1536] if norm > 0 else v_1536
            except Exception as e:
                logger.warning(f"Error al generar embedding con Gemini: {e}. Usando fallback.")

        # Intentar con OpenAI (text-embedding-3-small)
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=openai_key)
                response = client.embeddings.create(
                    input=[text],
                    model="text-embedding-3-small"
                )
                return response.data[0].embedding
            except Exception as e:
                logger.warning(f"Error al generar embedding con OpenAI: {e}. Usando fallback.")

        # Fallback sintético
        return self._generate_synthetic_embedding(text)

    def _split_markdown_chunks(self, text: str, chunk_size: int, overlap: int) -> List[Dict[str, Any]]:
        """
        Segmentación inteligente especializada para Markdown:
        Divide respetando los encabezados (#, ##, ###) y guardando el contexto del título.
        """
        lines = text.split("\n")
        chunks = []
        current_header = "General"
        current_chunk = []
        current_len = 0
        
        header_regex = re.compile(r"^(#{1,6})\s+(.+)$")
        
        for line in lines:
            m = header_regex.match(line)
            if m:
                # Si tenemos contenido acumulado, guardamos el chunk anterior antes de procesar el nuevo encabezado
                if current_chunk:
                    content_str = "\n".join(current_chunk)
                    chunks.append({
                        "heading": current_header,
                        "content": content_str
                    })
                    current_chunk = []
                    current_len = 0
                current_header = m.group(2).strip()
            
            current_chunk.append(line)
            current_len += len(line) + 1
            
            # Si supera el tamaño de chunk, guardamos y arrastramos solapamiento
            if current_len >= chunk_size:
                content_str = "\n".join(current_chunk)
                chunks.append({
                    "heading": current_header,
                    "content": content_str
                })
                # Mantener solapamiento de líneas finales
                overlap_lines = current_chunk[-3:] if len(current_chunk) > 3 else current_chunk[-1:]
                current_chunk = list(overlap_lines)
                current_len = sum(len(l) + 1 for l in current_chunk)
                
        if current_chunk:
            chunks.append({
                "heading": current_header,
                "content": "\n".join(current_chunk)
            })
            
        return chunks

    def _split_generic_chunks(self, text: str, chunk_size: int, overlap: int) -> List[Dict[str, Any]]:
        """
        Segmentador genérico por longitud y párrafos para PDFs y TXT.
        """
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = []
        current_len = 0
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            current_chunk.append(para)
            current_len += len(para) + 2
            
            if current_len >= chunk_size:
                chunks.append({
                    "heading": None,
                    "content": "\n\n".join(current_chunk)
                })
                current_chunk = [para]
                current_len = len(para)
                
        if current_chunk:
            chunks.append({
                "heading": None,
                "content": "\n\n".join(current_chunk)
            })
        return chunks

    def ingest_file(
        self,
        agent_id: str,
        filename: str,
        file_type: str,
        content: str,
        chunk_size: int = DEFAULT_VAULT_CHUNK_SIZE,
        overlap: int = DEFAULT_VAULT_CHUNK_OVERLAP
    ) -> Dict[str, Any]:
        """
        Ingesta un archivo en el Vault del agente:
        - Calcula hash.
        - Evita re-indexar si el contenido es idéntico.
        - Segmenta y calcula embeddings.
        - Registra wikilinks de interconexión.
        """
        if not self.supabase:
            raise RuntimeError("Supabase no está configurado.")

        # 1. Calcular hash MD5
        content_hash = hashlib.md5(content.encode("utf-8", errors="replace")).hexdigest()

        # 2. Comprobar si ya existe con el mismo hash
        existing = self.supabase.table("agent_vault_documents")\
            .select("id, content_hash")\
            .eq("agent_id", agent_id)\
            .eq("file_name", filename)\
            .execute()

        if existing.data and existing.data[0].get("content_hash") == content_hash:
            logger.info(f"El archivo {filename} ya está indexado y no ha cambiado.")
            return {"status": "skipped", "document_id": existing.data[0]["id"]}

        # Si ya existe pero el hash es diferente, eliminamos el anterior para re-indexar de forma limpia
        if existing.data:
            doc_id = existing.data[0]["id"]
            self.supabase.table("agent_vault_documents").delete().eq("id", doc_id).execute()

        # 3. Insertar registro de documento
        # Extraer tags simples de metadatos o por defecto
        tags = []
        if file_type == "md":
            # Intentar extraer tags simples del frontmatter o texto (#tag)
            tags_found = re.findall(r"#(\w+)", content)
            tags = list(set(tags_found))

        doc_record = self.supabase.table("agent_vault_documents").insert({
            "agent_id": agent_id,
            "file_name": filename,
            "content_hash": content_hash,
            "file_type": file_type,
            "tags": tags,
            "raw_content": content
        }).execute()

        if not doc_record.data:
            raise RuntimeError("Fallo al registrar el documento en la base de datos.")
        
        new_doc_id = doc_record.data[0]["id"]

        # 4. Dividir en chunks
        if file_type == "md":
            chunks = self._split_markdown_chunks(content, chunk_size, overlap)
        else:
            chunks = self._split_generic_chunks(content, chunk_size, overlap)

        # 5. Generar embeddings e insertar
        for idx, ch in enumerate(chunks):
            embedding_vector = self.get_embedding(ch["content"])
            self.supabase.table("agent_vault_embeddings").insert({
                "document_id": new_doc_id,
                "agent_id": agent_id,
                "chunk_index": idx,
                "chunk_content": ch["content"],
                "embedding": embedding_vector
            }).execute()

        # 6. Mapear interconexiones semánticas (Wikilinks)
        # Buscar patrones [[Nombre de Nota]]
        wikilinks = re.findall(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]", content)
        for link in set(wikilinks):
            link_name = link.strip()
            # Buscar si ese documento destino existe en el Vault del agente
            target_doc = self.supabase.table("agent_vault_documents")\
                .select("id")\
                .eq("agent_id", agent_id)\
                .eq("file_name", link_name if link_name.endswith((".md", ".pdf", ".txt")) else f"{link_name}.md")\
                .execute()
            
            if target_doc.data:
                # Registrar enlace bidireccional / directo
                self.supabase.table("agent_vault_relations").insert({
                    "agent_id": agent_id,
                    "source_doc_id": new_doc_id,
                    "target_doc_id": target_doc.data[0]["id"],
                    "relation_type": "link"
                }).execute()

        return {
            "status": "indexed",
            "document_id": new_doc_id,
            "chunks_count": len(chunks)
        }

    def search_vault(self, agent_id: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Búsqueda vectorial en el Vault del agente por distancia coseno.
        """
        if not self.supabase:
            return []

        query_vector = self.get_embedding(query)
        
        # Invocar la función RPC match_vault_embeddings de Postgres
        res = self.supabase.rpc("match_vault_embeddings", {
            "query_embedding": query_vector,
            "match_threshold": 0.3,
            "match_count": limit,
            "p_agent_id": agent_id
        }).execute()
        
        results = res.data or []
        
        # Si no hay resultados de embeddings, hacemos una búsqueda básica de fallback tipo LIKE sobre los documentos
        if not results:
            fallback = self.supabase.table("agent_vault_documents")\
                .select("id, file_name, raw_content")\
                .eq("agent_id", agent_id)\
                .ilike("raw_content", f"%{query}%")\
                .limit(2)\
                .execute()
            for doc in (fallback.data or []):
                results.append({
                    "document_id": doc["id"],
                    "chunk_content": doc["raw_content"][:500] + "...",
                    "similarity": 0.5
                })
        
        return results
