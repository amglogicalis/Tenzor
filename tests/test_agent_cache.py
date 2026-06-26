"""
test_agent_cache.py
Tests de la Fase 7: Cache, Feedback y Re-síntesis.

Sin hits a Supabase real — todo mockeado via unittest.mock.
"""
import pytest
from unittest.mock import MagicMock, patch, call

from app.services.agent_cache_service import (
    AgentCacheService,
    _normalize_query, _compute_hash, _is_cacheable,
    FEEDBACK_NEGATIVE_THRESHOLD,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def make_svc() -> AgentCacheService:
    """Servicio con _sb mockeado."""
    svc = AgentCacheService.__new__(AgentCacheService)
    svc._sb = MagicMock()
    return svc


def make_svc_no_db() -> AgentCacheService:
    """Servicio sin DB (None)."""
    svc = AgentCacheService.__new__(AgentCacheService)
    svc._sb = None
    return svc


# ─── Tests de utilidades ──────────────────────────────────────────────────────

class TestNormalizeQuery:
    def test_lowercase(self):
        assert _normalize_query("Hola MUNDO") == "hola mundo"

    def test_strip_whitespace(self):
        assert _normalize_query("  hola  mundo  ") == "hola mundo"

    def test_collapse_spaces(self):
        assert _normalize_query("hola   mundo") == "hola mundo"

    def test_empty_string(self):
        assert _normalize_query("") == ""


class TestComputeHash:
    def test_deterministic(self):
        h1 = _compute_hash("agent-1", "¿Qué es Docker?")
        h2 = _compute_hash("agent-1", "¿Qué es Docker?")
        assert h1 == h2

    def test_different_agents_different_hash(self):
        h1 = _compute_hash("agent-1", "Docker")
        h2 = _compute_hash("agent-2", "Docker")
        assert h1 != h2

    def test_different_queries_different_hash(self):
        h1 = _compute_hash("agent-1", "Docker")
        h2 = _compute_hash("agent-1", "Kubernetes")
        assert h1 != h2

    def test_case_insensitive(self):
        """Queries que difieren solo en mayúsculas → mismo hash."""
        h1 = _compute_hash("agent-1", "¿QUÉ ES DOCKER?")
        h2 = _compute_hash("agent-1", "¿qué es docker?")
        assert h1 == h2

    def test_hash_is_hex_string(self):
        h = _compute_hash("agent-1", "test")
        assert len(h) == 64
        int(h, 16)  # debe ser hexadecimal válido


class TestIsCacheable:
    def test_normal_query_cacheable(self):
        assert _is_cacheable("¿Cómo configuro un servidor nginx?") is True

    def test_too_short_not_cacheable(self):
        assert _is_cacheable("hola") is False

    def test_too_long_not_cacheable(self):
        assert _is_cacheable("x" * 2001) is False

    def test_exact_min_length_cacheable(self):
        assert _is_cacheable("a" * 10) is True

    def test_exact_max_length_cacheable(self):
        assert _is_cacheable("a" * 2000) is True

    def test_empty_not_cacheable(self):
        assert _is_cacheable("") is False


# ─── Tests de get_cached_response ─────────────────────────────────────────────

class TestGetCachedResponse:
    def test_no_db_returns_none(self):
        svc = make_svc_no_db()
        assert svc.get_cached_response("agent-1", "¿Qué es Docker?") is None

    def test_cache_miss_returns_none(self):
        svc = make_svc()
        svc._sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        result = svc.get_cached_response("agent-1", "¿Qué es Docker?")
        assert result is None

    def test_cache_hit_returns_response(self):
        svc = make_svc()
        mock_entry = {"id": "c1", "response": "Docker es una plataforma de contenedores.", "user_feedback": 0, "times_used": 3}
        # Configurar el mock en cadena
        (svc._sb.table.return_value
            .select.return_value
            .eq.return_value
            .eq.return_value
            .execute.return_value.data) = [mock_entry]
        result = svc.get_cached_response("agent-1", "¿Qué es Docker?")
        assert result == "Docker es una plataforma de contenedores."

    def test_very_negative_feedback_skips_cache(self):
        """Entradas con feedback ≤ -3 no se devuelven."""
        svc = make_svc()
        mock_entry = {"id": "c1", "response": "Respuesta mala.", "user_feedback": -3, "times_used": 1}
        (svc._sb.table.return_value
            .select.return_value
            .eq.return_value
            .eq.return_value
            .execute.return_value.data) = [mock_entry]
        result = svc.get_cached_response("agent-1", "¿Qué es Docker?")
        assert result is None

    def test_short_query_not_cached(self):
        svc = make_svc()
        result = svc.get_cached_response("agent-1", "hola")
        assert result is None
        svc._sb.table.assert_not_called()

    def test_cache_hit_increments_times_used(self):
        svc = make_svc()
        mock_entry = {"id": "c1", "response": "Respuesta.", "user_feedback": 0, "times_used": 2}
        (svc._sb.table.return_value
            .select.return_value
            .eq.return_value
            .eq.return_value
            .execute.return_value.data) = [mock_entry]
        # El update también debe ser mockeado
        (svc._sb.table.return_value
            .update.return_value
            .eq.return_value
            .execute.return_value) = MagicMock()

        svc.get_cached_response("agent-1", "¿Qué es Docker?")
        # Verificar que se llamó update
        svc._sb.table.return_value.update.assert_called()


# ─── Tests de store_response ──────────────────────────────────────────────────

class TestStoreResponse:
    def test_no_db_returns_false(self):
        svc = make_svc_no_db()
        assert svc.store_response("agent-1", "¿Qué es Docker?", "Respuesta.") is False

    def test_short_query_not_stored(self):
        svc = make_svc()
        result = svc.store_response("agent-1", "hola", "Respuesta.")
        assert result is False
        svc._sb.table.assert_not_called()

    def test_normal_query_stored(self):
        svc = make_svc()
        (svc._sb.table.return_value
            .upsert.return_value
            .execute.return_value) = MagicMock()
        result = svc.store_response("agent-1", "¿Cómo funciona Docker?", "Docker usa namespaces.")
        assert result is True
        svc._sb.table.return_value.upsert.assert_called_once()

    def test_upsert_includes_query_hash(self):
        svc = make_svc()
        (svc._sb.table.return_value
            .upsert.return_value
            .execute.return_value) = MagicMock()
        query = "¿Cómo funciona Docker?"
        svc.store_response("agent-1", query, "Respuesta.")
        call_args = svc._sb.table.return_value.upsert.call_args[0][0]
        assert "query_hash" in call_args
        assert call_args["query_hash"] == _compute_hash("agent-1", query)


# ─── Tests de invalidate_cache ────────────────────────────────────────────────

class TestInvalidateCache:
    def test_no_db_returns_zero(self):
        svc = make_svc_no_db()
        assert svc.invalidate_cache("agent-1") == 0

    def test_invalidates_all_entries(self):
        svc = make_svc()
        (svc._sb.table.return_value
            .delete.return_value
            .eq.return_value
            .execute.return_value.data) = [{"id": "c1"}, {"id": "c2"}]
        count = svc.invalidate_cache("agent-1")
        assert count == 2

    def test_invalidate_calls_delete_with_agent_id(self):
        svc = make_svc()
        (svc._sb.table.return_value
            .delete.return_value
            .eq.return_value
            .execute.return_value.data) = []
        svc.invalidate_cache("agent-xyz")
        svc._sb.table.return_value.delete.assert_called_once()


# ─── Tests de get_cache_stats ─────────────────────────────────────────────────

class TestCacheStats:
    def test_no_db_returns_zeros(self):
        svc = make_svc_no_db()
        stats = svc.get_cache_stats("agent-1")
        assert stats["total_entries"] == 0
        assert stats["total_hits"] == 0
        assert stats["avg_feedback"] == 0.0

    def test_stats_with_entries(self):
        svc = make_svc()
        (svc._sb.table.return_value
            .select.return_value
            .eq.return_value
            .execute.return_value.data) = [
                {"times_used": 5, "user_feedback": 1},
                {"times_used": 3, "user_feedback": -1},
                {"times_used": 1, "user_feedback": 0},
            ]
        stats = svc.get_cache_stats("agent-1")
        assert stats["total_entries"] == 3
        assert stats["total_hits"] == 9  # 5 + 3 + 1
        assert stats["avg_feedback"] == 0.0  # (1 + -1) / 2 = 0

    def test_positive_avg_feedback(self):
        svc = make_svc()
        (svc._sb.table.return_value
            .select.return_value
            .eq.return_value
            .execute.return_value.data) = [
                {"times_used": 2, "user_feedback": 1},
                {"times_used": 2, "user_feedback": 1},
            ]
        stats = svc.get_cache_stats("agent-1")
        assert stats["avg_feedback"] == 1.0


# ─── Tests de submit_feedback ─────────────────────────────────────────────────

class TestSubmitFeedback:
    def test_invalid_value_raises(self):
        svc = make_svc()
        with pytest.raises(ValueError, match="\\+1 o -1"):
            svc.submit_feedback("msg-1", "agent-1", "user-1", 0)

    def test_no_db_returns_basic_result(self):
        svc = make_svc_no_db()
        result = svc.submit_feedback("msg-1", "agent-1", "user-1", 1)
        assert result["feedback"] == 1
        assert result["message_id"] == "msg-1"

    def test_message_not_found_raises(self):
        svc = make_svc()
        svc._sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        with pytest.raises(ValueError, match="no encontrado"):
            svc.submit_feedback("bad-id", "agent-1", "user-1", 1)

    def test_non_assistant_message_raises(self):
        svc = make_svc()
        svc._sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "msg-1", "role": "user", "content": "Hola", "metadata": {}, "session_id": "sess-1"}
        ]
        with pytest.raises(ValueError, match="asistente"):
            svc.submit_feedback("msg-1", "agent-1", "user-1", 1)


