"""
test_platform_chat.py
Tests de la Fase 6: Chat con agentes personalizados.

Estrategia de mocking:
  - PlatformChatService._sb → None (modo sin DB).
  - PlatformRAGService.search → mockeado para controlar qué chunks devuelve.
  - provider_router.infer    → mockeado para no hacer llamadas HTTP reales.
  - _load_agent              → mockeado para devolver agentes de prueba.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from fastapi.testclient import TestClient

from app.main import app
from app.services.platform_chat_service import (
    PlatformChatService, ChatSession, ChatResponse
)
from app.services.provider_router_service import InferenceResult, InferenceError, ProviderAttempt
from app.services.platform_rag_service import KnowledgeChunk


# ─── Fixtures ─────────────────────────────────────────────────────────────────

client = TestClient(app)

FAKE_TOKEN = "fake-platform-token"

AGENT_PUBLIC = {
    "id": "agent-pub-1",
    "user_id": "other-user",
    "name": "Agente Público",
    "description": "Test",
    "category": "dev",
    "base_tier": "balanced",
    "is_public": True,
    "deleted_at": None,
    "current_version_id": "ver-1",
    "system_instructions": "Eres un asistente de prueba.",
    "current_version": {
        "id": "ver-1",
        "agent_id": "agent-pub-1",
        "version": 1,
        "system_instructions": "Instrucciones compiladas del agente de prueba.",
        "retrieval_profile": {
            "trigger_keywords": ["api", "error", "deploy"],
            "always_retrieve": False,
            "top_k": 3,
            "context_injection": "prefix",
            "relevance_threshold": 0.6,
        },
    },
}

AGENT_NO_RAG = {
    "id": "agent-no-rag",
    "user_id": "user-owner",
    "name": "Agente Sin RAG",
    "category": "dev",
    "base_tier": "fast",
    "is_public": False,
    "deleted_at": None,
    "current_version_id": "ver-2",
    "current_version": {
        "id": "ver-2",
        "agent_id": "agent-no-rag",
        "version": 1,
        "system_instructions": "Sistema sin RAG.",
        "retrieval_profile": None,
    },
}

FAKE_INFERENCE_RESULT = InferenceResult(
    content="Esta es la respuesta del agente.",
    provider="groq",
    model="llama-3.1-8b-instant",
    key_id="sys-groq-1",
    tokens_in=50,
    tokens_out=100,
    latency_ms=320.5,
    finish_reason="stop",
)

FAKE_CHUNK = KnowledgeChunk(
    chunk_id="chunk-1",
    agent_id="agent-pub-1",
    file_id="file-1",
    chunk_index=0,
    heading="API Reference",
    concept_node="api",
    content="La API de Tenzor acepta peticiones POST en /v1/chat.",
    metadata={},
    rank=0.85,
)


def _make_auth_dep(user_id: str = "user-123"):
    """Sobreescribe la dependencia de auth para simular usuario autenticado."""
    return {"user_id": user_id, "username": "testuser"}


# ─── Tests de PlatformChatService (unitarios) ─────────────────────────────────

class TestShouldRetrieve:
    def _svc(self):
        svc = PlatformChatService.__new__(PlatformChatService)
        svc._sb = None
        svc._rag = MagicMock()
        return svc

    def test_no_profile_returns_false(self):
        svc = self._svc()
        assert svc._should_retrieve("hola", None) is False

    def test_always_retrieve_true(self):
        svc = self._svc()
        profile = {"always_retrieve": True, "trigger_keywords": []}
        assert svc._should_retrieve("hola", profile) is True

    def test_keyword_match_activates_rag(self):
        svc = self._svc()
        profile = {
            "always_retrieve": False,
            "trigger_keywords": ["api", "error", "deploy"],
        }
        assert svc._should_retrieve("tengo un error en la API", profile) is True

    def test_keyword_no_match(self):
        svc = self._svc()
        profile = {
            "always_retrieve": False,
            "trigger_keywords": ["kubernetes", "terraform"],
        }
        assert svc._should_retrieve("hola, ¿cómo estás?", profile) is False

    def test_keyword_match_case_insensitive(self):
        svc = self._svc()
        profile = {
            "always_retrieve": False,
            "trigger_keywords": ["API"],
        }
        assert svc._should_retrieve("problema con la api de producción", profile) is True

    def test_empty_keywords_no_match(self):
        svc = self._svc()
        profile = {"always_retrieve": False, "trigger_keywords": []}
        assert svc._should_retrieve("consulta técnica", profile) is False


class TestBuildRagBlock:
    def _svc(self):
        svc = PlatformChatService.__new__(PlatformChatService)
        svc._sb = None
        svc._rag = MagicMock()
        return svc

    def test_rag_block_contains_content(self):
        svc = self._svc()
        block = svc._build_rag_block([FAKE_CHUNK])
        assert "La API de Tenzor" in block
        assert "API Reference" in block

    def test_rag_block_has_multiple_chunks(self):
        svc = self._svc()
        chunk2 = KnowledgeChunk(
            chunk_id="c2", agent_id="a1", file_id="f1",
            chunk_index=1, heading="Errores", concept_node="error",
            content="El error 429 indica rate limiting.", metadata={}, rank=0.7,
        )
        block = svc._build_rag_block([FAKE_CHUNK, chunk2])
        assert "[1]" in block
        assert "[2]" in block
        assert "rate limiting" in block

    def test_chunk_without_heading(self):
        svc = self._svc()
        chunk = KnowledgeChunk(
            chunk_id="c3", agent_id="a1", file_id="f1",
            chunk_index=0, heading=None, concept_node=None,
            content="Contenido sin heading.", metadata={}, rank=0.5,
        )
        block = svc._build_rag_block([chunk])
        assert "Contenido sin heading." in block


class TestExtractSystemInstructions:
    def _svc(self):
        svc = PlatformChatService.__new__(PlatformChatService)
        svc._sb = None
        svc._rag = MagicMock()
        return svc

    def test_extracts_from_current_version(self):
        svc = self._svc()
        instructions = svc._extract_system_instructions(AGENT_PUBLIC)
        assert instructions == "Instrucciones compiladas del agente de prueba."

    def test_fallback_to_agent_field(self):
        svc = self._svc()
        agent = {"system_instructions": "Fallback instructions.", "current_version": None}
        assert svc._extract_system_instructions(agent) == "Fallback instructions."

    def test_fallback_default(self):
        svc = self._svc()
        agent = {"current_version": None}
        result = svc._extract_system_instructions(agent)
        assert "asistente" in result.lower()


class TestExtractRetrievalProfile:
    def _svc(self):
        svc = PlatformChatService.__new__(PlatformChatService)
        svc._sb = None
        svc._rag = MagicMock()
        return svc

    def test_extracts_dict_profile(self):
        svc = self._svc()
        rp = svc._extract_retrieval_profile(AGENT_PUBLIC)
        assert rp is not None
        assert rp["top_k"] == 3

    def test_extracts_json_string_profile(self):
        import json
        svc = self._svc()
        agent = {
            "current_version": {
                "retrieval_profile": json.dumps({"always_retrieve": True, "top_k": 5})
            }
        }
        rp = svc._extract_retrieval_profile(agent)
        assert rp["always_retrieve"] is True

    def test_none_profile_returns_none(self):
        svc = self._svc()
        assert svc._extract_retrieval_profile(AGENT_NO_RAG) is None

    def test_no_version_returns_none(self):
        svc = self._svc()
        agent = {"current_version": None}
        assert svc._extract_retrieval_profile(agent) is None


class TestBuildMessages:
    def _svc(self):
        svc = PlatformChatService.__new__(PlatformChatService)
        svc._sb = None
        svc._rag = MagicMock()
        return svc

    def test_empty_history_only_user_message(self):
        svc = self._svc()
        msgs = svc._build_messages(history=[], user_message="Hola")
        assert len(msgs) == 1
        assert msgs[0] == {"role": "user", "content": "Hola"}

    def test_history_prepended(self):
        svc = self._svc()
        history = [
            {"role": "user", "content": "Primer mensaje"},
            {"role": "assistant", "content": "Primera respuesta"},
        ]
        msgs = svc._build_messages(history=history, user_message="Segundo mensaje")
        assert len(msgs) == 3
        assert msgs[-1] == {"role": "user", "content": "Segundo mensaje"}

    def test_history_not_mutated(self):
        svc = self._svc()
        history = [{"role": "user", "content": "Test"}]
        original_len = len(history)
        svc._build_messages(history=history, user_message="Nuevo")
        assert len(history) == original_len  # history original no se modifica


class TestChatService:
    """Tests del flujo completo de chat (sin DB real)."""

    def _make_svc(self) -> PlatformChatService:
        svc = PlatformChatService.__new__(PlatformChatService)
        svc._sb = None  # Sin DB
        svc._rag = MagicMock()
        svc._rag.search.return_value = []
        # Cache mockeado: MISS por defecto (None = sin hit)
        svc._cache = MagicMock()
        svc._cache.get_cached_response.return_value = None
        svc._cache.store_response.return_value = True
        return svc

    def test_chat_no_rag_success(self):
        svc = self._make_svc()
        with patch.object(svc, "_load_agent", return_value=AGENT_NO_RAG), \
             patch.object(svc, "_get_or_create_session",
                          return_value=ChatSession("sess-1", "agent-no-rag", "user-1")), \
             patch.object(svc, "_load_history", return_value=[]), \
             patch.object(svc, "_save_message", return_value="msg-abc"), \
             patch.object(svc, "_touch_session"), \
             patch("app.services.platform_chat_service.provider_router.infer",
                   return_value=FAKE_INFERENCE_RESULT):
            resp = svc.chat(
                user_id="user-1",
                agent_id="agent-no-rag",
                user_message="¿Qué es Docker?",
            )
        assert resp.content == "Esta es la respuesta del agente."
        assert resp.provider == "groq"
        assert resp.rag_chunks_used == 0

    def test_chat_with_rag_keyword_match(self):
        svc = self._make_svc()
        svc._rag.search.return_value = [FAKE_CHUNK]

        with patch.object(svc, "_load_agent", return_value=AGENT_PUBLIC), \
             patch.object(svc, "_get_or_create_session",
                          return_value=ChatSession("sess-2", "agent-pub-1", "user-1")), \
             patch.object(svc, "_load_history", return_value=[]), \
             patch.object(svc, "_save_message", return_value="msg-xyz"), \
             patch.object(svc, "_touch_session"), \
             patch("app.services.platform_chat_service.provider_router.infer",
                   return_value=FAKE_INFERENCE_RESULT):
            resp = svc.chat(
                user_id="user-1",
                agent_id="agent-pub-1",
                user_message="Tengo un error en la API",
            )
        assert resp.rag_chunks_used == 1
        svc._rag.search.assert_called_once()

    def test_chat_no_rag_if_no_keyword_match(self):
        svc = self._make_svc()

        with patch.object(svc, "_load_agent", return_value=AGENT_PUBLIC), \
             patch.object(svc, "_get_or_create_session",
                          return_value=ChatSession("sess-3", "agent-pub-1", "user-1")), \
             patch.object(svc, "_load_history", return_value=[]), \
             patch.object(svc, "_save_message", return_value="msg-1"), \
             patch.object(svc, "_touch_session"), \
             patch("app.services.platform_chat_service.provider_router.infer",
                   return_value=FAKE_INFERENCE_RESULT):
            resp = svc.chat(
                user_id="user-1",
                agent_id="agent-pub-1",
                user_message="Hola, ¿cómo estás?",  # No contiene keywords
            )
        assert resp.rag_chunks_used == 0
        svc._rag.search.assert_not_called()

    def test_chat_inference_error_raises_value_error(self):
        svc = self._make_svc()

        with patch.object(svc, "_load_agent", return_value=AGENT_NO_RAG), \
             patch.object(svc, "_get_or_create_session",
                          return_value=ChatSession("sess-4", "agent-no-rag", "user-1")), \
             patch.object(svc, "_load_history", return_value=[]), \
             patch("app.services.platform_chat_service.provider_router.infer",
                   side_effect=InferenceError("all failed", attempts=[])):
            with pytest.raises(ValueError, match="providers están saturados"):
                svc.chat(
                    user_id="user-1",
                    agent_id="agent-no-rag",
                    user_message="Test",
                )

    def test_chat_with_conversation_history(self):
        svc = self._make_svc()
        history = [
            {"role": "user", "content": "Primer turno"},
            {"role": "assistant", "content": "Respuesta del primer turno"},
        ]

        captured_messages = {}
        def mock_infer(messages, **kwargs):
            captured_messages["msgs"] = messages
            return FAKE_INFERENCE_RESULT

        with patch.object(svc, "_load_agent", return_value=AGENT_NO_RAG), \
             patch.object(svc, "_get_or_create_session",
                          return_value=ChatSession("sess-5", "agent-no-rag", "user-1")), \
             patch.object(svc, "_load_history", return_value=history), \
             patch.object(svc, "_save_message", return_value="msg-1"), \
             patch.object(svc, "_touch_session"), \
             patch("app.services.platform_chat_service.provider_router.infer",
                   side_effect=mock_infer):
            svc.chat(user_id="user-1", agent_id="agent-no-rag", user_message="Segundo turno")

        msgs = captured_messages["msgs"]
        assert len(msgs) == 3
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[2]["content"] == "Segundo turno"

    def test_system_prompt_injected_as_kwarg(self):
        """Verifica que el system_prompt compilado se pasa al router."""
        svc = self._make_svc()
        captured = {}

        def mock_infer(messages, system_prompt=None, **kwargs):
            captured["system_prompt"] = system_prompt
            return FAKE_INFERENCE_RESULT

        with patch.object(svc, "_load_agent", return_value=AGENT_PUBLIC), \
             patch.object(svc, "_get_or_create_session",
                          return_value=ChatSession("sess-6", "agent-pub-1", "user-1")), \
             patch.object(svc, "_load_history", return_value=[]), \
             patch.object(svc, "_save_message", return_value="msg-1"), \
             patch.object(svc, "_touch_session"), \
             patch("app.services.platform_chat_service.provider_router.infer",
                   side_effect=mock_infer):
            svc.chat(user_id="user-1", agent_id="agent-pub-1", user_message="Hola")

        assert "Instrucciones compiladas" in captured["system_prompt"]


# ─── Tests de Endpoints HTTP ──────────────────────────────────────────────────

def _auth_override(user_id="user-123"):
    from app.middleware.platform_auth_middleware import require_platform_user
    app.dependency_overrides[require_platform_user] = lambda: {"user_id": user_id, "username": "test"}


def _clear_auth():
    from app.middleware.platform_auth_middleware import require_platform_user
    app.dependency_overrides.pop(require_platform_user, None)


class TestChatEndpoints:

    def setup_method(self):
        _auth_override()

    def teardown_method(self):
        _clear_auth()

    def test_send_message_requires_auth(self):
        _clear_auth()
        resp = client.post("/platform/chat/agent-1", json={"message": "Hola"})
        assert resp.status_code in (401, 403)

    def test_send_message_success(self):
        mock_response = ChatResponse(
            session_id="sess-new",
            message_id="msg-new",
            content="Respuesta del agente.",
            provider="groq",
            model="llama-3.1-8b",
            tokens_in=10,
            tokens_out=20,
            latency_ms=250.0,
            rag_chunks_used=0,
        )
        with patch(
            "app.routers.platform_chat._chat_service.chat",
            return_value=mock_response,
        ):
            resp = client.post(
                "/platform/chat/agent-pub-1",
                json={"message": "Hola, ¿qué puedes hacer?"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["content"] == "Respuesta del agente."
        assert data["session_id"] == "sess-new"
        assert data["provider"] == "groq"

    def test_send_message_with_session_id(self):
        mock_response = ChatResponse(
            session_id="existing-sess",
            message_id="msg-2",
            content="Continuación.",
            provider="groq",
            model="llama-3.1-8b",
            tokens_in=15,
            tokens_out=30,
            latency_ms=180.0,
        )
        with patch(
            "app.routers.platform_chat._chat_service.chat",
            return_value=mock_response,
        ) as mock_chat:
            resp = client.post(
                "/platform/chat/agent-pub-1",
                json={"message": "Continúa", "session_id": "existing-sess"},
            )
        assert resp.status_code == 200
        mock_chat.assert_called_once()
        call_kwargs = mock_chat.call_args.kwargs
        assert call_kwargs["session_id"] == "existing-sess"

    def test_send_message_agent_not_found(self):
        with patch(
            "app.routers.platform_chat._chat_service.chat",
            side_effect=ValueError("Agente no encontrado."),
        ):
            resp = client.post(
                "/platform/chat/nonexistent",
                json={"message": "Hola"},
            )
        assert resp.status_code == 404

    def test_send_message_providers_saturated(self):
        with patch(
            "app.routers.platform_chat._chat_service.chat",
            side_effect=ValueError("providers están saturados"),
        ):
            resp = client.post(
                "/platform/chat/agent-1",
                json={"message": "Hola"},
            )
        assert resp.status_code == 503

    def test_list_sessions_requires_auth(self):
        _clear_auth()
        resp = client.get("/platform/chat/sessions")
        assert resp.status_code in (401, 403)

    def test_list_sessions_success(self):
        mock_sessions = [
            {"id": "s1", "agent_id": "a1", "title": "Sesión 1",
             "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T01:00:00Z"},
        ]
        with patch(
            "app.routers.platform_chat._chat_service.list_sessions",
            return_value=mock_sessions,
        ):
            resp = client.get("/platform/chat/sessions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["sessions"][0]["id"] == "s1"

    def test_get_session_history_success(self):
        mock_history = [
            {"id": "m1", "role": "user", "content": "Hola", "metadata": {}, "created_at": "2025-01-01T00:00:00Z"},
            {"id": "m2", "role": "assistant", "content": "Hola!", "metadata": {}, "created_at": "2025-01-01T00:00:01Z"},
        ]
        with patch(
            "app.routers.platform_chat._chat_service.get_session_history",
            return_value=mock_history,
        ):
            resp = client.get("/platform/chat/sessions/sess-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2

    def test_get_session_history_not_found(self):
        with patch(
            "app.routers.platform_chat._chat_service.get_session_history",
            side_effect=ValueError("Sesión no encontrada o sin acceso."),
        ):
            resp = client.get("/platform/chat/sessions/bad-sess")
        assert resp.status_code == 404

    def test_delete_session_success(self):
        with patch(
            "app.routers.platform_chat._chat_service.delete_session",
            return_value=True,
        ):
            resp = client.delete("/platform/chat/sessions/sess-del")
        assert resp.status_code == 200
        assert "eliminada" in resp.json()["detail"]

    def test_delete_session_not_found(self):
        with patch(
            "app.routers.platform_chat._chat_service.delete_session",
            side_effect=ValueError("Sesión no encontrada o sin acceso."),
        ):
            resp = client.delete("/platform/chat/sessions/bad-sess")
        assert resp.status_code == 404

    def test_message_validation_empty(self):
        resp = client.post(
            "/platform/chat/agent-1",
            json={"message": ""},
        )
        assert resp.status_code == 422

    def test_temperature_validation(self):
        resp = client.post(
            "/platform/chat/agent-1",
            json={"message": "Test", "temperature": 5.0},
        )
        assert resp.status_code == 422

    def test_invalid_force_provider(self):
        resp = client.post(
            "/platform/chat/agent-1",
            json={"message": "Test", "force_provider": "anthropic"},
        )
        assert resp.status_code == 422
