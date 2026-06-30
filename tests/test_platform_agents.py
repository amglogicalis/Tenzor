"""
test_platform_agents.py
Tests de la Fase 2: CRUD de agentes personalizados y versionado.
Usa mocks de Supabase para correr sin conexión real.
"""
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# ─── Fixtures base ────────────────────────────────────────────────────────────

USER_ID = "user-test-123"
AGENT_ID = "agent-test-456"
VERSION_ID = "version-test-789"
VALID_TOKEN = "Bearer valid-platform-token"

MOCK_VERSION = {
    "id": VERSION_ID,
    "agent_id": AGENT_ID,
    "version": 1,
    "system_instructions": "Eres un experto en Python y arquitectura de software.",
    "behavior_examples": [],
    "style_rules": {},
    "domain_constraints": {},
    "retrieval_profile": {},
    "created_at": "2026-06-26T10:00:00Z",
}

MOCK_AGENT = {
    "id": AGENT_ID,
    "user_id": USER_ID,
    "name": "Python Expert",
    "description": "Agente experto en Python",
    "category": "dev",
    "base_tier": "balanced",
    "is_public": False,
    "level": 1,
    "experience": 0,
    "current_version_id": VERSION_ID,
    "current_version": MOCK_VERSION,
    "deleted_at": None,
    "created_at": "2026-06-26T10:00:00Z",
    "updated_at": "2026-06-26T10:00:00Z",
}

CREATE_PAYLOAD = {
    "name": "Python Expert",
    "description": "Agente experto en Python",
    "category": "dev",
    "base_tier": "balanced",
    "system_instructions": "Eres un experto en Python y arquitectura de software con 15 años de experiencia.",
    "is_public": False,
}


def make_auth_mock():
    """Mock para verify_token del middleware de plataforma."""
    mock = MagicMock()
    mock.auth.get_user.return_value = MagicMock(
        user=MagicMock(id=USER_ID, email="test@example.com")
    )
    return mock


def patch_auth_and_agent(agent_mock_sb):
    """Helper para parchear tanto auth como agent service simultáneamente."""
    return (
        patch("app.services.platform_auth_service.platform_auth_service.supabase", make_auth_mock()),
        patch("app.services.agent_service.agent_service.supabase", agent_mock_sb),
    )


# ─── Tests de creación ────────────────────────────────────────────────────────

class TestCreateAgent:
    def _build_create_mock(self, count=0):
        sb = MagicMock()

        def table_side_effect(table_name):
            t = MagicMock()
            if table_name == "custom_agents":
                # count query: select.eq.is_.execute
                count_chain = MagicMock()
                count_chain.execute.return_value = MagicMock(count=count)
                t.select.return_value.eq.return_value.is_.return_value = count_chain
                # insert agente
                t.insert.return_value.execute.return_value = MagicMock(data=[MOCK_AGENT])
                # update current_version_id
                t.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[MOCK_AGENT])
            elif table_name == "agent_versions":
                # insert versión
                t.insert.return_value.execute.return_value = MagicMock(data=[MOCK_VERSION])
                # get version by id (single)
                t.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=MOCK_VERSION)
            return t

        sb.table.side_effect = table_side_effect
        return sb

    def test_create_agent_success(self):
        sb_agent = self._build_create_mock(count=0)
        auth_sb = make_auth_mock()
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", auth_sb), \
             patch("app.services.agent_service.agent_service.supabase", sb_agent):
            resp = client.post(
                "/platform/agents",
                json=CREATE_PAYLOAD,
                headers={"Authorization": VALID_TOKEN},
            )
        assert resp.status_code == 201

    def test_create_agent_requires_auth(self):
        resp = client.post("/platform/agents", json=CREATE_PAYLOAD)
        assert resp.status_code == 401

    def test_create_agent_invalid_category(self):
        auth_sb = make_auth_mock()
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", auth_sb):
            resp = client.post(
                "/platform/agents",
                json={**CREATE_PAYLOAD, "category": "cocina"},
                headers={"Authorization": VALID_TOKEN},
            )
        assert resp.status_code == 422

    def test_create_agent_short_instructions(self):
        auth_sb = make_auth_mock()
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", auth_sb):
            resp = client.post(
                "/platform/agents",
                json={**CREATE_PAYLOAD, "system_instructions": "Corto"},
                headers={"Authorization": VALID_TOKEN},
            )
        assert resp.status_code == 422

    def test_create_agent_limit_reached(self):
        # Tras remover la restricción de agentes máximos, crear un agente con count>=10 es exitoso (201)
        sb_agent = self._build_create_mock(count=10)  
        auth_sb = make_auth_mock()
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", auth_sb), \
             patch("app.services.agent_service.agent_service.supabase", sb_agent):
            resp = client.post(
                "/platform/agents",
                json=CREATE_PAYLOAD,
                headers={"Authorization": VALID_TOKEN},
            )
        assert resp.status_code == 201


# ─── Tests de listado ─────────────────────────────────────────────────────────

