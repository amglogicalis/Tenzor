"""
test_round_table.py
Tests de la Fase 8: Arzor Round Table (debate multi-agente).

Estrategia:
  - RoundTableService._sb mockeado completamente.
  - provider_router.infer mockeado para evitar llamadas HTTP.
  - Tests de endpoints HTTP con TestClient y dependency_overrides.
"""
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.services.round_table_service import (
    RoundTableService, RoundTableTurn, RoundTableResult,
    MIN_AGENTS, MAX_AGENTS, MIN_ROUNDS, MAX_ROUNDS,
)
from app.services.provider_router_service import InferenceResult, InferenceError

client = TestClient(app)

# ─── Fixtures ─────────────────────────────────────────────────────────────────

FAKE_TABLE = {
    "id": "table-1",
    "user_id": "user-1",
    "name": "Mesa de prueba",
    "description": "Test",
    "topic": "¿Debería usarse microservicios o monolito?",
    "status": "idle",
    "result": None,
    "created_at": "2025-01-01T00:00:00Z",
    "updated_at": "2025-01-01T00:00:00Z",
}

FAKE_TABLE_DONE = {**FAKE_TABLE, "status": "done",
                   "result": json.dumps({"synthesis": "Síntesis del debate.", "turns": []})}

AGENT_1 = {
    "id": "agent-1", "user_id": "user-1", "name": "Agente DevOps",
    "base_tier": "fast", "is_public": False, "deleted_at": None,
    "current_version_id": "ver-1",
    "current_version": {"system_instructions": "Eres un experto en DevOps.", "retrieval_profile": None},
}
AGENT_2 = {
    "id": "agent-2", "user_id": "user-1", "name": "Agente Arquitecto",
    "base_tier": "balanced", "is_public": False, "deleted_at": None,
    "current_version_id": "ver-2",
    "current_version": {"system_instructions": "Eres un arquitecto de software.", "retrieval_profile": None},
}

FAKE_INFERENCE = InferenceResult(
    content="Esta es mi opinión sobre el tema del debate.",
    provider="groq", model="llama-3.1-8b",
    key_id="sys-groq-1", tokens_in=50, tokens_out=80,
    latency_ms=200.0, finish_reason="stop",
)

FAKE_MEMBERS = [
    {"agent_id": "agent-1", "turn_order": 0},
    {"agent_id": "agent-2", "turn_order": 1},
]


def make_svc() -> RoundTableService:
    svc = RoundTableService.__new__(RoundTableService)
    svc._sb = MagicMock()
    return svc


def _auth_override(user_id="user-1"):
    from app.middleware.platform_auth_middleware import require_platform_user
    app.dependency_overrides[require_platform_user] = lambda: {"user_id": user_id, "username": "test"}


def _clear_auth():
    from app.middleware.platform_auth_middleware import require_platform_user
    app.dependency_overrides.pop(require_platform_user, None)


# ─── Tests de RoundTableTurn y RoundTableResult ───────────────────────────────

class TestRoundTableDTOs:
    def test_turn_to_dict(self):
        turn = RoundTableTurn(
            agent_id="a1", agent_name="Agente", round_num=1,
            content="Mi turno.", provider="groq", model="llama",
            tokens_in=10, tokens_out=20, latency_ms=100.0,
        )
        d = turn.to_dict()
        assert d["agent_id"] == "a1"
        assert d["round"] == 1
        assert d["content"] == "Mi turno."

    def test_result_to_dict(self):
        turn = RoundTableTurn("a1", "A", 1, "Texto", "groq", "m", 5, 10, 50.0)
        result = RoundTableResult(
            table_id="t1", topic="Tema", turns=[turn],
            synthesis="Síntesis.", total_tokens=15, total_latency_ms=50.0,
        )
        d = result.to_dict()
        assert d["table_id"] == "t1"
        assert d["turn_count"] == 1
        assert d["synthesis"] == "Síntesis."
        assert len(d["turns"]) == 1


# ─── Tests de _format_history ─────────────────────────────────────────────────

