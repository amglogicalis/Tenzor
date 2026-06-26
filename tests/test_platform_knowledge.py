"""
test_platform_knowledge.py
Tests de la Fase 4: RAG por agente — chunking, extracción de texto, indexación,
búsqueda, gestión de archivos y endpoints.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from io import BytesIO

from app.main import app
from app.services.platform_rag_service import PlatformRAGService, KnowledgeChunk

client = TestClient(app)

USER_ID = "user-test-123"
AGENT_ID = "agent-test-456"
FILE_ID = "file-test-789"
VALID_TOKEN = "Bearer valid-platform-token"

# ─── Fixtures ─────────────────────────────────────────────────────────────────

def make_auth_mock():
    mock = MagicMock()
    mock.auth.get_user.return_value = MagicMock(
        user=MagicMock(id=USER_ID, email="test@example.com")
    )
    return mock

def make_agent_mock(owner_id=USER_ID):
    """Mock de Supabase para agent_service.get_agent."""
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = MagicMock(
        data=[{"id": AGENT_ID, "user_id": owner_id, "is_public": False,
               "current_version_id": None}]
    )
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=None)
    return sb

SAMPLE_MD = b"""# Guia de Python

## Variables y Tipos

En Python, las variables se definen sin declarar su tipo.
Python es un lenguaje de tipado dinamico, lo que significa que el tipo
se infiere en tiempo de ejecucion.

```python
nombre = "Tenzor"
version = 3.11
activo = True
```

## Funciones

Las funciones se definen con la palabra clave `def`.
Pueden recibir parametros y devolver valores.

```python
def saludar(nombre: str) -> str:
    return f"Hola, {nombre}!"
```

## Clases

Python soporta programacion orientada a objetos.
Las clases encapsulan datos y comportamiento.

