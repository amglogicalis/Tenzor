from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app
from app.models import ChatCompletionResponse, ChatCompletionResponseChoice, ChatCompletionResponseUsage, Message

client = TestClient(app)

def test_root_endpoint():
    """Prueba que el endpoint raíz responda correctamente con el HTML del frontend."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"].lower()
    assert "Tenzor" in response.text

def test_chat_completions_without_auth():
    """Prueba que el endpoint de chat requiera autenticación."""
    payload = {
        "model": "tenzor-dev",
        "messages": [{"role": "user", "content": "Hola"}]
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 401
    assert "detail" in response.json()

@patch("app.services.key_service.KeyService.validate_key")
def test_chat_completions_invalid_auth(mock_validate):
    """Prueba que rechace una API Key inválida mockeando la base de datos."""
    mock_validate.side_effect = ValueError("API Key no registrada.")
    payload = {
        "model": "tenzor-dev",
        "messages": [{"role": "user", "content": "Hola"}]
    }
    headers = {"Authorization": "Bearer clave-invalida"}
    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert response.status_code == 401
    assert "key" in response.json()["detail"].lower()

@patch("app.services.key_service.KeyService.validate_key")
@patch("app.services.ai_service.AIService.generate_chat_completion")
def test_chat_completions_success(mock_generate, mock_validate):
    """Prueba el flujo exitoso de chat mockeando la autenticación y la llamada a la IA."""
    # Configurar el mock de autenticación
    mock_validate.return_value = {
        "valid": True,
        "owner_name": "Test User",
        "rate_limit": 100,
        "requests_today": 0,
        "dev_mode": True
    }

    # Configurar el mock de generación de la IA
    mock_generate.return_value = ChatCompletionResponse(
        id="test-123",
        created=1700000000,
        model="tenzor-dev (mock)",
        choices=[
            ChatCompletionResponseChoice(
                index=0,
                message=Message(role="assistant", content="Respuesta simulada sobre programación."),
                finish_reason="stop"
            )
        ],
        usage=ChatCompletionResponseUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20)
    )

    payload = {
        "model": "tenzor-dev",
        "messages": [{"role": "user", "content": "¿Cómo hago un bucle en Python?"}]
    }
    headers = {"Authorization": "Bearer tenzor-mock-dev-key"}
    
    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test-123"
    assert data["choices"][0]["message"]["content"] == "Respuesta simulada sobre programación."
    assert mock_generate.called
    assert mock_validate.called

@patch("app.services.key_service.KeyService.validate_key")
@patch("app.services.ai_service.AIService.generate_chat_completion")
def test_chat_completions_with_images_success(mock_generate, mock_validate):
    """Prueba que el endpoint de chat admita imágenes en la petición."""
    mock_validate.return_value = {
        "valid": True,
        "owner_name": "Test User",
        "rate_limit": 100,
        "requests_today": 0,
        "dev_mode": True
    }
    
    mock_generate.return_value = ChatCompletionResponse(
        id="test-img-123",
        created=1700000000,
        model="tenzor-dev (mock)",
        choices=[
            ChatCompletionResponseChoice(
                index=0,
                message=Message(role="assistant", content="Veo la imagen correctamente."),
                finish_reason="stop"
            )
        ],
        usage=ChatCompletionResponseUsage(prompt_tokens=10, completion_tokens=10, total_tokens=20)
    )

    payload = {
        "model": "tenzor-dev",
        "messages": [
            {
                "role": "user",
                "content": "¿Qué es esta imagen?",
                "images": ["data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="]
            }
        ]
    }
    headers = {"Authorization": "Bearer tenzor-mock-dev-key"}
    
    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test-img-123"
    assert data["choices"][0]["message"]["content"] == "Veo la imagen correctamente."
    assert mock_generate.called
    assert mock_validate.called

@patch("app.services.key_service.KeyService.validate_key")
def test_chat_completions_expired_key(mock_validate):
    """Prueba que el chat rechace una API Key caducada con código 401."""
    mock_validate.side_effect = ValueError("API Key caducada y eliminada.")
    payload = {
        "model": "tenzor-dev",
        "messages": [{"role": "user", "content": "Hola"}]
    }
    headers = {"Authorization": "Bearer clave-expirada"}
    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert response.status_code == 401
    assert "caducada" in response.json()["detail"].lower()

@patch("app.services.key_service.KeyService.validate_key")
def test_chat_completions_custom_model_forbidden(mock_validate):
    """Prueba que el chat rechace una petición al modelo custom si la key no tiene permiso (403)."""
    mock_validate.return_value = {
        "valid": True,
        "owner_name": "Standard User",
        "rate_limit": 100,
        "requests_today": 0,
        "allow_custom_model": False,
        "dev_mode": False
    }
    payload = {
        "model": "tenz-1-meteor",
        "messages": [{"role": "user", "content": "Hola"}]
    }
    headers = {"Authorization": "Bearer clave-sin-permiso-custom"}
    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert response.status_code == 403
    assert "permisos" in response.json()["detail"].lower()

@patch("app.services.key_service.KeyService.validate_key")
def test_chat_completions_custom_model_success(mock_validate):
    """Prueba que el chat procese con éxito una petición al modelo custom a través de Ollama mockeando HTTP."""
    mock_validate.return_value = {
        "valid": True,
        "owner_name": "VIP User",
        "rate_limit": 100,
        "requests_today": 0,
        "allow_custom_model": True,
        "dev_mode": False
    }
    
    import httpx
    original_post = httpx.Client.post
    post_calls = []

    def mock_post_fn(self, url, *args, **kwargs):
        post_calls.append(url)
        if "localhost" in str(url) or "127.0.0.1" in str(url):
            class MockResponse:
                status_code = 200
                def json(self):
                    return {
                        "id": "chatcmpl-mock",
                        "created": 1700000000,
                        "choices": [
                            {
                                "index": 0,
                                "message": {"role": "assistant", "content": "Hola, soy el modelo meteor personalizado."},
                                "finish_reason": "stop"
                            }
                        ],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
                    }
            return MockResponse()
        return original_post(self, url, *args, **kwargs)

    payload = {
        "model": "tenz-1-meteor",
        "messages": [{"role": "user", "content": "Hola, meteor"}]
    }
    headers = {"Authorization": "Bearer clave-con-permiso-custom"}
    
    with patch("httpx.Client.post", new=mock_post_fn):
        response = client.post("/v1/chat/completions", json=payload, headers=headers)
        
    assert response.status_code == 200
    data = response.json()
    assert "meteor" in data["choices"][0]["message"]["content"].lower()
    assert len(post_calls) > 0
    assert any("localhost" in str(u) or "127.0.0.1" in str(u) for u in post_calls)
    assert mock_validate.called




