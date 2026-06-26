"""
test_provider_router.py
Tests de la Fase 5: Anti-429, cooldown, key pool y provider router.

Estrategia:
  - CooldownService: estado en memoria, sin dependencias externas.
  - KeyPool: bootstrap con keys ficticias, sin env vars reales.
  - ProviderRouter: todos los providers mockeados (sin llamadas HTTP reales).
"""
import time
import pytest
from unittest.mock import MagicMock, patch

from app.services.cooldown_service import CooldownService, KeyState, _calculate_backoff, CooldownReason
from app.services.provider_key_pool_service import (
    ProviderKeyPoolService, ProviderKey, PROVIDER_ORDER, PROVIDER_MODEL_MAP,
)
from app.services.provider_router_service import (
    ProviderRouterService, InferenceResult, InferenceError,
    _RateLimitError, _AuthError, _ServiceError, _parse_retry_after,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def make_cooldown() -> CooldownService:
    """CooldownService limpio, sin estado previo."""
    svc = CooldownService()
    return svc

def make_pool_with_keys(*providers) -> ProviderKeyPoolService:
    """KeyPool sin bootstrap de sistema, con keys ficticias inyectadas."""
    pool = ProviderKeyPoolService.__new__(ProviderKeyPoolService)
    import threading
    pool._lock = threading.Lock()
    pool._keys = {}
    for i, provider in enumerate(providers):
        key = ProviderKey(
            key_id=f"key-{provider}-{i}",
            provider=provider,
            api_key=f"sk-test-{provider}-{i}",
            tier="all",
            priority=i,
            source="system",
        )
        pool._keys[key.key_id] = key
        # También registrar en el cooldown global para que is_available funcione
        from app.services.cooldown_service import cooldown_service
        cooldown_service.register_key(key.key_id, provider, "test-model")
    return pool

def make_result(provider="groq", model="llama-3.1-8b") -> InferenceResult:
    return InferenceResult(
        content="Respuesta de prueba.",
        provider=provider,
        model=model,
        key_id="key-test",
        tokens_in=10,
        tokens_out=20,
        latency_ms=150.0,
    )


# ─── Tests de CooldownService ─────────────────────────────────────────────────

class TestCooldownService:

    def test_new_key_is_available(self):
        svc = make_cooldown()
        svc.register_key("k1", "groq", "llama-8b")
        assert svc.is_available("k1") is True

    def test_unknown_key_is_available(self):
        """Keys no registradas se consideran disponibles (fail-open)."""
        svc = make_cooldown()
        assert svc.is_available("unknown-key") is True

    def test_record_429_puts_key_in_cooldown(self):
        svc = make_cooldown()
        svc.register_key("k1", "groq", "llama-8b")
        svc.record_429("k1")
        assert svc.is_available("k1") is False

    def test_cooldown_expires(self):
        """Simula que el cooldown ya pasó manipulando el estado interno."""
        svc = make_cooldown()
        svc.register_key("k1", "groq", "llama-8b")
        # Forzar cooldown expirado (en el pasado)
        svc._states["k1"].cooldown_until = time.monotonic() - 1.0
        assert svc.is_available("k1") is True

    def test_record_auth_error_marks_invalid(self):
        svc = make_cooldown()
        svc.register_key("k1", "groq", "llama-8b")
        svc.record_auth_error("k1")
        assert svc.is_available("k1") is False
        assert svc._states["k1"].is_permanently_invalid is True

    def test_reset_key_clears_cooldown(self):
        svc = make_cooldown()
        svc.register_key("k1", "groq", "llama-8b")
        svc.record_429("k1")
        assert svc.is_available("k1") is False
        svc.reset_key("k1")
        assert svc.is_available("k1") is True

    def test_consecutive_429s_increase_backoff(self):
        """Más errores consecutivos → mayor cooldown."""
        state = KeyState(key_id="k1", provider="groq", model="m1")
        state.record_429()
        first_cooldown = state.cooldown_until

        state2 = KeyState(key_id="k2", provider="groq", model="m1")
        state2.consecutive_errors = 3
        state2.record_429()
        second_cooldown = state2.cooldown_until

        assert second_cooldown > first_cooldown

    def test_record_503_applies_short_cooldown(self):
        svc = make_cooldown()
        svc.register_key("k1", "groq", "llama-8b")
        svc.record_503("k1")
        assert svc.is_available("k1") is False
        # El cooldown de 503 debe ser menor que 5 minutos
        remaining = svc.seconds_until_available("k1")
        assert remaining < 300

    def test_rpm_window_prevents_overuse(self):
        """La ventana deslizante debe bloquear la key si se supera el RPM."""
        svc = make_cooldown()
        svc.register_key("k1", "groq", "llama-8b")
        # Simular 5 requests con rpm_limit=5
        state = svc._states["k1"]
        now = time.monotonic()
        state.request_timestamps = [now - i for i in range(5)]  # 5 en los últimos 60s
        assert svc.is_available("k1", rpm_limit=5) is False

    def test_old_rpm_timestamps_are_cleaned(self):
        """Timestamps de más de 60s se limpian automáticamente."""
        svc = make_cooldown()
        svc.register_key("k1", "groq", "llama-8b")
        state = svc._states["k1"]
        # 5 requests pero hace más de 60s
        old_time = time.monotonic() - 65.0
        state.request_timestamps = [old_time] * 5
        assert svc.is_available("k1", rpm_limit=5) is True

    def test_get_stats_returns_dict(self):
        svc = make_cooldown()
        svc.register_key("k1", "groq", "llama-8b")
        stats = svc.get_stats("k1")
        assert stats is not None
        assert stats["key_id"] == "k1"
        assert stats["provider"] == "groq"
        assert "is_available" in stats
        assert "total_requests" in stats

    def test_get_stats_unknown_key_returns_none(self):
        svc = make_cooldown()
        assert svc.get_stats("nonexistent") is None

    def test_record_success_resets_consecutive_errors(self):
        svc = make_cooldown()
        svc.register_key("k1", "groq", "llama-8b")
        svc._states["k1"].consecutive_errors = 3
        svc.record_success("k1", tokens_in=100, tokens_out=200)
        assert svc._states["k1"].consecutive_errors == 0
        assert svc._states["k1"].total_tokens_in == 100
        assert svc._states["k1"].total_tokens_out == 200


# ─── Tests de _calculate_backoff ──────────────────────────────────────────────

class TestBackoff:
    def test_first_429_is_at_least_10s(self):
        result = _calculate_backoff(consecutive=1, base=60.0)
        assert result >= 10.0

    def test_backoff_increases_with_consecutive(self):
        b1 = _calculate_backoff(consecutive=1, base=60.0)
        b2 = _calculate_backoff(consecutive=3, base=60.0)
        # Con jitter no podemos garantizar b2 > b1 en cada ejecución,
        # pero el promedio de b3 es 4x b1, así que con consecutive=4 siempre > b1
        b4 = _calculate_backoff(consecutive=5, base=60.0)
        assert b4 > b1

    def test_backoff_caps_at_900s(self):
        result = _calculate_backoff(consecutive=20, base=60.0)
        assert result <= 900.0

    def test_retry_after_is_respected(self):
        result = _calculate_backoff(consecutive=1, base=60.0, override_seconds=120.0)
        assert result >= 120.0

    def test_retry_after_caps_at_900s(self):
        result = _calculate_backoff(consecutive=1, base=60.0, override_seconds=1000.0)
        assert result <= 900.0


# ─── Tests de _parse_retry_after ─────────────────────────────────────────────

class TestParseRetryAfter:
    def test_numeric_string(self):
        headers = {"retry-after": "30"}
        assert _parse_retry_after(headers) == 30.0

    def test_float_string(self):
        headers = {"Retry-After": "45.5"}
        assert _parse_retry_after(headers) == 45.5

    def test_missing_header_returns_none(self):
        assert _parse_retry_after({}) is None

    def test_none_headers_returns_none(self):
        assert _parse_retry_after(None) is None

    def test_extracts_number_from_text(self):
        headers = {"retry-after": "retry in 60 seconds"}
        result = _parse_retry_after(headers)
        assert result == 60.0


# ─── Tests de ProviderKeyPoolService ─────────────────────────────────────────

class TestKeyPool:
    def test_get_best_key_returns_available(self):
        pool = make_pool_with_keys("groq")
        key = pool.get_best_key(provider="groq", tier="balanced")
        assert key is not None
        assert key.provider == "groq"

    def test_get_best_key_returns_none_if_all_on_cooldown(self):
        pool = make_pool_with_keys("groq")
        # Poner la única key en cooldown
        key_id = list(pool._keys.keys())[0]
        from app.services.cooldown_service import cooldown_service
        cooldown_service._states[key_id].cooldown_until = time.monotonic() + 999
        key = pool.get_best_key(provider="groq", tier="balanced")
        assert key is None

    def test_get_best_key_returns_none_for_unknown_provider(self):
        pool = make_pool_with_keys("groq")
        key = pool.get_best_key(provider="openrouter", tier="balanced")
        assert key is None

    def test_provider_order_fast_tier(self):
        order = PROVIDER_ORDER["fast"]
        assert order[0] == "groq"   # Groq primero en fast

    def test_provider_order_pro_tier(self):
        order = PROVIDER_ORDER["pro"]
        assert order[0] == "google"  # Gemini primero en pro

    def test_model_map_coverage(self):
        """Todos los tiers tienen modelos configurados para todos los providers."""
        for provider in ("groq", "google", "openrouter"):
            for tier in ("fast", "balanced", "pro"):
                model = PROVIDER_MODEL_MAP[provider][tier]
                assert model, f"Falta modelo para {provider}/{tier}"

    def test_add_user_key(self):
        pool = make_pool_with_keys()
        pool.add_user_key(
            key_id="user-k1",
            provider="groq",
            api_key="sk-user-groq",
            user_id="user-123",
            tier="all",
        )
        assert "user-k1" in pool._keys
        assert pool._keys["user-k1"].source == "user"

    def test_remove_user_keys(self):
        pool = make_pool_with_keys()
        pool.add_user_key("uk1", "groq", "sk1", "user-1", "all")
        pool.add_user_key("uk2", "google", "sk2", "user-1", "all")
        pool.add_user_key("uk3", "groq", "sk3", "user-2", "all")
        removed = pool.remove_user_keys("user-1")
        assert removed == 2
        assert "uk1" not in pool._keys
        assert "uk3" in pool._keys

    def test_get_pool_status_hides_api_key(self):
        pool = make_pool_with_keys("groq")
        status = pool.get_pool_status()
        for entry in status:
            assert "api_key" not in entry
            assert "sk-" not in str(entry)


# ─── Tests del ProviderRouterService ─────────────────────────────────────────

class TestProviderRouter:

    def _make_fresh_pool(self, *providers) -> ProviderKeyPoolService:
        """
        Pool limpio con keys ficticias y cooldown_service fresco por test,
        evitando contaminacion del singleton global entre tests.
        """
        fresh_cooldown = CooldownService()  # instancia limpia
        pool = ProviderKeyPoolService.__new__(ProviderKeyPoolService)
        import threading
        pool._lock = threading.Lock()
        pool._keys = {}
        for i, provider in enumerate(providers):
            key = ProviderKey(
                key_id=f"key-{provider}-fresh-{i}",
                provider=provider,
                api_key=f"sk-test-{provider}-fresh",
                tier="all",
                priority=i,
                source="system",
            )
            pool._keys[key.key_id] = key
            fresh_cooldown.register_key(key.key_id, provider, "test-model")
        # Devolvemos también el cooldown para poder parchear ambos
        pool._fresh_cooldown = fresh_cooldown
        return pool

    def _patches(self, pool):
        """Context managers de patches necesarios para aislar el router."""
        return (
            patch("app.services.provider_router_service.key_pool", pool),
            patch("app.services.provider_key_pool_service.cooldown_service", pool._fresh_cooldown),
            patch("app.services.provider_router_service.cooldown_service", pool._fresh_cooldown),
        )

    def test_successful_call_groq(self):
        pool = self._make_fresh_pool("groq")
        router = ProviderRouterService()
        expected = make_result("groq")
        p1, p2, p3 = self._patches(pool)
        with p1, p2, p3, \
             patch("app.services.provider_router_service._call_groq", return_value=expected):
            result = router.infer(
                messages=[{"role": "user", "content": "Hola"}],
                tier="fast",
            )
        assert result.provider == "groq"
        assert result.content == "Respuesta de prueba."

    def test_successful_call_gemini(self):
        pool = self._make_fresh_pool("google")
        router = ProviderRouterService()
        expected = make_result("google", "gemini-2.5-flash")
        p1, p2, p3 = self._patches(pool)
        with p1, p2, p3, \
             patch("app.services.provider_router_service._call_gemini", return_value=expected):
            result = router.infer(
                messages=[{"role": "user", "content": "Hola"}],
                tier="balanced",
                force_provider="google",
            )
        assert result.provider == "google"

    def test_fallback_on_429(self):
        """Si google da 429, debe intentar groq como fallback (balanced: google→groq→openrouter)."""
        pool = self._make_fresh_pool("google", "groq")
        router = ProviderRouterService()
        groq_result = make_result("groq", "llama-3.3-70b-versatile")
        call_count = {"groq": 0, "google": 0}

        def mock_dispatch(provider, model, messages, api_key, system_prompt, temperature, max_tokens):
            call_count[provider] = call_count.get(provider, 0) + 1
            if provider == "google":
                raise _RateLimitError(429, "rate limited", retry_after=30)
            return groq_result

        p1, p2, p3 = self._patches(pool)
        with p1, p2, p3, patch.object(router, "_dispatch", side_effect=mock_dispatch):
            result = router.infer(
                messages=[{"role": "user", "content": "Test"}],
                tier="balanced",
            )

        assert result.provider == "groq"
        assert call_count["google"] >= 1

    def test_fallback_on_503(self):
        """Si groq da 503 (servicio caído), debe pasar directo al siguiente provider."""
        pool = self._make_fresh_pool("groq", "google")
        router = ProviderRouterService()
        google_result = make_result("google")

        def mock_dispatch(provider, model, messages, api_key, system_prompt, temperature, max_tokens):
            if provider == "groq":
                raise _ServiceError(503, "overloaded")
            return google_result

        p1, p2, p3 = self._patches(pool)
        with p1, p2, p3, patch.object(router, "_dispatch", side_effect=mock_dispatch):
            result = router.infer(
                messages=[{"role": "user", "content": "Test"}],
                tier="balanced",
            )
        assert result.provider == "google"

    def test_raises_inference_error_when_all_fail(self):
        """Si todos los providers fallan, debe lanzar InferenceError."""
        pool = self._make_fresh_pool("groq", "google", "openrouter")
        router = ProviderRouterService()

        def mock_dispatch(provider, model, messages, api_key, system_prompt, temperature, max_tokens):
            raise _RateLimitError(429, f"{provider} rate limited", retry_after=60)

        p1, p2, p3 = self._patches(pool)
        with p1, p2, p3, \
             patch.object(router, "_dispatch", side_effect=mock_dispatch), \
             pytest.raises(InferenceError) as exc_info:
            router.infer(
                messages=[{"role": "user", "content": "Test"}],
                tier="balanced",
            )

        error = exc_info.value
        assert len(error.attempts) > 0
        error_dict = error.to_dict()
        assert "attempts" in error_dict

    def test_auth_error_skips_provider(self):
        """Un 401 en google debe marcar la key como inválida y pasar al siguiente (groq)."""
        pool = self._make_fresh_pool("google", "groq")
        router = ProviderRouterService()
        groq_result = make_result("groq")

        def mock_dispatch(provider, model, messages, api_key, system_prompt, temperature, max_tokens):
            if provider == "google":
                raise _AuthError(401, "invalid key")
            return groq_result

        p1, p2, p3 = self._patches(pool)
        with p1, p2, p3, patch.object(router, "_dispatch", side_effect=mock_dispatch):
            result = router.infer(
                messages=[{"role": "user", "content": "Test"}],
                tier="balanced",
            )
        assert result.provider == "groq"
        # Verificar que la key de google fue marcada como inválida en el cooldown fresco
        google_key_id = [k for k in pool._keys if "google" in k][0]
        assert pool._fresh_cooldown._states[google_key_id].is_permanently_invalid is True

    def test_tokens_registered_on_success(self):
        """Los tokens in/out se registran correctamente en el cooldown."""
        pool = self._make_fresh_pool("groq")
        router = ProviderRouterService()
        expected = InferenceResult(
            content="ok", provider="groq", model="llama-8b",
            key_id="", tokens_in=50, tokens_out=100, latency_ms=200,
        )

        p1, p2, p3 = self._patches(pool)
        with p1, p2, p3, patch.object(router, "_dispatch", return_value=expected):
            result = router.infer(
                messages=[{"role": "user", "content": "Test"}],
                tier="fast",
            )
        groq_key_id = [k for k in pool._keys if "groq" in k][0]
        stats = pool._fresh_cooldown.get_stats(groq_key_id)
        assert stats["total_tokens_in"] == 50
        assert stats["total_tokens_out"] == 100

    def test_force_provider_override(self):
        """force_provider debe ignorar el orden del tier."""
        pool = self._make_fresh_pool("openrouter")
        router = ProviderRouterService()
        expected = make_result("openrouter")

        p1, p2, p3 = self._patches(pool)
        with p1, p2, p3, patch.object(router, "_dispatch", return_value=expected):
            result = router.infer(
                messages=[{"role": "user", "content": "Test"}],
                tier="balanced",
                force_provider="openrouter",
            )
        assert result.provider == "openrouter"
