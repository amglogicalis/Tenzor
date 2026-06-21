from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app
from app.models import ChatCompletionResponse, ChatCompletionResponseChoice, ChatCompletionResponseUsage, Message

client = TestClient(app)

def test_root_endpoint():
    """Prueba que el endpoint raíz responda correctamente."""
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "online"
    assert response.json()["name"] == "Tenzor API"

def test_chat_completions_without_auth():
    """Prueba que el endpoint de chat requiera autenticación."""
    payload = {
        "model": "tenzor-dev",
        "messages": [{"role": "user", "content": "Hola"}]
    }
    response = client.post("/v1/chat/completions", json=payload)
    assert response.status_code == 401
    assert "detail" in response.json()

def test_chat_completions_invalid_auth():
    """Prueba que rechace una API Key inválida."""
    payload = {
        "model": "tenzor-dev",
        "messages": [{"role": "user", "content": "Hola"}]
    }
    headers = {"Authorization": "Bearer clave-invalida"}
    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    assert response.status_code == 401
    assert "key" in response.json()["detail"].lower()

@patch("app.services.ai_service.AIService.generate_chat_completion")
def test_chat_completions_success(mock_generate):
    """Prueba el flujo exitoso de chat usando una key de desarrollo mockeando la llamada a la IA."""
    # Configurar el mock para evitar llamadas reales a las APIs de Groq/Gemini en los tests
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
    # En modo desarrollo local, cualquier key que empiece con "tenzor-" es válida
    headers = {"Authorization": "Bearer tenzor-mock-dev-key"}
    
    response = client.post("/v1/chat/completions", json=payload, headers=headers)
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "test-123"
    assert data["choices"][0]["message"]["content"] == "Respuesta simulada sobre programación."
    assert mock_generate.called
