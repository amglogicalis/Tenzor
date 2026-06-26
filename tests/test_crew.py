"""
test_crew.py
Tests de la Fase 10: Arzor DevCrew — generación de planes y código.
"""
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.services.crew_service import DevCrewService
from app.services.provider_router_service import InferenceResult, InferenceError

client = TestClient(app)

# ─── Fixtures ─────────────────────────────────────────────────────────────────

FAKE_PLAN_JSON = {
    "summary": "Implementar un sistema de caché Redis en la API FastAPI.",
    "complexity": "medium",
    "estimated_hours": 4,
    "steps": [
        {
            "id": 1,
            "title": "Instalar y configurar redis-py",
            "description": "Añadir redis-py a requirements.txt y crear RedisClient.",
            "files": ["requirements.txt", "app/services/redis_client.py"],
            "type": "create",
        },
        {
            "id": 2,
            "title": "Integrar caché en endpoints",
            "description": "Añadir decorador de caché en los endpoints principales.",
            "files": ["app/routers/chat.py"],
            "type": "modify",
        },
    ],
    "risks": ["Invalidación de caché incorrecta", "Overhead de serialización"],
    "dependencies": ["redis>=5.0", "hiredis"],
}

FAKE_CODE_JSON = {
    "file": "app/services/redis_client.py",
    "language": "python",
    "code": "import redis\n\nclient = redis.Redis(host='localhost', port=6379)\n",
    "integration_notes": "Importar `client` desde este módulo en los routers.",
    "test_hints": ["Probar conexión con client.ping()", "Mockear redis en tests"],
}

FAKE_INFERENCE_PLAN = InferenceResult(
    content=json.dumps(FAKE_PLAN_JSON),
    provider="groq", model="llama-3.1-8b",
    key_id="sys-groq-1", tokens_in=100, tokens_out=300,
    latency_ms=800.0, finish_reason="stop",
)

FAKE_INFERENCE_CODE = InferenceResult(
    content=json.dumps(FAKE_CODE_JSON),
    provider="groq", model="llama-3.1-8b",
    key_id="sys-groq-1", tokens_in=150, tokens_out=200,
    latency_ms=600.0, finish_reason="stop",
)


def make_svc() -> DevCrewService:
    svc = DevCrewService.__new__(DevCrewService)
    svc._sb = None
    return svc


def _auth_override():
    from app.middleware.platform_auth_middleware import require_platform_user
    app.dependency_overrides[require_platform_user] = lambda: {"user_id": "user-1", "username": "test"}


def _clear_auth():
    from app.middleware.platform_auth_middleware import require_platform_user
    app.dependency_overrides.pop(require_platform_user, None)


# ─── Tests de _parse_json_response ───────────────────────────────────────────

class TestParseJsonResponse:
    def test_valid_json(self):
        svc = make_svc()
        data = {"key": "value", "num": 42}
        result = svc._parse_json_response(json.dumps(data))
        assert result["key"] == "value"

    def test_json_with_code_fences(self):
        svc = make_svc()
        content = '```json\n{"summary": "test"}\n```'
        result = svc._parse_json_response(content)
        assert result["summary"] == "test"

    def test_json_with_surrounding_text(self):
        svc = make_svc()
        content = 'Aquí está el plan:\n{"summary": "mi plan"}\nEspero que sirva.'
        result = svc._parse_json_response(content)
        assert result["summary"] == "mi plan"

    def test_invalid_json_returns_raw(self):
        svc = make_svc()
        content = "No es JSON en absoluto, solo texto."
        result = svc._parse_json_response(content)
        assert "raw_response" in result
        assert "error" in result


# ─── Tests de generate_plan ───────────────────────────────────────────────────

