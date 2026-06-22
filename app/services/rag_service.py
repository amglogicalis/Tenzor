import os
import re
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

class RAGChunk:
    def __init__(self, source_file: str, heading: str, content: str, is_default_heading: bool = False):
        self.source_file = source_file
        self.heading = heading
        self.content = content
        self.is_default_heading = is_default_heading

    def __repr__(self):
        return f"RAGChunk(file={os.path.basename(self.source_file)}, heading={self.heading}, default={self.is_default_heading})"

class RAGService:
    def __init__(self, docs_dir: str = "docs_traning"):
        self.docs_dir = docs_dir
        self.chunks: List[RAGChunk] = []
        self.stop_words = {
            "de", "la", "que", "el", "en", "y", "a", "los", "del", "se", "las", 
            "por", "un", "para", "con", "no", "una", "su", "al", "lo", "como", 
            "más", "pero", "sus", "este", "o", "tu", "te", "me", "es", "son", 
            "esta", "esto", "estos", "estas", "un", "una", "unos", "unas"
        }
        self.load_documents()

    def clean_text(self, text: str) -> str:
        """Normaliza el texto a minúsculas y elimina caracteres especiales."""
        text = text.lower()
        # Reemplazar acentos comunes para evitar fallos de coincidencia
        replacements = {
            "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
            "ü": "u", "ñ": "n"
        }
        for orig, rep in replacements.items():
            text = text.replace(orig, rep)
        # Eliminar puntuación
        text = re.sub(r'[^\w\s]', ' ', text)
        return text

    def load_documents(self):
        """Busca y carga dinámicamente todos los archivos .md en la carpeta configurada."""
        self.chunks.clear()
        
        # Asegurar que el directorio existe
        os.makedirs(self.docs_dir, exist_ok=True)

        # Buscar archivos locales .md
        md_files = []
        for root, _, files in os.walk(self.docs_dir):
            for file in files:
                if file.endswith(".md"):
                    md_files.append(os.path.join(root, file))

        # Si no hay archivos locales, intentar descargar de GCS
        if not md_files:
            try:
                self._download_docs_from_gcs()
                # Re-escanear después de la descarga
                for root, _, files in os.walk(self.docs_dir):
                    for file in files:
                        if file.endswith(".md"):
                            md_files.append(os.path.join(root, file))
            except Exception as download_err:
                logger.error(f"Error descargando documentación de GCS: {download_err}")

        if not md_files:
            logger.warning(f"La carpeta de documentación RAG '{self.docs_dir}' está vacía y no se pudo descargar de GCS.")
            return

        logger.info(f"Escaneando directorio RAG '{self.docs_dir}'...")
        for file_path in md_files:
            try:
                self.parse_markdown_file(file_path)
            except Exception as e:
                logger.error(f"Error parseando el archivo RAG {file_path}: {e}")

        logger.info(f"RAG inicializado correctamente con {len(self.chunks)} secciones cargadas en memoria.")

    def _download_docs_from_gcs(self):
        """Descarga la documentación de GCS si no existe localmente (por ejemplo, en Render)."""
        logger.info("Documentación local no encontrada. Intentando descargar desde Google Cloud Storage (GCS)...")
        
        # 1. Obtener credenciales GCP
        creds = None
        google_creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        info = None
        if google_creds_json:
            try:
                import json
                from google.oauth2 import service_account
                info = json.loads(google_creds_json)
                creds = service_account.Credentials.from_service_account_info(
                    info,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                logger.info("Credenciales GCS cargadas desde GOOGLE_CREDENTIALS_JSON.")
            except Exception as e:
                logger.error(f"Error cargando GOOGLE_CREDENTIALS_JSON para GCS: {e}")
        
        if not creds:
            # Intentar buscar service_account.json local (útil en dev si se borra docs_traning)
            sa_paths = [
                "service_account.json",
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "service_account.json")
            ]
            for sa_path in sa_paths:
                if os.path.exists(sa_path):
                    try:
                        from google.oauth2 import service_account
                        creds = service_account.Credentials.from_service_account_file(
                            sa_path,
                            scopes=["https://www.googleapis.com/auth/cloud-platform"]
                        )
                        logger.info(f"Credenciales GCS cargadas desde archivo local {sa_path}.")
                        break
                    except Exception as e:
                        logger.error(f"Error cargando credentials de GCS desde {sa_path}: {e}")

        # 2. Conectar y descargar blobs
        try:
            from google.cloud import storage
            if creds:
                client = storage.Client(credentials=creds, project=info.get("project_id") if info else None)
            else:
                client = storage.Client()
                
            bucket_name = os.getenv("RAG_BUCKET_NAME", "tenzorai-tuning")
            prefix = "docs_traning/"
            bucket = client.bucket(bucket_name)
            
            logger.info(f"Listando blobs en gs://{bucket_name}/{prefix}...")
            blobs = list(client.list_blobs(bucket, prefix=prefix))
            
            if not blobs:
                logger.warning(f"No se encontraron archivos RAG en gs://{bucket_name}/{prefix}.")
                return
                
            download_count = 0
            for blob in blobs:
                if blob.name.endswith("/"):
                    continue
                
                # Obtener la ruta del archivo relativo dentro de docs_traning
                if blob.name.startswith(prefix):
                    rel_path = blob.name[len(prefix):]
                else:
                    rel_path = blob.name
                
                # Reemplazar barras para que sea multiplataforma
                rel_path = rel_path.replace("/", os.sep)
                local_file_path = os.path.join(self.docs_dir, rel_path)
                
                # Asegurar que existe el subdirectorio local
                os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                
                logger.info(f"Descargando {blob.name} en {local_file_path}...")
                blob.download_to_filename(local_file_path)
                download_count += 1
                
            logger.info(f"Descarga de documentación finalizada con éxito. Total descargados: {download_count} archivos.")
        except Exception as e:
            logger.error(f"Excepción descargando documentación de GCS: {e}")

    def parse_markdown_file(self, file_path: str):
        """Divide un archivo Markdown en chunks pequeños (máx 1800 caracteres) con solapamiento."""
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Primero, intentar dividir por encabezados de Markdown (# o ## o ###)
        pattern = re.compile(r'(?:^|\n)(#{1,3})\s+(.+?)(?=\n#{1,3}\s+|$)', re.DOTALL)
        matches = list(pattern.finditer(content))
        
        blocks = []
        
        if not matches:
            # Si no hay encabezados, el bloque es todo el archivo y se marca como default heading
            title = os.path.splitext(os.path.basename(file_path))[0]
            blocks.append((title, content.strip(), True))
        else:
            for i, match in enumerate(matches):
                heading = match.group(2).strip()
                start_pos = match.end()
                end_pos = matches[i+1].start() if i + 1 < len(matches) else len(content)
                section_content = content[start_pos:end_pos].strip()
                if section_content:
                    blocks.append((heading, section_content, False))

        # Procesar cada bloque para subdividirlo si es muy grande (> 1800 caracteres)
        max_chunk_size = 1800
        overlap = 300
        
        for heading, text, is_default in blocks:
            if len(text) <= max_chunk_size:
                self.chunks.append(RAGChunk(file_path, heading, text, is_default))
            else:
                # Cortar con solapamiento
                start = 0
                part = 1
                while start < len(text):
                    end = start + max_chunk_size
                    chunk_text = text[start:end].strip()
                    if chunk_text:
                        self.chunks.append(RAGChunk(
                            source_file=file_path,
                            heading=f"{heading} (Parte {part})",
                            content=chunk_text,
                            is_default_heading=is_default
                        ))
                    start += (max_chunk_size - overlap)
                    part += 1

    def search(self, query: str, threshold: float = 0.25, max_results: int = 3) -> Optional[List[RAGChunk]]:
        """
        Busca las secciones más relevantes que coincidan con la consulta.
        Retorna None si no hay resultados relevantes por encima del umbral.
        """
        query_cleaned = self.clean_text(query)
        query_words = query_cleaned.split()
        
        # Umbral de disparo: La consulta debe contener al menos uno de estos términos clave de infraestructura privada
        trigger_keywords = {
            "cap", "poseidon", "grito", "disaster", "recovery", "dr", 
            "aap", "aaponaws", "controller", "hub", "gateway", "eda",
            "mapfre", "avm", "maptech", "subnets", "subnet", "failover", "switchover"
        }
        
        has_trigger = any(word in trigger_keywords for word in query_words)
        if not has_trigger:
            return None

        # Filtrar palabras vacías para la puntuación
        query_words_filtered = [w for w in query_words if w not in self.stop_words and len(w) > 1]
        if not query_words_filtered:
            return None

        scored_chunks: List[Tuple[float, RAGChunk]] = []

        for chunk in self.chunks:
            heading_cleaned = self.clean_text(chunk.heading)
            content_cleaned = self.clean_text(chunk.content)
            
            heading_words = heading_cleaned.split()
            content_words = content_cleaned.split()

            # Calcular coincidencia de términos
            matches_in_heading = sum(1 for w in query_words_filtered if w in heading_words)
            matches_in_content = sum(1 for w in query_words_filtered if w in content_words)

            # Calcular puntuación ponderada
            # Coincidir palabras en el título tiene 3x peso, pero solo si es un título real del documento
            heading_multiplier = 0.2 if chunk.is_default_heading else 3.0
            heading_score = (matches_in_heading / len(query_words_filtered)) * heading_multiplier
            content_score = (matches_in_content / len(query_words_filtered)) * 1.0
            
            score = heading_score + content_score

            # Dar bonus si la frase de búsqueda simplificada aparece literal en el contenido
            simplified_query = " ".join(query_words_filtered)
            if len(simplified_query) > 3 and (simplified_query in content_cleaned or simplified_query in heading_cleaned):
                score += 1.5

            if score > 0:
                scored_chunks.append((score, chunk))

        if not scored_chunks:
            return None

        # Ordenar por puntuación descendente
        scored_chunks.sort(key=lambda x: x[0], reverse=True)

        # Filtrar por umbral de relevancia
        filtered = [chunk for score, chunk in scored_chunks if score >= threshold]
        
        if not filtered:
            return None

        # Retornar los N mejores resultados
        return filtered[:max_results]
