from fastapi.testclient import TestClient
from unittest.mock import patch
from app.main import app
from app.models import ChatCompletionResponse, ChatCompletionResponseChoice, ChatCompletionResponseUsage, Message
from app import config

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
        "model": config.CUSTOM_MODEL_NAME,
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
                                "message": {"role": "assistant", "content": "Hola, soy el modelo nova personalizado."},
                                "finish_reason": "stop"
                            }
                        ],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}
                    }
            return MockResponse()
        return original_post(self, url, *args, **kwargs)

    payload = {
        "model": config.CUSTOM_MODEL_NAME,
        "messages": [{"role": "user", "content": "Hola, nova"}]
    }
    headers = {"Authorization": "Bearer clave-con-permiso-custom"}
    
    # Patch configs to isolate this test from .env values
    old_provider = config.CUSTOM_MODEL_PROVIDER
    old_backing = config.CUSTOM_MODEL_BACKING_NAME
    config.CUSTOM_MODEL_PROVIDER = "ollama"
    config.CUSTOM_MODEL_BACKING_NAME = "qwen2.5-coder:7b"

    try:
        with patch("httpx.Client.post", new=mock_post_fn):
            response = client.post("/v1/chat/completions", json=payload, headers=headers)
            
        assert response.status_code == 200
        data = response.json()
        assert "nova" in data["choices"][0]["message"]["content"].lower()
        assert len(post_calls) > 0
        assert any("localhost" in str(u) or "127.0.0.1" in str(u) for u in post_calls)
        assert mock_validate.called
    finally:
        config.CUSTOM_MODEL_PROVIDER = old_provider
        config.CUSTOM_MODEL_BACKING_NAME = old_backing