class TestListAgents:
    def _build_list_mock(self):
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.is_.return_value.order.return_value.execute.return_value = MagicMock(data=[MOCK_AGENT])
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=MOCK_VERSION)
        return sb

    def test_list_my_agents_requires_auth(self):
        resp = client.get("/platform/agents")
        assert resp.status_code == 401

    def test_list_my_agents_success(self):
        auth_sb = make_auth_mock()
        sb_agent = self._build_list_mock()
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", auth_sb), \
             patch("app.services.agent_service.agent_service.supabase", sb_agent):
            resp = client.get("/platform/agents", headers={"Authorization": VALID_TOKEN})
        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        assert "total" in data

    def test_library_no_auth_required(self):
        sb_agent = MagicMock()

        def table_side_effect(table_name):
            t = MagicMock()
            if table_name == "custom_agents":
                # list_public_agents query chain
                t.select.return_value.eq.return_value.is_.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
                    data=[{**MOCK_AGENT, "is_public": True}]
                )
            elif table_name == "agent_versions":
                t.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=MOCK_VERSION)
            return t

        sb_agent.table.side_effect = table_side_effect
        with patch("app.services.agent_service.agent_service.supabase", sb_agent):
            resp = client.get("/platform/agents/library")
        assert resp.status_code == 200


# ─── Tests de obtener agente ──────────────────────────────────────────────────

class TestGetAgent:
    def _build_get_mock(self, owner_id=USER_ID, is_public=False):
        sb = MagicMock()
        agent_data = {**MOCK_AGENT, "user_id": owner_id, "is_public": is_public}
        sb.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = MagicMock(data=[agent_data])
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=MOCK_VERSION)
        return sb

    def test_get_own_agent(self):
        auth_sb = make_auth_mock()
        sb_agent = self._build_get_mock(owner_id=USER_ID)
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", auth_sb), \
             patch("app.services.agent_service.agent_service.supabase", sb_agent):
            resp = client.get(f"/platform/agents/{AGENT_ID}", headers={"Authorization": VALID_TOKEN})
        assert resp.status_code == 200

    def test_get_other_private_agent_forbidden(self):
        auth_sb = make_auth_mock()
        sb_agent = self._build_get_mock(owner_id="other-user-id", is_public=False)
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", auth_sb), \
             patch("app.services.agent_service.agent_service.supabase", sb_agent):
            resp = client.get(f"/platform/agents/{AGENT_ID}", headers={"Authorization": VALID_TOKEN})
        assert resp.status_code == 403

    def test_get_public_agent_from_other_user(self):
        auth_sb = make_auth_mock()
        sb_agent = self._build_get_mock(owner_id="other-user-id", is_public=True)
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", auth_sb), \
             patch("app.services.agent_service.agent_service.supabase", sb_agent):
            resp = client.get(f"/platform/agents/{AGENT_ID}", headers={"Authorization": VALID_TOKEN})
        assert resp.status_code == 200


# ─── Tests de actualización ───────────────────────────────────────────────────

class TestUpdateAgent:
    def _build_update_mock(self):
        sb = MagicMock()
        # _assert_owner
        sb.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = MagicMock(data=[{"user_id": USER_ID}])
        # update
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[MOCK_AGENT])
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(data=MOCK_VERSION)
        return sb

    def test_update_agent_name(self):
        auth_sb = make_auth_mock()
        sb_agent = self._build_update_mock()
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", auth_sb), \
             patch("app.services.agent_service.agent_service.supabase", sb_agent):
            resp = client.patch(
                f"/platform/agents/{AGENT_ID}",
                json={"name": "Nuevo Nombre"},
                headers={"Authorization": VALID_TOKEN},
            )
        assert resp.status_code == 200

    def test_update_requires_auth(self):
        resp = client.patch(f"/platform/agents/{AGENT_ID}", json={"name": "Test"})
        assert resp.status_code == 401


# ─── Tests de borrado ─────────────────────────────────────────────────────────

class TestDeleteAgent:
    def _build_delete_mock(self):
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = MagicMock(data=[{"user_id": USER_ID}])
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        return sb

    def test_delete_agent_success(self):
        auth_sb = make_auth_mock()
        sb_agent = self._build_delete_mock()
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", auth_sb), \
             patch("app.services.agent_service.agent_service.supabase", sb_agent):
            resp = client.delete(f"/platform/agents/{AGENT_ID}", headers={"Authorization": VALID_TOKEN})
        assert resp.status_code == 204

    def test_delete_requires_auth(self):
        resp = client.delete(f"/platform/agents/{AGENT_ID}")
        assert resp.status_code == 401


# ─── Tests de versionado ──────────────────────────────────────────────────────

class TestVersioning:
    def _build_version_mock(self):
        sb = MagicMock()
        # _assert_owner
        sb.table.return_value.select.return_value.eq.return_value.is_.return_value.execute.return_value = MagicMock(data=[{"user_id": USER_ID}])
        # get last version number
        sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"version": 1}])
        # insert new version
        v2 = {**MOCK_VERSION, "version": 2, "id": "version-2-id"}
        sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[v2])
        # update current_version_id
        sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        return sb

    def test_create_new_version_success(self):
        auth_sb = make_auth_mock()
        sb_agent = self._build_version_mock()
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", auth_sb), \
             patch("app.services.agent_service.agent_service.supabase", sb_agent):
            resp = client.post(
                f"/platform/agents/{AGENT_ID}/versions",
                json={"system_instructions": "Nueva versión con instrucciones mucho más completas y detalladas para el agente."},
                headers={"Authorization": VALID_TOKEN},
            )
        assert resp.status_code == 201
        assert resp.json()["version"] == 2

    def test_new_version_requires_auth(self):
        resp = client.post(
            f"/platform/agents/{AGENT_ID}/versions",
            json={"system_instructions": "test de instrucciones muy largas para superar el minimo"},
        )
        assert resp.status_code == 401