```python
class Agente:
    def __init__(self, nombre: str):
        self.nombre = nombre
    
    def responder(self, pregunta: str) -> str:
        return f"Agente {self.nombre}: respondiendo a '{pregunta}'"
```
"""

SAMPLE_TXT = b"""
FastAPI es un framework moderno de Python para construir APIs.
Es muy rapido y facil de usar. Tiene soporte para OpenAPI automatico.
Se puede usar con bases de datos, autenticacion y mucho mas.
Soporta async/await de forma nativa para alta concurrencia.
"""

# ─── Tests del servicio RAG (sin Supabase) ────────────────────────────────────

class TestChunking:
    """Tests del motor de chunking — sin dependencias externas."""

    def setup_method(self):
        self.svc = PlatformRAGService.__new__(PlatformRAGService)
        self.svc.supabase = None  # sin conexión real

    def test_chunk_short_text_single_chunk(self):
        text = "Este es un texto corto que deberia caber en un solo chunk."
        chunks = self.svc._chunk_text(text, chunk_size=600, overlap=120)
        assert len(chunks) == 1
        assert "texto corto" in chunks[0]

    def test_chunk_long_text_multiple_chunks(self):
        text = ("Lorem ipsum dolor sit amet. " * 100)
        chunks = self.svc._chunk_text(text, chunk_size=200, overlap=40)
        assert len(chunks) > 1

    def test_chunks_have_overlap(self):
        """Verifica que los chunks consecutivos comparten contenido (solapamiento)."""
        # Texto largo con palabras únicas marcadas
        text = " ".join([f"palabra{i}" for i in range(200)])
        chunks = self.svc._chunk_text(text, chunk_size=300, overlap=100)
        assert len(chunks) >= 2
        # El final del primer chunk debe solaparse con el inicio del segundo
        last_words_c1 = set(chunks[0].split()[-10:])
        first_words_c2 = set(chunks[1].split()[:10])
        overlap_words = last_words_c1 & first_words_c2
        assert len(overlap_words) > 0, "No se detectó solapamiento entre chunks"

    def test_chunk_filters_short_fragments(self):
        """Chunks con menos de 50 chars deben ser filtrados."""
        text = "# Título\n\nContenido largo aquí " * 30
        chunks = self.svc._chunk_text(text, chunk_size=400, overlap=80)
        for chunk in chunks:
            assert len(chunk.strip()) >= 50

    def test_chunk_markdown_by_headings(self):
        """El chunker debe dividir preferentemente por encabezados MD."""
        md = SAMPLE_MD.decode()
        chunks = self.svc._chunk_text(md, chunk_size=600, overlap=100)
        assert len(chunks) >= 2
        # Al menos un chunk debe contener un bloque de código
        code_chunks = [c for c in chunks if "```python" in c]
        assert len(code_chunks) >= 1

    def test_chunk_empty_text_returns_empty(self):
        chunks = self.svc._chunk_text("", chunk_size=600, overlap=100)
        assert chunks == []

    def test_chunk_only_whitespace_returns_empty(self):
        chunks = self.svc._chunk_text("   \n\n\n   ", chunk_size=600, overlap=100)
        assert chunks == []


class TestTextExtraction:
    """Tests de extracción de texto — sin Supabase."""

    def setup_method(self):
        self.svc = PlatformRAGService.__new__(PlatformRAGService)
        self.svc.supabase = None

    def test_extract_txt(self):
        text = self.svc._extract_text(SAMPLE_TXT, "text/plain", "test.txt")
        assert "FastAPI" in text
        assert "Python" in text

    def test_extract_md(self):
        text = self.svc._extract_text(SAMPLE_MD, "text/markdown", "test.md")
        assert "Variables" in text
        assert "Funciones" in text

    def test_extract_utf8_encoding(self):
        content = "Éste es un texto con acentos: á, é, í, ó, ú, ñ".encode("utf-8")
        text = self.svc._extract_text(content, "text/plain", "test.txt")
        assert "acentos" in text

    def test_extract_latin1_encoding(self):
        content = "Texto en latin-1: café".encode("latin-1")
        text = self.svc._extract_text(content, "text/plain", "test.txt")
        assert "Texto" in text


class TestHeadingAndConcept:
    """Tests de extracción de metadata de chunks."""

    def setup_method(self):
        self.svc = PlatformRAGService.__new__(PlatformRAGService)

    def test_extract_md_heading(self):
        chunk = "## Configuración de FastAPI\nContenido del chunk aquí."
        heading = self.svc._extract_heading(chunk)
        assert heading == "Configuración de FastAPI"

    def test_extract_first_line_as_heading(self):
        chunk = "Introducción a Docker\nContenido largo del chunk."
        heading = self.svc._extract_heading(chunk)
        assert "Docker" in heading

    def test_no_heading_for_long_first_line(self):
        chunk = "Esta primera línea es demasiado larga para ser un encabezado válido y tiene más de 80 caracteres.\nContenido."
        heading = self.svc._extract_heading(chunk)
        assert heading is None

    def test_concept_extraction(self):
        chunk = "FastAPI FastAPI FastAPI es un framework para APIs modernas en Python."
        concept = self.svc._extract_concept(chunk)
        assert concept in ("fastapi", "framework", "python", "apis")

    def test_concept_none_for_empty(self):
        concept = self.svc._extract_concept("")
        assert concept is None


class TestTsQueryBuilder:
    """Tests del constructor de tsquery."""

    def setup_method(self):
        self.svc = PlatformRAGService.__new__(PlatformRAGService)

    def test_basic_query(self):
        result = self.svc._build_tsquery("cómo configurar Docker")
        assert "configurar" in result
        assert "docker" in result
        assert "&" in result

    def test_removes_stopwords(self):
        result = self.svc._build_tsquery("cómo se usa la API en Python")
        assert "como" not in result
        assert "python" in result
        assert "api" in result

    def test_empty_query_returns_empty(self):
        result = self.svc._build_tsquery("")
        assert result == ""

    def test_only_stopwords_returns_empty(self):
        result = self.svc._build_tsquery("de la y el")
        assert result == ""

    def test_max_8_keywords(self):
        result = self.svc._build_tsquery("uno dos tres cuatro cinco seis siete ocho nueve diez")
        keywords = result.split(" & ")
        assert len(keywords) <= 8


# ─── Tests de ingesta completa (Supabase mockeado) ────────────────────────────

class TestIngestFile:
    def _build_rag_mock(self, file_id=FILE_ID):
        sb = MagicMock()

        def table_side(table_name):
            t = MagicMock()
            if table_name == "agent_files":
                t.insert.return_value.execute.return_value = MagicMock(
                    data=[{"id": file_id, "agent_id": AGENT_ID,
                           "user_id": USER_ID, "status": "processing"}]
                )
                t.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
                t.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
                    data=[{"id": file_id}]
                )
                t.delete.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
            elif table_name == "agent_knowledge":
                t.insert.return_value.execute.return_value = MagicMock(data=[])
            return t

        sb.table.side_effect = table_side
        return sb

    def test_ingest_txt_success(self):
        sb = self._build_rag_mock()
        svc = PlatformRAGService.__new__(PlatformRAGService)
        svc.supabase = sb
        result = svc.ingest_file(
            agent_id=AGENT_ID,
            user_id=USER_ID,
            filename="test.txt",
            content_type="text/plain",
            raw_bytes=SAMPLE_TXT,
        )
        assert result["file_id"] == FILE_ID
        assert result["chunks_created"] >= 1
        assert result["status"] == "ready"

    def test_ingest_md_success(self):
        sb = self._build_rag_mock()
        svc = PlatformRAGService.__new__(PlatformRAGService)
        svc.supabase = sb
        result = svc.ingest_file(
            agent_id=AGENT_ID,
            user_id=USER_ID,
            filename="guia.md",
            content_type="text/markdown",
            raw_bytes=SAMPLE_MD,
        )
        assert result["chunks_created"] >= 2

    def test_ingest_oversized_file_raises(self):
        sb = self._build_rag_mock()
        svc = PlatformRAGService.__new__(PlatformRAGService)
        svc.supabase = sb
        big_file = b"x" * (11 * 1024 * 1024)  # 11 MB
        with pytest.raises(ValueError, match="límite"):
            svc.ingest_file(
                agent_id=AGENT_ID, user_id=USER_ID,
                filename="big.txt", content_type="text/plain",
                raw_bytes=big_file,
            )

    def test_ingest_unsupported_type_raises(self):
        sb = self._build_rag_mock()
        svc = PlatformRAGService.__new__(PlatformRAGService)
        svc.supabase = sb
        with pytest.raises(ValueError, match="soportado"):
            svc.ingest_file(
                agent_id=AGENT_ID, user_id=USER_ID,
                filename="test.xlsx",
                content_type="application/vnd.ms-excel",
                raw_bytes=b"datos",
            )

    def test_ingest_empty_file_raises(self):
        sb = self._build_rag_mock()
        svc = PlatformRAGService.__new__(PlatformRAGService)
        svc.supabase = sb
        # El mock retorna el file record, pero el texto estará vacío
        with pytest.raises(ValueError):
            svc.ingest_file(
                agent_id=AGENT_ID, user_id=USER_ID,
                filename="empty.txt", content_type="text/plain",
                raw_bytes=b"   ",
            )


# ─── Tests de búsqueda (Supabase mockeado) ────────────────────────────────────

class TestSearch:
    def _build_search_mock(self, chunks_data=None):
        sb = MagicMock()
        data = chunks_data or [
            {
                "id": "chunk-1", "agent_id": AGENT_ID, "file_id": FILE_ID,
                "chunk_index": 0, "heading": "FastAPI", "concept_node": "fastapi",
                "content": "FastAPI es un framework moderno para construir APIs en Python.",
                "metadata": {"filename": "guia.md"}, "created_at": "2026-06-26T10:00:00Z",
                "rank": 0.8,
            }
        ]
        sb.rpc.return_value.execute.return_value = MagicMock(data=data)
        return sb

    def test_search_returns_chunks(self):
        sb = self._build_search_mock()
        svc = PlatformRAGService.__new__(PlatformRAGService)
        svc.supabase = sb
        results = svc.search(agent_id=AGENT_ID, query="configurar FastAPI Python")
        assert len(results) == 1
        assert isinstance(results[0], KnowledgeChunk)
        assert results[0].rank == 0.8

    def test_search_empty_query_returns_empty(self):
        svc = PlatformRAGService.__new__(PlatformRAGService)
        svc.supabase = MagicMock()
        results = svc.search(agent_id=AGENT_ID, query="")
        assert results == []

    def test_search_only_stopwords_returns_empty(self):
        svc = PlatformRAGService.__new__(PlatformRAGService)
        svc.supabase = MagicMock()
        results = svc.search(agent_id=AGENT_ID, query="de la y el")
        assert results == []

    def test_search_fallback_on_rpc_error(self):
        """Si la RPC falla, el fallback ILIKE debe devolver resultados."""
        sb = MagicMock()
        sb.rpc.return_value.execute.side_effect = Exception("RPC not found")
        sb.table.return_value.select.return_value.eq.return_value.ilike.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{
                "id": "chunk-fb", "agent_id": AGENT_ID, "file_id": FILE_ID,
                "chunk_index": 0, "heading": None, "concept_node": None,
                "content": "FastAPI content here for fallback search.",
                "metadata": {},
            }]
        )
        svc = PlatformRAGService.__new__(PlatformRAGService)
        svc.supabase = sb
        results = svc.search(agent_id=AGENT_ID, query="FastAPI framework")
        assert len(results) >= 1

    def test_knowledge_chunk_to_context_string(self):
        chunk = KnowledgeChunk(
            chunk_id="c1", agent_id=AGENT_ID, file_id=FILE_ID,
            chunk_index=0, heading="Intro", concept_node="python",
            content="Python es genial.", metadata={}, rank=0.9,
        )
        ctx = chunk.to_context_string()
        assert "[Intro]" in ctx
        assert "(python)" in ctx
        assert "Python es genial." in ctx


# ─── Tests de endpoints ───────────────────────────────────────────────────────

class TestKnowledgeEndpoints:

    def _patch_all(self, rag_mock, agent_mock):
        return (
            patch("app.services.platform_auth_service.platform_auth_service.supabase", make_auth_mock()),
            patch("app.services.agent_service.agent_service.supabase", agent_mock),
            patch("app.services.platform_rag_service.platform_rag_service.supabase", rag_mock),
        )

    def test_upload_requires_auth(self):
        resp = client.post(
            f"/platform/knowledge/{AGENT_ID}/upload",
            files={"file": ("test.txt", b"contenido", "text/plain")},
        )
        assert resp.status_code == 401

    def test_list_files_requires_auth(self):
        resp = client.get(f"/platform/knowledge/{AGENT_ID}/files")
        assert resp.status_code == 401

    def test_upload_success(self):
        rag_sb = MagicMock()
        rag_sb.table.return_value.insert.return_value.execute.return_value = MagicMock(
            data=[{"id": FILE_ID, "agent_id": AGENT_ID, "user_id": USER_ID, "status": "processing"}]
        )
        rag_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

        agent_sb = make_agent_mock()

        with patch("app.services.platform_auth_service.platform_auth_service.supabase", make_auth_mock()), \
             patch("app.services.agent_service.agent_service.supabase", agent_sb), \
             patch("app.services.platform_rag_service.platform_rag_service.ingest_file",
                   return_value={"file_id": FILE_ID, "chunks_created": 3, "filename": "guia.txt",
                                 "file_size_bytes": len(SAMPLE_TXT), "status": "ready"}):
            resp = client.post(
                f"/platform/knowledge/{AGENT_ID}/upload",
                files={"file": ("guia.txt", SAMPLE_TXT, "text/plain")},
                headers={"Authorization": VALID_TOKEN},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["chunks_created"] == 3
        assert data["status"] == "ready"

    def test_list_files_success(self):
        agent_sb = make_agent_mock()
        mock_files = [
            {"id": FILE_ID, "filename": "guia.md", "content_type": "text/markdown",
             "file_size_bytes": 1024, "status": "ready", "error_message": None,
             "created_at": "2026-06-26T10:00:00Z"}
        ]
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", make_auth_mock()), \
             patch("app.services.agent_service.agent_service.supabase", agent_sb), \
             patch("app.services.platform_rag_service.platform_rag_service.list_files",
                   return_value=mock_files):
            resp = client.get(
                f"/platform/knowledge/{AGENT_ID}/files",
                headers={"Authorization": VALID_TOKEN},
            )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_delete_file_success(self):
        agent_sb = make_agent_mock()
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", make_auth_mock()), \
             patch("app.services.agent_service.agent_service.supabase", agent_sb), \
             patch("app.services.platform_rag_service.platform_rag_service.delete_file",
                   return_value=None):
            resp = client.delete(
                f"/platform/knowledge/{AGENT_ID}/files/{FILE_ID}",
                headers={"Authorization": VALID_TOKEN},
            )
        assert resp.status_code == 204

    def test_stats_endpoint(self):
        agent_sb = make_agent_mock()
        mock_stats = {"total_files": 2, "ready_files": 2, "processing_files": 0,
                      "error_files": 0, "total_chunks": 47}
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", make_auth_mock()), \
             patch("app.services.agent_service.agent_service.supabase", agent_sb), \
             patch("app.services.platform_rag_service.platform_rag_service.get_agent_knowledge_stats",
                   return_value=mock_stats):
            resp = client.get(
                f"/platform/knowledge/{AGENT_ID}/stats",
                headers={"Authorization": VALID_TOKEN},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_chunks"] == 47
        assert data["ready_files"] == 2