class TestGeneratePlan:
    def test_short_task_raises(self):
        svc = make_svc()
        with pytest.raises(ValueError, match="10 caracteres"):
            svc.generate_plan("user-1", "corto")

    def test_successful_plan(self):
        svc = make_svc()
        with patch("app.services.crew_service.provider_router.infer",
                   return_value=FAKE_INFERENCE_PLAN):
            result = svc.generate_plan("user-1", "Implementar sistema de caché Redis")
        assert result["summary"] == FAKE_PLAN_JSON["summary"]
        assert result["complexity"] == "medium"
        assert len(result["steps"]) == 2
        assert "_meta" in result

    def test_meta_includes_provider_info(self):
        svc = make_svc()
        with patch("app.services.crew_service.provider_router.infer",
                   return_value=FAKE_INFERENCE_PLAN):
            result = svc.generate_plan("user-1", "Tarea de desarrollo larga")
        meta = result["_meta"]
        assert meta["provider"] == "groq"
        assert meta["tokens_in"] == 100
        assert meta["tokens_out"] == 300

    def test_inference_error_raises_value_error(self):
        svc = make_svc()
        with patch("app.services.crew_service.provider_router.infer",
                   side_effect=InferenceError("All providers failed", attempts=3)):
            with pytest.raises(ValueError, match="Error al generar el plan"):
                svc.generate_plan("user-1", "Tarea que falla por error de provider")

    def test_plan_uses_correct_tier(self):
        svc = make_svc()
        calls = []
        def capture_infer(**kwargs):
            calls.append(kwargs)
            return FAKE_INFERENCE_PLAN
        with patch("app.services.crew_service.provider_router.infer", side_effect=capture_infer):
            svc.generate_plan("user-1", "Tarea de prueba larga", tier="pro")
        assert calls[0]["tier"] == "pro"

    def test_plan_temperature_is_low(self):
        """Plan debe usar temperatura baja para precisión."""
        svc = make_svc()
        calls = []
        def capture_infer(**kwargs):
            calls.append(kwargs)
            return FAKE_INFERENCE_PLAN
        with patch("app.services.crew_service.provider_router.infer", side_effect=capture_infer):
            svc.generate_plan("user-1", "Tarea de prueba larga")
        assert calls[0]["temperature"] <= 0.4

    def test_plan_json_in_code_fences_parsed_correctly(self):
        """LLM puede responder con código rodeado de ``` — debe parsearse."""
        svc = make_svc()
        fenced_response = f"```json\n{json.dumps(FAKE_PLAN_JSON)}\n```"
        fenced_result = InferenceResult(
            content=fenced_response, provider="groq", model="m",
            key_id="k", tokens_in=10, tokens_out=20, latency_ms=100.0, finish_reason="stop",
        )
        with patch("app.services.crew_service.provider_router.infer", return_value=fenced_result):
            result = svc.generate_plan("user-1", "Tarea con respuesta en fenced JSON")
        assert result["complexity"] == "medium"


# ─── Tests de generate_code ───────────────────────────────────────────────────

class TestGenerateCode:
    def test_empty_title_raises(self):
        svc = make_svc()
        with pytest.raises(ValueError, match="requeridos"):
            svc.generate_code("user-1", "", "descripción", [])

    def test_successful_code(self):
        svc = make_svc()
        with patch("app.services.crew_service.provider_router.infer",
                   return_value=FAKE_INFERENCE_CODE):
            result = svc.generate_code(
                "user-1",
                "Crear RedisClient",
                "Cliente Redis reutilizable con connection pool",
                ["app/services/redis_client.py"],
            )
        assert result["file"] == "app/services/redis_client.py"
        assert "redis" in result["code"]
        assert "_meta" in result

    def test_code_temperature_is_very_low(self):
        """Código debe usar temperatura muy baja para determinismo."""
        svc = make_svc()
        calls = []
        def capture_infer(**kwargs):
            calls.append(kwargs)
            return FAKE_INFERENCE_CODE
        with patch("app.services.crew_service.provider_router.infer", side_effect=capture_infer):
            svc.generate_code("user-1", "Paso X", "Descripción del paso X", [])
        assert calls[0]["temperature"] <= 0.3

    def test_existing_code_included_in_prompt(self):
        """El código existente debe estar en el prompt enviado al LLM."""
        svc = make_svc()
        prompts_seen = []
        def capture_infer(**kwargs):
            prompts_seen.append(kwargs["messages"][0]["content"])
            return FAKE_INFERENCE_CODE
        with patch("app.services.crew_service.provider_router.infer", side_effect=capture_infer):
            svc.generate_code("user-1", "Paso", "Desc", [],
                              existing_code="class ExistingModel:\n    pass")
        assert "ExistingModel" in prompts_seen[0]

    def test_existing_code_truncated_at_3000_chars(self):
        """El código existente se trunca a 3000 chars para no saturar el prompt."""
        svc = make_svc()
        prompts_seen = []
        def capture_infer(**kwargs):
            prompts_seen.append(kwargs["messages"][0]["content"])
            return FAKE_INFERENCE_CODE
        long_code = "x" * 5000
        with patch("app.services.crew_service.provider_router.infer", side_effect=capture_infer):
            svc.generate_code("user-1", "Paso", "Desc", [], existing_code=long_code)
        # El prompt no debe tener las 5000 x
        assert "x" * 3001 not in prompts_seen[0]