class TestFormatHistory:
    def test_empty_history(self):
        svc = make_svc()
        assert svc._format_history([]) == ""

    def test_single_turn(self):
        turn = RoundTableTurn("a1", "DevOps", 1, "Prefiero microservicios.",
                              "groq", "m", 5, 10, 50.0)
        svc = make_svc()
        result = svc._format_history([turn])
        assert "Ronda 1" in result
        assert "DevOps" in result
        assert "microservicios" in result

    def test_multiple_turns_separated(self):
        t1 = RoundTableTurn("a1", "A", 1, "Turno 1", "groq", "m", 5, 10, 50.0)
        t2 = RoundTableTurn("a2", "B", 1, "Turno 2", "groq", "m", 5, 10, 50.0)
        svc = make_svc()
        result = svc._format_history([t1, t2])
        assert "---" in result
        assert "Turno 1" in result
        assert "Turno 2" in result


# ─── Tests de _extract_instructions ──────────────────────────────────────────

class TestExtractInstructions:
    def test_from_version(self):
        svc = make_svc()
        assert svc._extract_instructions(AGENT_1) == "Eres un experto en DevOps."

    def test_fallback_to_agent_field(self):
        svc = make_svc()
        agent = {"name": "Test", "system_instructions": "Fallback.", "current_version": None}
        assert svc._extract_instructions(agent) == "Fallback."

    def test_default_fallback(self):
        svc = make_svc()
        agent = {"name": "Mi Agente", "current_version": None}
        result = svc._extract_instructions(agent)
        assert "Mi Agente" in result


# ─── Tests de CRUD de mesas ───────────────────────────────────────────────────

class TestCreateTable:
    def test_short_topic_raises(self):
        svc = make_svc()
        with pytest.raises(ValueError, match="10 caracteres"):
            svc.create_table("u1", "Mesa", None, "corto")

    def test_create_calls_insert(self):
        svc = make_svc()
        svc._sb.table.return_value.insert.return_value.execute.return_value.data = [FAKE_TABLE]
        result = svc.create_table("u1", "Mesa", None, "¿Microservicios o monolito?")
        assert result["name"] == "Mesa de prueba"
        svc._sb.table.return_value.insert.assert_called_once()


class TestGetTable:
    def test_not_found_raises(self):
        svc = make_svc()
        svc._sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
        with pytest.raises(ValueError, match="no encontrada"):
            svc.get_table("bad-id", "user-1")

    def test_found_returns_table(self):
        svc = make_svc()
        svc._sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [FAKE_TABLE]
        result = svc.get_table("table-1", "user-1")
        assert result["id"] == "table-1"


# ─── Tests de add_member ──────────────────────────────────────────────────────

class TestAddMember:
    def test_running_table_raises(self):
        svc = make_svc()
        running_table = {**FAKE_TABLE, "status": "running"}
        with patch.object(svc, "get_table", return_value=running_table):
            with pytest.raises(ValueError, match="idle"):
                svc.add_member("table-1", "user-1", "agent-1")

    def test_max_agents_raises(self):
        svc = make_svc()
        with patch.object(svc, "get_table", return_value=FAKE_TABLE):
            # Simular MAX_AGENTS miembros ya existentes
            svc._sb.table.return_value.select.return_value.eq.return_value.execute.return_value.count = MAX_AGENTS
            with pytest.raises(ValueError, match=f"Máximo {MAX_AGENTS}"):
                svc.add_member("table-1", "user-1", "agent-x")

    def test_add_member_success(self):
        svc = make_svc()
        with patch.object(svc, "get_table", return_value=FAKE_TABLE), \
             patch.object(svc, "_load_agent", return_value=AGENT_1):
            svc._sb.table.return_value.select.return_value.eq.return_value.execute.return_value.count = 1
            svc._sb.table.return_value.upsert.return_value.execute.return_value.data = [
                {"id": "m1", "table_id": "table-1", "agent_id": "agent-1", "turn_order": 0}
            ]
            result = svc.add_member("table-1", "user-1", "agent-1", turn_order=0)
            assert result["agent_id"] == "agent-1"


# ─── Tests del debate ─────────────────────────────────────────────────────────