# ─── Tests de prepare_resynthesis_context ─────────────────────────────────────

class TestPrepareResynthesisContext:
    def test_no_negative_messages_returns_cannot_resynthesize(self):
        svc = make_svc()
        with patch.object(svc, "get_negative_messages", return_value=[]):
            result = svc.prepare_resynthesis_context(
                agent_id="agent-1",
                user_id="user-1",
                current_instructions="Eres un asistente.",
            )
        assert result["can_resynthesize"] is False

    def test_with_negative_messages_returns_context(self):
        svc = make_svc()
        fake_negatives = [
            {"id": "m1", "content": "Respuesta incorrecta sobre Docker.", "metadata": {"feedback": -1}},
            {"id": "m2", "content": "Explicación confusa de Kubernetes.", "metadata": {"feedback": -1}},
        ]
        with patch.object(svc, "get_negative_messages", return_value=fake_negatives):
            result = svc.prepare_resynthesis_context(
                agent_id="agent-1",
                user_id="user-1",
                current_instructions="Eres un experto en DevOps.",
            )
        assert result["can_resynthesize"] is True
        assert result["negative_count"] == 2
        assert "failure_summary" in result
        assert "suggested_prompt" in result
        assert "Eres un experto en DevOps." in result["suggested_prompt"]
        assert "negative_examples" in result
        assert len(result["negative_examples"]) == 2

    def test_suggested_prompt_includes_current_instructions(self):
        svc = make_svc()
        fake_negatives = [
            {"id": "m1", "content": "Bad response.", "metadata": {"feedback": -1}},
        ]
        current = "Instrucciones originales del agente."
        with patch.object(svc, "get_negative_messages", return_value=fake_negatives):
            result = svc.prepare_resynthesis_context("a1", "u1", current)
        assert current in result["suggested_prompt"]