# ─── Tests de Endpoints HTTP ──────────────────────────────────────────────────

class TestCrewEndpoints:

    def setup_method(self):
        _auth_override()

    def teardown_method(self):
        _clear_auth()

    def test_plan_requires_auth(self):
        _clear_auth()
        resp = client.post("/platform/crew/plan", json={"task": "Tarea de prueba larga"})
        assert resp.status_code in (401, 403)

    def test_plan_success(self):
        with patch("app.routers.crew._crew.generate_plan", return_value=FAKE_PLAN_JSON):
            resp = client.post("/platform/crew/plan", json={
                "task": "Implementar sistema de caché Redis para mejorar performance",
                "tech_stack": "Python, FastAPI, Redis",
                "tier": "balanced",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["complexity"] == "medium"
        assert len(data["steps"]) == 2

    def test_plan_short_task_rejected(self):
        resp = client.post("/platform/crew/plan", json={"task": "corto"})
        assert resp.status_code == 422

    def test_plan_invalid_tier_rejected(self):
        resp = client.post("/platform/crew/plan", json={
            "task": "Tarea válida larga", "tier": "ultra"
        })
        assert resp.status_code == 422

    def test_plan_service_error_returns_400(self):
        with patch("app.routers.crew._crew.generate_plan",
                   side_effect=ValueError("Error al generar el plan")):
            resp = client.post("/platform/crew/plan", json={
                "task": "Tarea que provoca error interno del servicio"
            })
        assert resp.status_code == 400

    def test_write_requires_auth(self):
        _clear_auth()
        resp = client.post("/platform/crew/write", json={
            "step_title": "Crear módulo", "step_description": "Descripción detallada del módulo"
        })
        assert resp.status_code in (401, 403)

    def test_write_success(self):
        with patch("app.routers.crew._crew.generate_code", return_value=FAKE_CODE_JSON):
            resp = client.post("/platform/crew/write", json={
                "step_title": "Crear RedisClient",
                "step_description": "Cliente Redis reutilizable con connection pool y retry",
                "files": ["app/services/redis_client.py"],
                "tier": "balanced",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["file"] == "app/services/redis_client.py"
        assert data["language"] == "python"
        assert "redis" in data["code"]

    def test_write_missing_step_title(self):
        resp = client.post("/platform/crew/write", json={
            "step_description": "Solo descripción sin título"
        })
        assert resp.status_code == 422

    def test_write_missing_step_desc(self):
        resp = client.post("/platform/crew/write", json={
            "step_title": "Solo título sin descripción"
        })
        assert resp.status_code == 422

    def test_write_service_error_returns_400(self):
        with patch("app.routers.crew._crew.generate_code",
                   side_effect=ValueError("Error al generar el código")):
            resp = client.post("/platform/crew/write", json={
                "step_title": "Paso con error",
                "step_description": "Este paso genera un error en el servicio"
            })
        assert resp.status_code == 400

    def test_plan_with_agent_id(self):
        """Puede pasarse un agent_id opcional."""
        with patch("app.routers.crew._crew.generate_plan", return_value=FAKE_PLAN_JSON) as mock:
            resp = client.post("/platform/crew/plan", json={
                "task": "Tarea con agente específico",
                "agent_id": "agent-123",
            })
        assert resp.status_code == 200
        call_kwargs = mock.call_args[1]
        assert call_kwargs["agent_id"] == "agent-123"
