"""
test_aft_compiler.py
Tests de la Fase 3: AFT Compiler y modelos Pydantic del perfil.

Estrategia de testing:
  - Todos los tests del compilador mockean la llamada a Gemini.
  - Se prueba: extracción de JSON, validación del schema, lógica de reintentos,
    validaciones de calidad (duplicados, placeholders, longitud) y los endpoints.
"""
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.services.aft_models import (
    AFTProfile,
    BehaviorExample,
    StyleRules,
    DomainConstraints,
    RetrievalProfile,
    CompileProfileRequest,
)
from app.services.instruction_compiler_service import (
    _extract_json,
    _format_validation_errors,
    compile_aft_profile,
)
from pydantic import ValidationError

client = TestClient(app)

# ─── Fixtures ─────────────────────────────────────────────────────────────────

USER_ID = "user-test-123"
AGENT_ID = "agent-test-456"
VALID_TOKEN = "Bearer valid-platform-token"


def make_auth_mock():
    mock = MagicMock()
    mock.auth.get_user.return_value = MagicMock(
        user=MagicMock(id=USER_ID, email="test@example.com")
    )
    return mock


def _make_valid_profile_dict(n_examples=12) -> dict:
    """Construye un dict de perfil AFT válido para usar en mocks."""
    examples = [
        {
            "input": f"¿Cómo implemento {topic} en Python de forma eficiente?",
            "output": f"Para implementar {topic} en Python de forma eficiente, debes considerar "
                      f"los siguientes aspectos fundamentales: primero, la arquitectura del sistema "
                      f"y cómo {topic} encaja en el contexto. Luego, las mejores prácticas "
                      f"específicas para este caso de uso.",
            "reasoning": f"Esta respuesta muestra expertise real en {topic} con contexto técnico."
        }
        for topic in [
            "una API REST", "caché distribuida", "procesamiento asíncrono",
            "autenticación JWT", "bases de datos relacionales", "microservicios",
            "CI/CD pipelines", "contenedores Docker", "monitorización",
            "tests unitarios", "patrones de diseño", "seguridad en APIs",
        ][:n_examples]
    ]
    return {
        "system_instructions": (
            "Eres un Ingeniero de Software Senior especializado en Python y arquitecturas cloud. "
            "Tu misión es proporcionar soluciones técnicas precisas, bien fundamentadas y listas "
            "para producción. Asumes que el usuario tiene conocimientos de programación. "
            "Respondes siempre con código funcional, explicas el razonamiento detrás de las "
            "decisiones de diseño y señalas los trade-offs de cada solución. "
            "Cuando una pregunta está fuera de tu dominio, lo indicas claramente y redirige "
            "al usuario a la fuente adecuada. Formato: markdown con bloques de código."
        ),
        "behavior_examples": examples,
        "style_rules": {
            "tone": "técnico y preciso, con foco en mejores prácticas",
            "response_format": "markdown con bloques de código Python",
            "verbosity": "adaptativo",
            "code_style": "PEP 8, type hints, docstrings Google style",
            "custom_rules": [
                "Siempre incluir manejo de errores en los ejemplos de código",
                "Mencionar complejidad temporal cuando sea relevante",
            ],
        },
        "domain_constraints": {
            "allowed_topics": ["Python", "FastAPI", "Docker", "AWS", "PostgreSQL", "arquitectura de software"],
            "forbidden_topics": ["recetas de cocina", "consejos personales", "política"],
            "expertise_level": "senior",
            "preferred_sources": ["documentación oficial de Python", "PEP standards", "AWS docs"],
            "language": "español",
            "out_of_scope_response": (
                "Lo siento, ese tema está fuera de mi área de especialización en desarrollo "
                "de software y arquitecturas cloud. Consulta a un especialista en ese campo."
            ),
        },
        "retrieval_profile": {
            "trigger_keywords": ["documentación", "cómo", "configurar", "instalar", "ejemplo", "error"],
            "always_retrieve": False,
            "top_k": 5,
            "context_injection": "prefix",
            "relevance_threshold": 0.6,
        },
    }


# ─── Tests de extracción de JSON ──────────────────────────────────────────────

class TestExtractJson:
    def test_extract_from_markdown_block(self):
        text = '```json\n{"key": "value"}\n```'
        result = _extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_from_plain_json(self):
        text = '{"key": "value"}'
        result = _extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_from_text_with_prefix(self):
        text = 'Aquí está el JSON:\n{"key": "value"}\nEspero que ayude.'
        result = _extract_json(text)
        parsed = json.loads(result)
        assert parsed["key"] == "value"

    def test_extract_nested_json(self):
        text = '{"a": {"b": {"c": 1}}}'
        result = _extract_json(text)
        parsed = json.loads(result)
        assert parsed["a"]["b"]["c"] == 1

    def test_extract_markdown_without_json_label(self):
        text = '```\n{"key": "value"}\n```'
        result = _extract_json(text)
        assert "key" in result


# ─── Tests de validación de AFTProfile ────────────────────────────────────────