class TestStartDebate:
    def test_invalid_rounds_raises(self):
        svc = make_svc()
        with patch.object(svc, "get_table", return_value=FAKE_TABLE):
            with pytest.raises(ValueError, match="rondas"):
                svc.start_debate("table-1", "user-1", rounds=0)

    def test_already_running_raises(self):
        svc = make_svc()
        running = {**FAKE_TABLE, "status": "running"}
        with patch.object(svc, "get_table", return_value=running):
            with pytest.raises(ValueError, match="en curso"):
                svc.start_debate("table-1", "user-1", rounds=1)

    def test_already_done_raises(self):
        svc = make_svc()
        with patch.object(svc, "get_table", return_value=FAKE_TABLE_DONE):
            with pytest.raises(ValueError, match="concluido"):
                svc.start_debate("table-1", "user-1", rounds=1)

    def test_not_enough_agents_raises(self):
        svc = make_svc()
        with patch.object(svc, "get_table", return_value=FAKE_TABLE):
            # Solo 1 miembro
            svc._sb.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = [
                {"agent_id": "agent-1", "turn_order": 0}
            ]
            with patch.object(svc, "_load_agent", return_value=AGENT_1):
                with pytest.raises(ValueError, match=f"al menos {MIN_AGENTS}"):
                    svc.start_debate("table-1", "user-1", rounds=1)

    def test_debate_runs_correct_number_of_turns(self):
        svc = make_svc()
        with patch.object(svc, "get_table", return_value=FAKE_TABLE), \
             patch.object(svc, "_load_agent", side_effect=[AGENT_1, AGENT_2, AGENT_1, AGENT_2]):
            svc._sb.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = FAKE_MEMBERS
            svc._sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

            turns_created = []
            def mock_run_turn(agent_data, **kwargs):
                t = RoundTableTurn(
                    agent_id=agent_data["agent_id"], agent_name=agent_data["name"],
                    round_num=kwargs["round_num"], content="Respuesta de prueba.",
                    provider="groq", model="m", tokens_in=5, tokens_out=10, latency_ms=50.0,
                )
                turns_created.append(t)
                return t

            with patch.object(svc, "_run_agent_turn", side_effect=mock_run_turn), \
                 patch.object(svc, "_synthesize", return_value="Síntesis del debate."):
                result = svc.start_debate("table-1", "user-1", rounds=2)

        # 2 rondas × 2 agentes = 4 turnos
        assert len(turns_created) == 4
        assert result.synthesis == "Síntesis del debate."

    def test_inference_error_in_turn_does_not_crash_debate(self):
        """Si un agente falla, el debate continúa con un mensaje de error."""
        svc = make_svc()
        with patch.object(svc, "get_table", return_value=FAKE_TABLE), \
             patch.object(svc, "_load_agent", side_effect=[AGENT_1, AGENT_2]):
            svc._sb.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value.data = FAKE_MEMBERS
            svc._sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

            error_turn = RoundTableTurn(
                "agent-1", "DevOps", 1,
                "[DevOps no pudo responder: error del provider.]",
                "error", "error", 0, 0, 0.0,
            )
            ok_turn = RoundTableTurn(
                "agent-2", "Arquitecto", 1, "Mi respuesta.", "groq", "m", 5, 10, 50.0
            )

            with patch.object(svc, "_run_agent_turn", side_effect=[error_turn, ok_turn]), \
                 patch.object(svc, "_synthesize", return_value="Síntesis."):
                result = svc.start_debate("table-1", "user-1", rounds=1)

        assert len(result.turns) == 2
        assert "error" in result.turns[0].provider


class TestGetResult:
    def test_not_done_raises(self):
        svc = make_svc()
        with patch.object(svc, "get_table", return_value=FAKE_TABLE):
            with pytest.raises(ValueError, match="no ha concluido"):
                svc.get_result("table-1", "user-1")

    def test_done_returns_result(self):
        svc = make_svc()
        with patch.object(svc, "get_table", return_value=FAKE_TABLE_DONE):
            result = svc.get_result("table-1", "user-1")
        assert "synthesis" in result


# ─── Tests de Endpoints HTTP ──────────────────────────────────────────────────

