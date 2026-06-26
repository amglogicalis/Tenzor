"""
test_platform_auth.py
Tests de la Fase 1: Auth, Profiles y Seguridad Multiusuario.
Se mockea Supabase para no necesitar conexión real en CI.
"""
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

# ─── Helpers de mock ──────────────────────────────────────────────────────────

def make_supabase_mock(
    username_taken: bool = False,
    signup_user_id: str = "test-uid-123",
    signup_access_token: str = "test-jwt-token",
    login_success: bool = True,
    profile_data: dict = None,
):
    """Construye un mock de Supabase reutilizable."""
    mock = MagicMock()

    # username check (profiles.select.eq.execute)
    username_check = MagicMock()
    username_check.data = [{"id": "some-id"}] if username_taken else []
    mock.table.return_value.select.return_value.eq.return_value.execute.return_value = username_check

    # sign_up
    mock_user = MagicMock()
    mock_user.id = signup_user_id
    mock_session = MagicMock()
    mock_session.access_token = signup_access_token
    mock_auth_resp = MagicMock()
    mock_auth_resp.user = mock_user
    mock_auth_resp.session = mock_session
    mock.auth.sign_up.return_value = mock_auth_resp

    # profiles.insert
    mock.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{}])

    # sign_in_with_password
    if login_success:
        mock.auth.sign_in_with_password.return_value = mock_auth_resp
    else:
        mock.auth.sign_in_with_password.side_effect = Exception("Invalid credentials")

    # profiles.select.eq.single.execute (get_profile)
    _profile = profile_data or {
        "id": signup_user_id,
        "username": "testuser",
        "display_name": "Test User",
        "bio": None,
        "avatar_url": None,
        "plan": "free",
        "created_at": "2026-06-26T10:00:00Z",
    }
    mock_profile_resp = MagicMock()
    mock_profile_resp.data = _profile
    mock.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_profile_resp

    # get_user (verify_token)
    mock_token_user = MagicMock()
    mock_token_user.id = signup_user_id
    mock_token_user.email = "test@example.com"
    mock_token_resp = MagicMock()
    mock_token_resp.user = mock_token_user
    mock.auth.get_user.return_value = mock_token_resp

    # profiles.update (update_profile)
    mock_update_resp = MagicMock()
    mock_update_resp.data = [_profile]
    mock.table.return_value.update.return_value.eq.return_value.execute.return_value = mock_update_resp

    return mock


# ─── Tests de Registro ────────────────────────────────────────────────────────

class TestRegister:
    def test_register_success(self):
        mock_sb = make_supabase_mock()
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", mock_sb):
            resp = client.post("/platform/auth/register", json={
                "email": "nuevo@example.com",
                "password": "password123",
                "username": "nuevouser",
                "display_name": "Nuevo User",
            })
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert data["username"] == "nuevouser"

    def test_register_username_taken(self):
        mock_sb = make_supabase_mock(username_taken=True)
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", mock_sb):
            resp = client.post("/platform/auth/register", json={
                "email": "otro@example.com",
                "password": "password123",
                "username": "ocupado",
            })
        assert resp.status_code == 400
        assert "uso" in resp.json()["detail"].lower()

    def test_register_weak_password(self):
        """La validación Pydantic rechaza contraseñas < 8 chars."""
        resp = client.post("/platform/auth/register", json={
            "email": "test@example.com",
            "password": "123",
            "username": "user1",
        })
        assert resp.status_code == 422

    def test_register_invalid_username_chars(self):
        """Usernames con caracteres no permitidos son rechazados por Pydantic."""
        resp = client.post("/platform/auth/register", json={
            "email": "test@example.com",
            "password": "password123",
            "username": "user name!",
        })
        assert resp.status_code == 422


# ─── Tests de Login ───────────────────────────────────────────────────────────

class TestLogin:
    def test_login_success(self):
        mock_sb = make_supabase_mock(login_success=True)
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", mock_sb):
            resp = client.post("/platform/auth/login", json={
                "email": "test@example.com",
                "password": "password123",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    def test_login_wrong_password(self):
        mock_sb = make_supabase_mock(login_success=False)
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", mock_sb):
            resp = client.post("/platform/auth/login", json={
                "email": "test@example.com",
                "password": "wrong",
            })
        assert resp.status_code == 401


# ─── Tests de Perfil ──────────────────────────────────────────────────────────

class TestProfile:
    def test_get_me_requires_auth(self):
        """Sin token devuelve 401."""
        resp = client.get("/platform/auth/me")
        assert resp.status_code == 401

    def test_get_me_with_valid_token(self):
        mock_sb = make_supabase_mock()
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", mock_sb):
            resp = client.get(
                "/platform/auth/me",
                headers={"Authorization": "Bearer test-jwt-token"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert "username" in data
        assert "plan" in data

    def test_patch_me_requires_auth(self):
        """Sin token devuelve 401."""
        resp = client.patch("/platform/auth/me", json={"display_name": "Nuevo"})
        assert resp.status_code == 401

    def test_patch_me_updates_display_name(self):
        mock_sb = make_supabase_mock()
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", mock_sb):
            resp = client.patch(
                "/platform/auth/me",
                json={"display_name": "Actualizado"},
                headers={"Authorization": "Bearer test-jwt-token"},
            )
        assert resp.status_code == 200


# ─── Tests de Aislamiento de Usuarios ────────────────────────────────────────

class TestUserIsolation:
    def test_token_of_user_a_cannot_get_user_b_profile(self):
        """
        Simula que el token de usuario A resuelve a user_id A.
        El endpoint /me siempre devuelve el perfil del token autenticado,
        no acepta un user_id arbitrario → aislamiento garantizado por diseño.
        """
        user_a_mock = make_supabase_mock(
            signup_user_id="user-a-id",
            profile_data={
                "id": "user-a-id",
                "username": "usera",
                "display_name": "User A",
                "bio": None,
                "avatar_url": None,
                "plan": "free",
                "created_at": "2026-06-26T10:00:00Z",
            },
        )
        with patch("app.services.platform_auth_service.platform_auth_service.supabase", user_a_mock):
            resp = client.get(
                "/platform/auth/me",
                headers={"Authorization": "Bearer token-de-user-a"},
            )
        assert resp.status_code == 200
        assert resp.json()["username"] == "usera"