@patch("app.services.key_service.KeyService.validate_key")
@patch("google.oauth2.service_account.Credentials.from_service_account_file")
@patch("google.auth.transport.requests.Request")
def test_chat_completions_vertexai_success(mock_request, mock_from_file, mock_validate):
    """Prueba que el chat procese con éxito una petición al modelo custom a través de Vertex AI mockeando OAuth2 e HTTP."""
    mock_validate.return_value = {
        "valid": True,
        "owner_name": "VIP User",
        "rate_limit": 100,
        "requests_today": 0,
        "allow_custom_model": True,
        "dev_mode": False
    }

    # Mock GCP credentials & token refresh
    class MockCreds:
        token = "mock-gcp-token"
        def refresh(self, request):
            pass
    mock_from_file.return_value = MockCreds()

    # Intercept Vertex AI call
    import httpx
    original_post = httpx.Client.post
    post_calls = []

    def mock_post_fn(self, url, *args, **kwargs):
        post_calls.append(url)
        if "aiplatform.googleapis.com" in str(url):
            class MockResponse:
                status_code = 200
                def json(self):
                    return {
                        "candidates": [
                          {
                            "content": {
                              "role": "model",
                              "parts": [
                                {
                                  "text": "Hola, soy el modelo de Vertex AI."
                                }
                              ]
                            },
                            "finishReason": "STOP"
                          }
                        ],
                        "usageMetadata": {
                          "promptTokenCount": 15,
                          "candidatesTokenCount": 20
                        },
                        "responseId": "vertex-mock-id"
                    }
            return MockResponse()
        return original_post(self, url, *args, **kwargs)

    # Patch configs
    old_provider = config.CUSTOM_MODEL_PROVIDER
    old_backing = config.CUSTOM_MODEL_BACKING_NAME
    config.CUSTOM_MODEL_PROVIDER = "vertexai"
    config.CUSTOM_MODEL_BACKING_NAME = "projects/753320073574/locations/us-central1/models/7952891298761932800"

    payload = {
        "model": config.CUSTOM_MODEL_NAME,
        "messages": [{"role": "user", "content": "Hola, nova"}]
    }
    headers = {"Authorization": "Bearer clave-con-permiso-custom"}

    try:
        with patch("httpx.Client.post", new=mock_post_fn):
            response = client.post("/v1/chat/completions", json=payload, headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "vertex" in data["choices"][0]["message"]["content"].lower()
        assert len(post_calls) > 0
        assert any("aiplatform.googleapis.com" in str(u) for u in post_calls)
        assert mock_validate.called
    finally:
        # Restore config
        config.CUSTOM_MODEL_PROVIDER = old_provider
        config.CUSTOM_MODEL_BACKING_NAME = old_backing


@patch("app.services.key_service.KeyService.validate_key")
@patch("google.oauth2.service_account.Credentials.from_service_account_file")
@patch("google.auth.transport.requests.Request")
def test_chat_completions_custom_vertex_success(mock_request, mock_from_file, mock_validate):
    """Prueba que el chat procese con éxito una petición al modelo custom a través de un Custom Vertex Endpoint."""
    mock_validate.return_value = {
        "valid": True,
        "owner_name": "VIP User",
        "rate_limit": 100,
        "requests_today": 0,
        "allow_custom_model": True,
        "dev_mode": False
    }

    # Mock GCP credentials & token refresh
    class MockCreds:
        token = "mock-gcp-token"
        def refresh(self, request):
            pass
    mock_from_file.return_value = MockCreds()

    # Intercept Vertex AI call
    import httpx
    original_post = httpx.Client.post
    post_calls = []

    def mock_post_fn(self, url, *args, **kwargs):
        post_calls.append(url)
        if "aiplatform.googleapis.com" in str(url):
            class MockResponse:
                status_code = 200
                def json(self):
                    return {
                        "predictions": [
                          "<|im_start|>assistant\nHola, soy el modelo personalizado Qwen en Vertex AI.<|im_end|>"
                        ]
                    }
            return MockResponse()
        return original_post(self, url, *args, **kwargs)

    # Patch configs
    old_provider = config.CUSTOM_MODEL_PROVIDER
    old_backing = config.CUSTOM_MODEL_BACKING_NAME
    config.CUSTOM_MODEL_PROVIDER = "vertexai"
    config.CUSTOM_MODEL_BACKING_NAME = "projects/753320073574/locations/us-central1/endpoints/7282699379213860864"

    payload = {
        "model": config.CUSTOM_MODEL_NAME,
        "messages": [{"role": "user", "content": "Hola, nova"}]
    }
    headers = {"Authorization": "Bearer clave-con-permiso-custom"}

    try:
        with patch("httpx.Client.post", new=mock_post_fn):
            response = client.post("/v1/chat/completions", json=payload, headers=headers)
        
        assert response.status_code == 200
        data = response.json()
        assert "qwen" in data["choices"][0]["message"]["content"].lower()
        assert len(post_calls) > 0
        assert any("aiplatform.googleapis.com" in str(u) for u in post_calls)
        assert mock_validate.called
    finally:
        config.CUSTOM_MODEL_PROVIDER = old_provider
        config.CUSTOM_MODEL_BACKING_NAME = old_backing


def test_wake_model_uses_configurable_vertex_resources():
    """Prueba que Wake-on-Demand use los recursos Vertex configurables, no IDs hardcodeados."""
    from app.routers.chat import ai_service
    import httpx

    old_endpoint_resource = config.VERTEX_ENDPOINT_RESOURCE
    old_model_resource = config.VERTEX_MODEL_RESOURCE
    old_display = config.VERTEX_DEPLOYED_MODEL_DISPLAY_NAME
    old_machine = config.VERTEX_MACHINE_TYPE
    old_accel_type = config.VERTEX_ACCELERATOR_TYPE
    old_accel_count = config.VERTEX_ACCELERATOR_COUNT
    old_deploy_timeout = config.VERTEX_DEPLOY_HTTP_TIMEOUT_SECONDS

    config.VERTEX_ENDPOINT_RESOURCE = "projects/p/locations/us-central1/endpoints/e-custom"
    config.VERTEX_MODEL_RESOURCE = "projects/p/locations/us-central1/models/m-custom@7"
    config.VERTEX_DEPLOYED_MODEL_DISPLAY_NAME = "nova-custom"
    config.VERTEX_MACHINE_TYPE = "g2-standard-24"
    config.VERTEX_ACCELERATOR_TYPE = "NVIDIA_L4"
    config.VERTEX_ACCELERATOR_COUNT = 2
    config.VERTEX_DEPLOY_HTTP_TIMEOUT_SECONDS = 7.0

    post_calls = []
    client_timeouts = []
    original_client_init = httpx.Client.__init__

    def mock_client_init(self, *args, **kwargs):
        client_timeouts.append(kwargs.get("timeout"))
        original_client_init(self, *args, **kwargs)

    def mock_post_fn(self, url, *args, **kwargs):
        post_calls.append((url, kwargs.get("json")))
        class MockResponse:
            status_code = 200
            def json(self):
                return {"name": "operations/deploy-123"}
        return MockResponse()

    try:
        with patch.object(ai_service, "get_model_status", return_value="sleep"), \
             patch.object(ai_service, "_vertex_headers", return_value={"Authorization": "Bearer test"}), \
             patch.object(ai_service, "_save_lifecycle_state") as mock_save_state, \
             patch("httpx.Client.__init__", new=mock_client_init), \
             patch("httpx.Client.post", new=mock_post_fn):
            result = ai_service.wake_model()

        assert result["status"] == "waking"
        assert result["operation"] == "operations/deploy-123"
        assert post_calls
        assert 7.0 in client_timeouts
        url, payload = post_calls[0]
        assert "endpoints/e-custom:deployModel" in url
        assert payload["deployedModel"]["model"] == "projects/p/locations/us-central1/models/m-custom@7"
        assert payload["deployedModel"]["displayName"] == "nova-custom"
        assert payload["deployedModel"]["dedicatedResources"]["machineSpec"]["machineType"] == "g2-standard-24"
        assert payload["deployedModel"]["dedicatedResources"]["machineSpec"]["acceleratorType"] == "NVIDIA_L4"
        assert payload["deployedModel"]["dedicatedResources"]["machineSpec"]["acceleratorCount"] == 2
        mock_save_state.assert_called_with(
            "waking",
            operation_name="operations/deploy-123",
            operation_kind="deploy",
            message="DESPERTANDO",
            started_at=ai_service.current_op_started_at,
        )
    finally:
        config.VERTEX_ENDPOINT_RESOURCE = old_endpoint_resource
        config.VERTEX_MODEL_RESOURCE = old_model_resource
        config.VERTEX_DEPLOYED_MODEL_DISPLAY_NAME = old_display
        config.VERTEX_MACHINE_TYPE = old_machine
        config.VERTEX_ACCELERATOR_TYPE = old_accel_type
        config.VERTEX_ACCELERATOR_COUNT = old_accel_count
        config.VERTEX_DEPLOY_HTTP_TIMEOUT_SECONDS = old_deploy_timeout
        ai_service.current_op_name = None
        ai_service.current_op_kind = None
        ai_service.current_op_error = None
        ai_service.current_op_started_at = None


def test_sleep_model_returns_sleeping_while_undeploy_operation_runs():
    """Prueba que Sleep-on-Demand exponga estado intermedio de apagado."""
    from app.routers.chat import ai_service
    import httpx

    old_endpoint_resource = config.VERTEX_ENDPOINT_RESOURCE
    config.VERTEX_ENDPOINT_RESOURCE = "projects/p/locations/us-central1/endpoints/e-custom"

    def mock_get_fn(self, url, *args, **kwargs):
        class MockResponse:
            status_code = 200
            def json(self):
                return {"deployedModels": [{"id": "deployed-1"}]}
        return MockResponse()

    def mock_post_fn(self, url, *args, **kwargs):
        class MockResponse:
            status_code = 200
            def json(self):
                return {"name": "operations/undeploy-123"}
        return MockResponse()

    try:
        with patch.object(ai_service, "_vertex_headers", return_value={"Authorization": "Bearer test"}), \
             patch("httpx.Client.get", new=mock_get_fn), \
             patch("httpx.Client.post", new=mock_post_fn):
            result = ai_service.sleep_model()

        assert result["status"] == "sleeping"
        assert result["operation"] == "operations/undeploy-123"
        assert ai_service.current_op_kind == "undeploy"
    finally:
        config.VERTEX_ENDPOINT_RESOURCE = old_endpoint_resource
        ai_service.current_op_name = None
        ai_service.current_op_kind = None
        ai_service.current_op_error = None
        ai_service.current_op_started_at = None


def test_lifecycle_operation_timeout_marks_error():
    """Evita que un deploy atascado quede indefinidamente en estado waking."""
    from app.routers.chat import ai_service
    from datetime import datetime, timedelta, timezone

    old_timeout = config.VERTEX_LIFECYCLE_OPERATION_TIMEOUT_SECONDS
    config.VERTEX_LIFECYCLE_OPERATION_TIMEOUT_SECONDS = 2700
    ai_service.current_op_name = "operations/deploy-stuck"
    ai_service.current_op_kind = "deploy"
    ai_service.current_op_error = None
    ai_service.current_op_started_at = (datetime.now(timezone.utc) - timedelta(seconds=2701)).isoformat()

    try:
        with patch.object(ai_service, "_vertex_headers", return_value={"Authorization": "Bearer test"}), \
             patch.object(ai_service, "_get_endpoint_deployed_models", return_value=[]), \
             patch.object(ai_service, "_save_lifecycle_state") as mock_save_state:
            status = ai_service.get_model_status()

        assert status == "error"
        assert "2700" in ai_service.current_op_error
        mock_save_state.assert_called()
        assert mock_save_state.call_args.args[0] == "error"
    finally:
        config.VERTEX_LIFECYCLE_OPERATION_TIMEOUT_SECONDS = old_timeout
        ai_service.current_op_name = None
        ai_service.current_op_kind = None
        ai_service.current_op_error = None
        ai_service.current_op_started_at = None


def test_status_hydrates_running_operation_from_lifecycle_store():
    """Un reinicio del backend no debe perder la operacion wake/sleep en curso."""
    from app.routers.chat import ai_service
    from datetime import datetime, timezone

    ai_service.current_op_name = None
    ai_service.current_op_kind = None
    ai_service.current_op_error = None
    ai_service.current_op_started_at = None
    started_at = datetime.now(timezone.utc).isoformat()

    try:
        with patch.object(ai_service, "_load_lifecycle_state", return_value={
            "status": "waking",
            "operation_name": "operations/deploy-restored",
            "operation_kind": "deploy",
            "operation_started_at": started_at,
        }), \
             patch.object(ai_service, "_vertex_headers", return_value={"Authorization": "Bearer test"}), \
             patch.object(ai_service, "_get_endpoint_deployed_models", return_value=[]), \
             patch("httpx.Client.get") as mock_get, \
             patch.object(ai_service, "_save_lifecycle_state"):
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {"done": False}
            status = ai_service.get_model_status()

        assert status == "waking"
        assert ai_service.current_op_name == "operations/deploy-restored"
        assert ai_service.current_op_kind == "deploy"
    finally:
        ai_service.current_op_name = None
        ai_service.current_op_kind = None
        ai_service.current_op_error = None
        ai_service.current_op_started_at = None


def test_model_garden_resource_does_not_append_version():
    """Los modelos mg-* de Model Garden se despliegan por ID directo, sin sufijo @version."""
    from app.routers.chat import ai_service

    old_model_resource = config.VERTEX_MODEL_RESOURCE
    old_model_id = config.VERTEX_MODEL_ID
    old_model_version = config.VERTEX_MODEL_VERSION

    config.VERTEX_MODEL_RESOURCE = ""
    config.VERTEX_MODEL_ID = "mg-custom-1782292431"
    config.VERTEX_MODEL_VERSION = "1"

    try:
        assert ai_service._vertex_model_resource() == "projects/tenzorai/locations/us-central1/models/mg-custom-1782292431"
    finally:
        config.VERTEX_MODEL_RESOURCE = old_model_resource
        config.VERTEX_MODEL_ID = old_model_id
        config.VERTEX_MODEL_VERSION = old_model_version


@patch("google.oauth2.service_account.Credentials.from_service_account_file")
@patch("google.auth.transport.requests.Request")
def test_custom_vertex_endpoint_uses_model_garden_messages_payload(mock_request, mock_from_file):
    """La inferencia contra el endpoint mg-* debe usar instances[].messages como el script de deploy."""
    from app.routers.chat import ai_service
    import httpx

    class MockCreds:
        token = "mock-gcp-token"
        def refresh(self, request):
            pass
    mock_from_file.return_value = MockCreds()

    post_payloads = []

    def mock_post_fn(self, url, *args, **kwargs):
        post_payloads.append(kwargs.get("json"))
        class MockResponse:
            status_code = 200
            def json(self):
                return {"predictions": [{"content": "Respuesta desde Model Garden."}]}
        return MockResponse()

    old_backing = config.CUSTOM_MODEL_BACKING_NAME
    config.CUSTOM_MODEL_BACKING_NAME = "projects/tenzorai/locations/us-central1/endpoints/mg-endpoint-1eae4fb8-4883-4bfc-8355-08cdb1ee1bb9"

    try:
        with patch("httpx.Client.post", new=mock_post_fn):
            result = ai_service._generate_custom_vertex_completion(
                messages=[Message(role="user", content="Hola")],
                system_prompt="Sistema",
                max_tokens=128,
                temperature=0.2,
            )

        assert result.choices[0].message.content == "Respuesta desde Model Garden."
        payload = post_payloads[0]
        assert "prompt" not in payload["instances"][0]
        assert payload["instances"][0]["max_tokens"] == 128
        assert payload["instances"][0]["temperature"] == 0.2
        assert payload["instances"][0]["messages"] == [
            {"role": "system", "content": "Sistema"},
            {"role": "user", "content": "Hola"},
        ]
    finally:
        config.CUSTOM_MODEL_BACKING_NAME = old_backing