class TestRoundTableEndpoints:

    def setup_method(self):
        _auth_override()

    def teardown_method(self):
        _clear_auth()

    def test_create_table_requires_auth(self):
        _clear_auth()
        resp = client.post("/platform/round-table", json={
            "name": "Mesa", "topic": "Tema de prueba extenso"
        })
        assert resp.status_code in (401, 403)

    def test_create_table_success(self):
        with patch("app.routers.round_table._rt_service.create_table", return_value=FAKE_TABLE):
            resp = client.post("/platform/round-table", json={
                "name": "Mesa de prueba",
                "topic": "¿Microservicios o monolito para una startup?",
            })
        assert resp.status_code == 201
        assert resp.json()["id"] == "table-1"

    def test_create_table_short_topic(self):
        resp = client.post("/platform/round-table", json={
            "name": "Mesa", "topic": "corto"
        })
        assert resp.status_code == 422

    def test_list_tables_success(self):
        with patch("app.routers.round_table._rt_service.list_tables", return_value=[FAKE_TABLE]):
            resp = client.get("/platform/round-table")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_get_table_not_found(self):
        with patch("app.routers.round_table._rt_service.get_table",
                   side_effect=ValueError("Mesa no encontrada o sin acceso.")):
            resp = client.get("/platform/round-table/bad-id")
        assert resp.status_code == 404

    def test_delete_table_success(self):
        with patch("app.routers.round_table._rt_service.delete_table", return_value=True):
            resp = client.delete("/platform/round-table/table-1")
        assert resp.status_code == 200
        assert "eliminada" in resp.json()["detail"]

    def test_add_member_success(self):
        with patch("app.routers.round_table._rt_service.add_member",
                   return_value={"id": "m1", "agent_id": "agent-1", "turn_order": 0}):
            resp = client.post("/platform/round-table/table-1/members", json={
                "agent_id": "agent-1", "turn_order": 0
            })
        assert resp.status_code == 201

    def test_add_member_max_agents(self):
        with patch("app.routers.round_table._rt_service.add_member",
                   side_effect=ValueError(f"Máximo {MAX_AGENTS} agentes por mesa.")):
            resp = client.post("/platform/round-table/table-1/members", json={
                "agent_id": "agent-7", "turn_order": 6
            })
        assert resp.status_code == 400

    def test_list_members_success(self):
        fake_members = [
            {"id": "m1", "agent_id": "agent-1", "turn_order": 0, "agent_name": "DevOps"},
            {"id": "m2", "agent_id": "agent-2", "turn_order": 1, "agent_name": "Arquitecto"},
        ]
        with patch("app.routers.round_table._rt_service.list_members", return_value=fake_members):
            resp = client.get("/platform/round-table/table-1/members")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

    def test_start_debate_success(self):
        fake_result = RoundTableResult(
            table_id="table-1", topic="Tema", turns=[],
            synthesis="Síntesis generada.", total_tokens=200, total_latency_ms=500.0,
        )
        with patch("app.routers.round_table._rt_service.start_debate", return_value=fake_result):
            resp = client.post("/platform/round-table/table-1/start", json={"rounds": 1})
        assert resp.status_code == 200
        assert resp.json()["synthesis"] == "Síntesis generada."

    def test_start_debate_invalid_rounds(self):
        resp = client.post("/platform/round-table/table-1/start", json={"rounds": 10})
        assert resp.status_code == 422

    def test_start_debate_table_not_found(self):
        with patch("app.routers.round_table._rt_service.start_debate",
                   side_effect=ValueError("Mesa no encontrada o sin acceso.")):
            resp = client.post("/platform/round-table/table-1/start", json={"rounds": 1})
        assert resp.status_code == 404

    def test_start_debate_already_done(self):
        with patch("app.routers.round_table._rt_service.start_debate",
                   side_effect=ValueError("El debate ya ha concluido.")):
            resp = client.post("/platform/round-table/table-1/start", json={"rounds": 1})
        assert resp.status_code == 400

    def test_get_result_success(self):
        fake_result_dict = {"synthesis": "Síntesis.", "turns": [], "total_tokens": 100}
        with patch("app.routers.round_table._rt_service.get_result", return_value=fake_result_dict):
            resp = client.get("/platform/round-table/table-1/result")
        assert resp.status_code == 200
        assert resp.json()["synthesis"] == "Síntesis."

    def test_get_result_not_done(self):
        with patch("app.routers.round_table._rt_service.get_result",
                   side_effect=ValueError("El debate no ha concluido (estado: running).")):
            resp = client.get("/platform/round-table/table-1/result")
        assert resp.status_code == 400

    def test_remove_member_success(self):
        with patch("app.routers.round_table._rt_service.remove_member", return_value=True):
            resp = client.delete("/platform/round-table/table-1/members/agent-1")
        assert resp.status_code == 200