class TestAFTProfileValidation:
    def test_valid_profile_passes(self):
        data = _make_valid_profile_dict()
        profile = AFTProfile(**data)
        assert len(profile.behavior_examples) == 12
        assert profile.style_rules.verbosity == "adaptativo"

    def test_too_few_examples_fails(self):
        data = _make_valid_profile_dict(n_examples=5)
        with pytest.raises(ValidationError) as exc_info:
            AFTProfile(**data)
        assert "behavior_examples" in str(exc_info.value)

    def test_too_many_examples_fails(self):
        data = _make_valid_profile_dict(n_examples=12)
        # Añadir 4 ejemplos extra para llegar a 16 (por encima del límite de 15)
        extra_topics = ["websockets", "message queues", "GraphQL APIs", "event-driven architecture"]
        for topic in extra_topics:
            data["behavior_examples"].append({
                "input": f"¿Cómo implemento {topic} correctamente en un sistema de alta disponibilidad?",
                "output": f"Para implementar {topic} en producción con alta disponibilidad necesitas considerar múltiples aspectos.",
                "reasoning": f"Ejemplo específico de {topic} en el dominio del agente."
            })
        assert len(data["behavior_examples"]) == 16
        with pytest.raises(ValidationError):
            AFTProfile(**data)

    def test_duplicate_examples_fail(self):
        data = _make_valid_profile_dict(n_examples=10)
        # Forzar duplicado: mismo input para todos
        for ex in data["behavior_examples"]:
            ex["input"] = "¿Cómo hago una API REST en Python de forma eficiente?"
        with pytest.raises(ValidationError) as exc_info:
            AFTProfile(**data)
        assert "similares" in str(exc_info.value).lower() or "duplicados" in str(exc_info.value).lower()

    def test_short_system_instructions_fails(self):
        data = _make_valid_profile_dict()
        data["system_instructions"] = "Eres un asistente."
        with pytest.raises(ValidationError):
            AFTProfile(**data)

    def test_invalid_verbosity_fails(self):
        data = _make_valid_profile_dict()
        data["style_rules"]["verbosity"] = "extremo"
        with pytest.raises(ValidationError):
            AFTProfile(**data)

    def test_invalid_expertise_level_fails(self):
        data = _make_valid_profile_dict()
        data["domain_constraints"]["expertise_level"] = "ninja"
        with pytest.raises(ValidationError):
            AFTProfile(**data)

    def test_invalid_context_injection_fails(self):
        data = _make_valid_profile_dict()
        data["retrieval_profile"]["context_injection"] = "random"
        with pytest.raises(ValidationError):
            AFTProfile(**data)

    def test_too_few_trigger_keywords_fails(self):
        data = _make_valid_profile_dict()
        data["retrieval_profile"]["trigger_keywords"] = ["uno", "dos"]
        with pytest.raises(ValidationError):
            AFTProfile(**data)

    def test_placeholder_in_example_fails(self):
        data = _make_valid_profile_dict()
        data["behavior_examples"][0]["input"] = "[input aquí]"
        with pytest.raises(ValidationError):
            AFTProfile(**data)

    def test_to_agent_version_dict_structure(self):
        data = _make_valid_profile_dict()
        profile = AFTProfile(**data)
        version_dict = profile.to_agent_version_dict()
        assert "system_instructions" in version_dict
        assert "behavior_examples" in version_dict
        assert "style_rules" in version_dict
        assert "domain_constraints" in version_dict
        assert "retrieval_profile" in version_dict
        assert isinstance(version_dict["behavior_examples"], list)


# ─── Tests del compilador (con mock de Gemini) ────────────────────────────────

class TestCompileAFTProfile:
    def _make_gemini_mock(self, response_dict: dict):
        """Crea un mock de genai.GenerativeModel que devuelve el dict dado."""
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.text = json.dumps(response_dict)
        mock_model.generate_content.return_value = mock_response
        return mock_model

    def _make_request(self) -> CompileProfileRequest:
        return CompileProfileRequest(
            agent_name="Python Expert",
            description=(
                "Agente especializado en Python y arquitectura de software. "
                "Responde a preguntas técnicas sobre Python, FastAPI, bases de datos, "
                "Docker, patrones de diseño y buenas prácticas de programación. "
                "Asume que el usuario tiene conocimientos previos de programación. "
                "Siempre incluye código funcional con manejo de errores."
            ),
            category="dev",
            base_tier="balanced",
            language="español",
        )

    def test_compile_success_on_first_attempt(self):
        valid_data = _make_valid_profile_dict()
        mock_model = self._make_gemini_mock(valid_data)

        with patch("app.services.instruction_compiler_service.config.GEMINI_API_KEY", "test-key"), \
             patch("app.services.instruction_compiler_service.genai.configure"), \
             patch("app.services.instruction_compiler_service.genai.GenerativeModel", return_value=mock_model):
            profile = compile_aft_profile(self._make_request())

        assert isinstance(profile, AFTProfile)
        assert len(profile.behavior_examples) == 12
        assert mock_model.generate_content.call_count == 1

    def test_compile_retries_on_invalid_json(self):
        """El compilador reintenta si el primer intento devuelve JSON inválido."""
        valid_data = _make_valid_profile_dict()

        call_count = 0
        def side_effect(prompt):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            if call_count == 1:
                mock_resp.text = "esto no es json válido {{{"
            else:
                mock_resp.text = json.dumps(valid_data)
            return mock_resp

        mock_model = MagicMock()
        mock_model.generate_content.side_effect = side_effect

        with patch("app.services.instruction_compiler_service.config.GEMINI_API_KEY", "test-key"), \
             patch("app.services.instruction_compiler_service.genai.configure"), \
             patch("app.services.instruction_compiler_service.genai.GenerativeModel", return_value=mock_model), \
             patch("app.services.instruction_compiler_service.time.sleep"):  # no esperar en tests
            profile = compile_aft_profile(self._make_request())

        assert isinstance(profile, AFTProfile)
        assert call_count == 2

    def test_compile_fails_after_max_attempts(self):
        """Si los 3 intentos fallan, lanza ValueError."""
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text="no es json {{{")

        with patch("app.services.instruction_compiler_service.config.GEMINI_API_KEY", "test-key"), \
             patch("app.services.instruction_compiler_service.genai.configure"), \
             patch("app.services.instruction_compiler_service.genai.GenerativeModel", return_value=mock_model), \
             patch("app.services.instruction_compiler_service.time.sleep"), \
             pytest.raises(ValueError) as exc_info:
            compile_aft_profile(self._make_request())

        assert "3 intentos" in str(exc_info.value)
        assert mock_model.generate_content.call_count == 3

    def test_compile_raises_runtime_if_no_api_key(self):
        with patch("app.services.instruction_compiler_service.config.GEMINI_API_KEY", ""):
            with pytest.raises(RuntimeError) as exc_info:
                compile_aft_profile(self._make_request())
        assert "GEMINI_API_KEY" in str(exc_info.value)

    def test_compile_handles_markdown_wrapped_json(self):
        """El compilador extrae JSON aunque venga dentro de un bloque markdown."""
        valid_data = _make_valid_profile_dict()
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(
            text=f"Aquí está el perfil:\n```json\n{json.dumps(valid_data)}\n```\nEspero que ayude."
        )

        with patch("app.services.instruction_compiler_service.config.GEMINI_API_KEY", "test-key"), \
             patch("app.services.instruction_compiler_service.genai.configure"), \
             patch("app.services.instruction_compiler_service.genai.GenerativeModel", return_value=mock_model):
            profile = compile_aft_profile(self._make_request())

        assert isinstance(profile, AFTProfile)


# ─── Tests de endpoints del compilador ────────────────────────────────────────

class TestCompilerEndpoints:
    COMPILE_PAYLOAD = {
        "agent_name": "Python Expert",
        "description": (
            "Agente especializado en Python y arquitectura de software. "
            "Responde a preguntas técnicas sobre Python, FastAPI, bases de datos, "
            "Docker y buenas prácticas de programación. Asume conocimientos previos."
        ),
        "category": "dev",
        "base_tier": "balanced",
        "language": "español",
    }

    def _mock_compile(self):
        valid_data = _make_valid_profile_dict()
        mock_model = MagicMock()
        mock_model.generate_content.return_value = MagicMock(text=json.dumps(valid_data))
        return mock_model

    def test_preview_requires_auth(self):
        resp = client.post("/platform/compiler/preview", json=self.COMPILE_PAYLOAD)
        assert resp.status_code == 401

    def test_preview_success(self):
        auth_sb = make_auth_mock()
        mock_model = self._mock_compile()

        with patch("app.services.platform_auth_service.platform_auth_service.supabase", auth_sb), \
             patch("app.services.instruction_compiler_service.config.GEMINI_API_KEY", "test-key"), \
             patch("app.services.instruction_compiler_service.genai.configure"), \
             patch("app.services.instruction_compiler_service.genai.GenerativeModel", return_value=mock_model):
            resp = client.post(
                "/platform/compiler/preview",
                json=self.COMPILE_PAYLOAD,
                headers={"Authorization": VALID_TOKEN},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "compiled"
        assert "profile" in data
        assert "summary" in data
        assert data["summary"]["behavior_examples_count"] == 12

    def test_preview_description_too_short(self):
        auth_sb = make_auth_mock()
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", auth_sb):
            resp = client.post(
                "/platform/compiler/preview",
                json={**self.COMPILE_PAYLOAD, "description": "Corto"},
                headers={"Authorization": VALID_TOKEN},
            )
        assert resp.status_code == 422

    def test_compile_agent_endpoint_requires_auth(self):
        resp = client.post(
            f"/platform/compiler/agents/{AGENT_ID}/compile",
            json=self.COMPILE_PAYLOAD,
        )
        assert resp.status_code == 401
