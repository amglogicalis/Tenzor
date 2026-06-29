"""
provider_router_service.py
Router de inferencias: orquesta providers, keys, fallbacks y Anti-429.

Flujo completo de una llamada:
  1. Determinar orden de providers según tier (fast/balanced/pro).
  2. Para cada provider en orden:
       a. Pedir la mejor key disponible al KeyPool.
       b. Si no hay key disponible → siguiente provider.
       c. Registrar uso (record_request).
       d. Llamar al provider con la key seleccionada.
       e. Éxito → registrar tokens, devolver resultado.
       f. 429 → record_429 + retry_after → continuar al siguiente provider/key.
       g. 503 → record_503 → continuar.
       h. 401/403 → record_auth_error → continuar.
       i. Timeout → record_timeout → continuar.
  3. Si todos los providers fallan → InferenceError con contexto completo.

El resultado siempre es un InferenceResult normalizado (formato OpenAI-compatible).

OpenRouter se llama vía httpx (API compatible con OpenAI).
Groq se llama con el SDK oficial.
Gemini se llama con google-generativeai.
"""
import re
import time
import json
import logging
import httpx
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from groq import Groq, RateLimitError as GroqRateLimitError, APIStatusError as GroqAPIStatusError
import google.generativeai as genai

from app import config
from app.services.cooldown_service import cooldown_service
from app.services.provider_key_pool_service import (
    key_pool, ProviderKey, PROVIDER_ORDER, PROVIDER_MODEL_MAP, PROVIDER_RPM_LIMITS
)

logger = logging.getLogger(__name__)


# ─── Estructuras de resultado ─────────────────────────────────────────────────

@dataclass
class InferenceResult:
    """Resultado normalizado de cualquier provider (formato OpenAI-like)."""
    content: str
    provider: str
    model: str
    key_id: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: float = 0.0
    finish_reason: str = "stop"


@dataclass
class ProviderAttempt:
    """Registro de un intento fallido para logging y diagnóstico."""
    provider: str
    key_id: str
    model: str
    error_code: int
    error_msg: str
    retry_after: Optional[float] = None


class InferenceError(Exception):
    """Se lanza cuando todos los providers y keys están agotados."""
    def __init__(self, message: str, attempts: List[ProviderAttempt]):
        super().__init__(message)
        self.attempts = attempts

    def to_dict(self) -> dict:
        return {
            "error": str(self),
            "attempts": [
                {
                    "provider": a.provider,
                    "model": a.model,
                    "error_code": a.error_code,
                    "error_msg": a.error_msg[:200],
                    "retry_after": a.retry_after,
                }
                for a in self.attempts
            ]
        }


# ─── Parseo de Retry-After ────────────────────────────────────────────────────

def _parse_retry_after(headers: Any) -> Optional[float]:
    """
    Extrae el valor Retry-After de los headers (si existe).
    Acepta formato en segundos (int/float) o en fecha HTTP.
    """
    if not headers:
        return None
    val = None
    for key in ("retry-after", "Retry-After", "x-ratelimit-reset-requests"):
        val = headers.get(key)
        if val is not None:
            break
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        # Intento de parsear como número extraído del string
        m = re.search(r"(\d+\.?\d*)", str(val))
        return float(m.group(1)) if m else None


# ─── Llamadas a cada provider ─────────────────────────────────────────────────

def _call_groq(
    messages: List[Dict[str, str]],
    model: str,
    api_key: str,
    temperature: float,
    max_tokens: Optional[int],
    system_prompt: Optional[str],
) -> InferenceResult:
    """Llama a Groq y devuelve un InferenceResult normalizado."""
    client = Groq(api_key=api_key)
    groq_messages = []
    if system_prompt:
        groq_messages.append({"role": "system", "content": system_prompt})
    groq_messages.extend(messages)

    t0 = time.monotonic()
    response = client.chat.completions.create(
        model=model,
        messages=groq_messages,
        temperature=temperature,
        max_tokens=max_tokens or 2048,
    )
    latency = (time.monotonic() - t0) * 1000

    choice = response.choices[0]
    usage = response.usage
    return InferenceResult(
        content=choice.message.content or "",
        provider="groq",
        model=model,
        key_id="",  # se rellena en el caller
        tokens_in=usage.prompt_tokens if usage else 0,
        tokens_out=usage.completion_tokens if usage else 0,
        latency_ms=round(latency, 1),
        finish_reason=choice.finish_reason or "stop",
    )


def _call_gemini(
    messages: List[Dict[str, str]],
    model: str,
    api_key: str,
    temperature: float,
    max_tokens: Optional[int],
    system_prompt: Optional[str],
) -> InferenceResult:
    """Llama a Gemini y devuelve un InferenceResult normalizado."""
    genai.configure(api_key=api_key, transport="rest")
    gemini_model = genai.GenerativeModel(
        model_name=model,
        system_instruction=system_prompt or "",
        generation_config=genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens or 2048,
        ),
    )
    # Convertir mensajes OpenAI → Gemini (alternado user/model)
    history = []
    last_user = None
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        if role == "user":
            if last_user is not None:
                history.append({"role": "model", "parts": ["..."]})
            history.append({"role": "user", "parts": [msg["content"]]})
            last_user = msg["content"]
        else:
            history.append({"role": "model", "parts": [msg["content"]]})
            last_user = None

    t0 = time.monotonic()
    if history and history[-1]["role"] == "user":
        user_msg = history[-1]["parts"][0]
        chat_history = history[:-1]
    elif history:
        user_msg = ""
        chat_history = history
    else:
        user_msg = ""
        chat_history = []

    chat = gemini_model.start_chat(history=chat_history)
    response = chat.send_message(user_msg)
    latency = (time.monotonic() - t0) * 1000

    content = response.text or ""
    usage_meta = getattr(response, "usage_metadata", None)
    tokens_in = getattr(usage_meta, "prompt_token_count", 0) or 0
    tokens_out = getattr(usage_meta, "candidates_token_count", 0) or 0

    return InferenceResult(
        content=content,
        provider="google",
        model=model,
        key_id="",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=round(latency, 1),
        finish_reason="stop",
    )


def _call_openrouter(
    messages: List[Dict[str, str]],
    model: str,
    api_key: str,
    temperature: float,
    max_tokens: Optional[int],
    system_prompt: Optional[str],
) -> InferenceResult:
    """
    Llama a OpenRouter via httpx (API compatible con OpenAI).
    Incluye los headers recomendados por OpenRouter para evitar filtros.
    """
    payload_messages = []
    if system_prompt:
        payload_messages.append({"role": "system", "content": system_prompt})
    payload_messages.extend(messages)

    payload = {
        "model": model,
        "messages": payload_messages,
        "temperature": temperature,
        "max_tokens": max_tokens or 2048,
        # Permite que OpenRouter seleccione el mejor provider disponible del modelo
        "route": "fallback",
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        # Headers recomendados por OpenRouter para identificar el uso
        "HTTP-Referer": "https://arzor.ai",
        "X-Title": "Arzor AIs Platform",
    }

    t0 = time.monotonic()
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{config.OPENROUTER_BASE_URL}/chat/completions",
            json=payload,
            headers=headers,
        )

    latency = (time.monotonic() - t0) * 1000

    if resp.status_code == 429:
        retry_after = _parse_retry_after(resp.headers)
        raise _RateLimitError(resp.status_code, resp.text, retry_after)
    if resp.status_code in (401, 403):
        raise _AuthError(resp.status_code, resp.text)
    if resp.status_code == 503:
        raise _ServiceError(resp.status_code, resp.text)
    if resp.status_code != 200:
        raise _ProviderError(resp.status_code, resp.text)

    data = resp.json()
    choice = data["choices"][0]
    usage = data.get("usage", {})

    return InferenceResult(
        content=choice["message"]["content"] or "",
        provider="openrouter",
        model=model,
        key_id="",
        tokens_in=usage.get("prompt_tokens", 0),
        tokens_out=usage.get("completion_tokens", 0),
        latency_ms=round(latency, 1),
        finish_reason=choice.get("finish_reason", "stop"),
    )


# ─── Configuración de proveedores genéricos OpenAI-compatibles ───────────────

OPENAI_COMPATIBLE_PROVIDERS = {
    "xai": "https://api.x.ai/v1",
    "perplexity": "https://api.perplexity.ai",
    "deepseek": "https://api.deepseek.com",
    "together": "https://api.together.xyz/v1",
    "fireworks": "https://api.fireworks.ai/inference/v1",
    "mistral": "https://api.mistral.ai/v1",
    "sambanova": "https://api.sambanova.ai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "zai": "https://api.z.ai/v1",
    "novita": "https://api.novita.ai/v3/openai",
    "scaleway": "https://api.scaleway.ai/v1"
}

LIGHTWEIGHT_MODELS = {
    "google": "gemini-2.0-flash-lite",
    "groq": "llama-3.1-8b-instant",
    "openrouter": "meta-llama/llama-3.1-8b-instruct:free",
    "cohere": "command-light",
    "anthropic": "claude-3-5-haiku-20241022",
    "nvidia": "meta/llama-3.1-8b-instruct",
    "cloudflare": "@cf/meta/llama-3-8b-instruct",
    "huggingface": "microsoft/Phi-3-mini-4k-instruct",
    "deepseek": "deepseek-chat",
    "xai": "grok-2",
    "perplexity": "sonar-reasoning",
    "mistral": "mistral-small-latest",
    "together": "meta-llama/Llama-3-8b-chat-hf",
    "fireworks": "accounts/fireworks/models/llama-v3-8b-instruct",
    "cerebras": "llama3-8b-8192",
    "sambanova": "Meta-Llama-3.1-8B-Instruct",
    "siliconflow": "deepseek-ai/DeepSeek-V3",
    "zai": "glm-4-flash",
    "novita": "meta-llama/llama-3.1-8b-instruct",
    "scaleway": "llama-3.1-8b-instruct",
    "watsonx": "ibm/granite-3-8b-instruct",
    "ollama": "llama3:latest",
}

def _call_cohere(
    messages: List[Dict[str, str]],
    model: str,
    api_key: str,
    temperature: float,
    max_tokens: Optional[int],
    system_prompt: Optional[str],
) -> InferenceResult:
    """Llama a Cohere v1 Chat API y devuelve un InferenceResult normalizado."""
    url = "https://api.cohere.com/v1/chat"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    chat_history = []
    user_message = ""
    
    # Procesar historial para Cohere
    for msg in messages[:-1]:
        role = "USER" if msg["role"] == "user" else "CHATBOT"
        chat_history.append({"role": role, "message": msg["content"]})
        
    if messages:
        user_message = messages[-1]["content"]
        
    payload = {
        "message": user_message,
        "chat_history": chat_history,
        "model": model,
        "temperature": temperature
    }
    if system_prompt:
        payload["preamble"] = system_prompt
    if max_tokens:
        payload["max_tokens"] = max_tokens
        
    t0 = time.monotonic()
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        
    latency = (time.monotonic() - t0) * 1000
    
    if resp.status_code == 429:
        retry_after = _parse_retry_after(resp.headers)
        raise _RateLimitError(resp.status_code, resp.text, retry_after)
    if resp.status_code in (401, 403):
        raise _AuthError(resp.status_code, resp.text)
    if resp.status_code != 200:
        raise _ProviderError(resp.status_code, resp.text)
        
    data = resp.json()
    content = data.get("text", "")
    meta = data.get("meta", {}).get("billed_tokens", {})
    tokens_in = meta.get("input_tokens", 0) or 0
    tokens_out = meta.get("output_tokens", 0) or 0
    
    return InferenceResult(
        content=content,
        provider="cohere",
        model=model,
        key_id="",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=round(latency, 1),
        finish_reason="stop",
    )


def _call_anthropic(
    messages: List[Dict[str, str]],
    model: str,
    api_key: str,
    temperature: float,
    max_tokens: Optional[int],
    system_prompt: Optional[str],
) -> InferenceResult:
    """Llama a la API de Messages de Anthropic Claude y devuelve un InferenceResult normalizado."""
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    # Conversión al formato estricto de mensajes de Anthropic (sólo user/assistant alternados)
    anthropic_messages = []
    last_role = None
    for msg in messages:
        role = "user" if msg["role"] == "user" else "assistant"
        if role == last_role:
            if anthropic_messages:
                anthropic_messages[-1]["content"] += "\n\n" + msg["content"]
            continue
        anthropic_messages.append({"role": role, "content": msg["content"]})
        last_role = role
        
    if anthropic_messages and anthropic_messages[0]["role"] != "user":
        anthropic_messages.insert(0, {"role": "user", "content": "Hola"})
        
    payload = {
        "model": model,
        "messages": anthropic_messages,
        "max_tokens": max_tokens or 2048,
        "temperature": temperature
    }
    if system_prompt:
        payload["system"] = system_prompt
        
    t0 = time.monotonic()
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        
    latency = (time.monotonic() - t0) * 1000
    
    if resp.status_code == 429:
        retry_after = _parse_retry_after(resp.headers)
        raise _RateLimitError(resp.status_code, resp.text, retry_after)
    if resp.status_code in (401, 403):
        raise _AuthError(resp.status_code, resp.text)
    if resp.status_code != 200:
        raise _ProviderError(resp.status_code, resp.text)
        
    data = resp.json()
    
    content = ""
    if data.get("content") and len(data["content"]) > 0:
        content = data["content"][0].get("text", "")
        
    usage = data.get("usage", {})
    tokens_in = usage.get("input_tokens", 0) or 0
    tokens_out = usage.get("output_tokens", 0) or 0
    
    return InferenceResult(
        content=content,
        provider="anthropic",
        model=model,
        key_id="",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=round(latency, 1),
        finish_reason=data.get("stop_reason") or "stop",
    )


def _call_huggingface(
    messages: List[Dict[str, str]],
    model: str,
    api_key: str,
    temperature: float,
    max_tokens: Optional[int],
    system_prompt: Optional[str],
) -> InferenceResult:
    """Llama a la Inference API de Hugging Face y devuelve un InferenceResult normalizado."""
    url = f"https://api-inference.huggingface.co/models/{model}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Compilar prompt a formato estructurado de chat
    prompt_parts = []
    if system_prompt:
        prompt_parts.append(f"<|system|>\n{system_prompt}\n")
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        prompt_parts.append(f"<|{role}|>\n{content}\n")
    prompt_parts.append("<|assistant|>\n")
    
    prompt = "".join(prompt_parts)
    
    payload = {
        "inputs": prompt,
        "parameters": {
            "temperature": max(0.1, min(1.0, temperature)),
            "max_new_tokens": max_tokens or 1024,
            "return_full_text": False
        }
    }
    
    t0 = time.monotonic()
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=payload)
    latency = (time.monotonic() - t0) * 1000
    
    if resp.status_code == 429:
        retry_after = _parse_retry_after(resp.headers)
        raise _RateLimitError(resp.status_code, resp.text, retry_after)
    if resp.status_code in (401, 403):
        raise _AuthError(resp.status_code, resp.text)
    if resp.status_code != 200:
        raise _ProviderError(resp.status_code, resp.text)
        
    data = resp.json()
    content = ""
    if isinstance(data, list) and len(data) > 0:
        content = data[0].get("generated_text", "")
    elif isinstance(data, dict):
        content = data.get("generated_text", "")
        
    if "<|assistant|>" in content:
        content = content.split("<|assistant|>")[-1].strip()
        
    tokens_in = len(prompt) // 4
    tokens_out = len(content) // 4
    
    return InferenceResult(
        content=content,
        provider="huggingface",
        model=model,
        key_id="",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=round(latency, 1),
        finish_reason="stop",
    )


def _call_watsonx(
    messages: List[Dict[str, str]],
    model: str,
    api_key: str,
    temperature: float,
    max_tokens: Optional[int],
    system_prompt: Optional[str],
) -> InferenceResult:
    """Llama a la API compatible con OpenAI de IBM Watsonx mediante un token de IAM generado al vuelo."""
    # Descomponer clave del usuario en APIKEY:PROJECT_ID:REGION
    parts = api_key.split(":")
    apikey = parts[0]
    project_id = parts[1] if len(parts) > 1 else ""
    region = parts[2] if len(parts) > 2 else "us-south"
    
    # 1. Generar token de IAM mediante IBM Cloud
    token_url = "https://iam.cloud.ibm.com/identity/token"
    token_headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }
    token_payload = f"grant_type=urn:ibm:params:oauth:grant-type:apikey&apikey={apikey}"
    
    t0 = time.monotonic()
    with httpx.Client(timeout=10.0) as client:
        token_resp = client.post(token_url, headers=token_headers, content=token_payload)
        
    if token_resp.status_code != 200:
        if token_resp.status_code in (400, 401, 403):
            raise _AuthError(token_resp.status_code, f"Error de autenticación de IBM IAM: {token_resp.text}")
        else:
            raise _ProviderError(token_resp.status_code, f"Error al generar token de IBM Cloud: {token_resp.text}")
            
    iam_token = token_resp.json().get("access_token")
    if not iam_token:
        raise _AuthError(401, "No se encontró access_token en la respuesta de IBM IAM")
        
    # 2. Realizar llamada a Watsonx Chat Completions
    url = f"https://{region}.ml.cloud.ibm.com/ml/v1/chat/completions?version=2024-03-14"
    headers = {
        "Authorization": f"Bearer {iam_token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    payload_messages = []
    if system_prompt:
        payload_messages.append({"role": "system", "content": system_prompt})
    payload_messages.extend(messages)
    
    payload = {
        "model": model,
        "messages": payload_messages,
        "temperature": temperature,
        "max_tokens": max_tokens or 2048,
    }
    if project_id:
        payload["project_id"] = project_id
        
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(url, headers=headers, json=payload)
        
    latency = (time.monotonic() - t0) * 1000
    
    if resp.status_code == 429:
        retry_after = _parse_retry_after(resp.headers)
        raise _RateLimitError(resp.status_code, resp.text, retry_after)
    if resp.status_code in (401, 403):
        raise _AuthError(resp.status_code, resp.text)
    if resp.status_code != 200:
        raise _ProviderError(resp.status_code, resp.text)
        
    data = resp.json()
    choice = data["choices"][0]
    usage = data.get("usage", {})
    
    return InferenceResult(
        content=choice["message"]["content"] or "",
        provider="watsonx",
        model=model,
        key_id="",
        tokens_in=usage.get("prompt_tokens", 0),
        tokens_out=usage.get("completion_tokens", 0),
        latency_ms=round(latency, 1),
        finish_reason=choice.get("finish_reason", "stop"),
    )


def _call_openai_compatible(
    provider: str,
    base_url: str,
    messages: List[Dict[str, str]],
    model: str,
    api_key: str,
    temperature: float,
    max_tokens: Optional[int],
    system_prompt: Optional[str],
) -> InferenceResult:
    """
    Llama a cualquier provider compatible con la API de OpenAI (DeepSeek, xAI, etc.).
    """
    payload_messages = []
    if system_prompt:
        payload_messages.append({"role": "system", "content": system_prompt})
    payload_messages.extend(messages)

    payload = {
        "model": model,
        "messages": payload_messages,
        "temperature": temperature,
        "max_tokens": max_tokens or 2048,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    t0 = time.monotonic()
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            json=payload,
            headers=headers,
        )

    latency = (time.monotonic() - t0) * 1000

    if resp.status_code == 429:
        retry_after = _parse_retry_after(resp.headers)
        raise _RateLimitError(resp.status_code, resp.text, retry_after)
    if resp.status_code in (401, 403):
        raise _AuthError(resp.status_code, resp.text)
    if resp.status_code == 503:
        raise _ServiceError(resp.status_code, resp.text)
    if resp.status_code != 200:
        raise _ProviderError(resp.status_code, resp.text)

    data = resp.json()
    choice = data["choices"][0]
    usage = data.get("usage", {})

    return InferenceResult(
        content=choice["message"]["content"] or "",
        provider=provider,
        model=model,
        key_id="",
        tokens_in=usage.get("prompt_tokens", 0),
        tokens_out=usage.get("completion_tokens", 0),
        latency_ms=round(latency, 1),
        finish_reason=choice.get("finish_reason", "stop"),
    )


# ─── Excepciones internas normalizadas ────────────────────────────────────────

class _RateLimitError(Exception):
    def __init__(self, code: int, msg: str, retry_after: Optional[float] = None):
        super().__init__(msg)
        self.code = code
        self.retry_after = retry_after

class _AuthError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code

class _ServiceError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code

class _ProviderError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(msg)
        self.code = code


# ─── Router principal ─────────────────────────────────────────────────────────

class ProviderRouterService:
    """
    Orquesta inferencias multi-provider con fallback automático y Anti-429.

    Para cada tier tiene un orden de providers preferido.
    Si un provider falla con 429/503/timeout, pasa al siguiente
    sin esperar (el cooldown evitará que esa key se reutilice).
    """

    def infer(
        self,
        messages: List[Dict[str, str]],
        tier: str = "balanced",
        user_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        force_provider: Optional[str] = None,  # override para debug
        preferred_provider: Optional[str] = None,
        preferred_model: Optional[str] = None,
        fallback_models: Optional[List[Dict[str, str]]] = None,
    ) -> InferenceResult:
        """
        Punto de entrada principal.

        Args:
            messages:           Lista de mensajes estilo OpenAI [{"role":..., "content":...}]
            tier:               "fast" | "balanced" | "pro"
            user_id:            UUID del usuario (para priorizar sus keys)
            system_prompt:      System prompt del agente (ya compilado por AFT)
            temperature:        0.0 - 2.0
            max_tokens:         Máximo de tokens de salida
            force_provider:     Forzar un provider concreto (debug/test)
            preferred_provider: Proveedor preferido del agente (ej. google, groq)
            preferred_model:    Modelo preferido del agente (ej. gemini-2.0-flash, llama-3.3-70b-versatile)

        Returns:
            InferenceResult con el contenido y métricas.

        Raises:
            InferenceError si todos los providers y keys fallan.
        """
        # 1. Obtener de forma dinámica todos los proveedores que tienen claves activas
        active_providers_in_pool = set()
        with key_pool._lock:
            for k in key_pool._keys.values():
                if k.user_id == user_id or k.source == "system":
                    active_providers_in_pool.add(k.provider)

        # Construir secuencia de intentos (provider, model)
        attempts_sequence = []
        visited_configs = set()

        # - Añadir el principal si existe
        if preferred_provider and preferred_model:
            config_key = (preferred_provider, preferred_model)
            attempts_sequence.append(config_key)
            visited_configs.add(config_key)
            
            # Su fallback local liviano
            lw = LIGHTWEIGHT_MODELS.get(preferred_provider)
            if lw and (preferred_provider, lw) not in visited_configs:
                attempts_sequence.append((preferred_provider, lw))
                visited_configs.add((preferred_provider, lw))

        # - Añadir los fallback_models personalizados del agente
        if fallback_models:
            for fm in fallback_models:
                p = fm.get("provider")
                m = fm.get("model")
                if p and m and p in active_providers_in_pool:
                    config_key = (p, m)
                    if config_key not in visited_configs:
                        attempts_sequence.append(config_key)
                        visited_configs.add(config_key)
                        
                        # También añadir su respectivo modelo liviano como fallback del fallback
                        lw = LIGHTWEIGHT_MODELS.get(p)
                        if lw and (p, lw) not in visited_configs:
                            attempts_sequence.append((p, lw))
                            visited_configs.add((p, lw))

        # - Añadir el resto de proveedores activos del pool (fallbacks generales del sistema)
        if force_provider:
            provider_order = [force_provider]
        elif preferred_provider:
            provider_order = [preferred_provider]
            default_fallbacks = ["groq", "google", "openrouter"]
            for p in default_fallbacks:
                if p != preferred_provider and p in active_providers_in_pool:
                    provider_order.append(p)
            for p in sorted(active_providers_in_pool):
                if p not in provider_order:
                    provider_order.append(p)
        else:
            suggested_order = key_pool.get_ordered_providers(tier)
            provider_order = []
            for p in suggested_order:
                if p in active_providers_in_pool:
                    provider_order.append(p)
            for p in sorted(active_providers_in_pool):
                if p not in provider_order:
                    provider_order.append(p)

        for p in provider_order:
            m = key_pool.get_model_for_tier(p, tier)
            if not m:
                m = LIGHTWEIGHT_MODELS.get(p)
            if p and m:
                config_key = (p, m)
                if config_key not in visited_configs:
                    attempts_sequence.append(config_key)
                    visited_configs.add(config_key)
                    
                    # Su fallback local
                    lw = LIGHTWEIGHT_MODELS.get(p)
                    if lw and (p, lw) not in visited_configs:
                        attempts_sequence.append((p, lw))
                        visited_configs.add((p, lw))

        attempts: List[ProviderAttempt] = []

        # Modelos gratuitos alternativos de OpenRouter en caso de 429
        openrouter_free_fallbacks = [
            "meta-llama/llama-3.3-70b-instruct:free",
            "meta-llama/llama-3.1-8b-instruct:free",
            "qwen/qwen-2.5-72b-instruct:free",
            "deepseek/deepseek-r1-distill-llama-70b:free"
        ]

        for provider, model in attempts_sequence:
            # Si es OpenRouter y es un modelo gratuito, expandimos dinámicamente sus fallbacks gratuitos
            models_to_try = [model]
            if provider == "openrouter" and model.endswith(":free"):
                for fallback_m in openrouter_free_fallbacks:
                    if fallback_m not in models_to_try:
                        models_to_try.append(fallback_m)

            rpm_limit = PROVIDER_RPM_LIMITS.get(provider, 20)

            for try_model in models_to_try:
                # Intentar con hasta 2 keys del mismo provider (si hay varias)
                key_attempts_succeeded = False
                for _ in range(2):
                    key = key_pool.get_best_key(
                        provider=provider, tier=tier, user_id=user_id
                    )
                    # Si no es la primera opción, permitimos ignore_cooldown para resiliencia
                    if key is None and (provider, try_model) != attempts_sequence[0]:
                        key = key_pool.get_best_key(
                            provider=provider, tier=tier, user_id=user_id, ignore_cooldown=True
                        )
                    if key is None:
                        logger.info(f"Router: no hay keys disponibles en {provider} para el modelo {try_model}, pasando a la siguiente opción")
                        break

                    cooldown_service.record_request(key.key_id)
                    logger.info(f"Router: intentando {provider}/{try_model} con key={key.key_id}")

                    try:
                        result = self._dispatch(
                            provider=provider,
                            model=try_model,
                            messages=messages,
                            api_key=key.api_key,
                            system_prompt=system_prompt,
                            temperature=temperature,
                            max_tokens=max_tokens,
                        )
                        # ✅ Éxito
                        result.key_id = key.key_id
                        cooldown_service.record_success(
                            key.key_id,
                            tokens_in=result.tokens_in,
                            tokens_out=result.tokens_out,
                        )
                        logger.info(
                            f"Router: ✅ {provider}/{try_model} | {result.tokens_in}in "
                            f"{result.tokens_out}out | {result.latency_ms:.0f}ms"
                        )
                        return result

                    except _RateLimitError as e:
                        cooldown_service.record_429(key.key_id, retry_after=e.retry_after)
                        attempts.append(ProviderAttempt(
                            provider=provider, key_id=key.key_id, model=try_model,
                            error_code=429, error_msg=str(e)[:200], retry_after=e.retry_after,
                        ))
                        logger.warning(f"Router: 429 en {provider}/{key.key_id} para modelo {try_model} retry_after={e.retry_after}s")

                    except _AuthError as e:
                        cooldown_service.record_auth_error(key.key_id)
                        attempts.append(ProviderAttempt(
                            provider=provider, key_id=key.key_id, model=try_model,
                            error_code=e.code, error_msg=str(e)[:200],
                        ))
                        logger.error(f"Router: auth error en {provider}/{key.key_id}")
                        break  # key inválida → pasar a la siguiente key/modelo

                    except _ServiceError as e:
                        cooldown_service.record_503(key.key_id)
                        attempts.append(ProviderAttempt(
                            provider=provider, key_id=key.key_id, model=try_model,
                            error_code=503, error_msg=str(e)[:200],
                        ))
                        logger.warning(f"Router: 503 en {provider}/{key.key_id}")
                        break  # provider caído → siguiente key/modelo

                    except GroqRateLimitError as e:
                        retry_after = None
                        if hasattr(e, 'response') and e.response is not None:
                            retry_after = _parse_retry_after(e.response.headers)
                        cooldown_service.record_429(key.key_id, retry_after=retry_after)
                        attempts.append(ProviderAttempt(
                            provider=provider, key_id=key.key_id, model=model,
                            error_code=429, error_msg=str(e)[:200], retry_after=retry_after,
                        ))
                        logger.warning(f"Router: 429 en Groq {key.key_id} para modelo {model} retry_after={retry_after}s")

                    except GroqAPIStatusError as e:
                        code = e.status_code if hasattr(e, 'status_code') else 500
                        if code in (401, 403):
                            cooldown_service.record_auth_error(key.key_id)
                            break
                        elif code == 503:
                            cooldown_service.record_503(key.key_id)
                            break
                        attempts.append(ProviderAttempt(
                            provider=provider, key_id=key.key_id, model=model,
                            error_code=code, error_msg=str(e)[:200],
                        ))

                    except httpx.TimeoutException:
                        cooldown_service.record_timeout(key.key_id)
                        attempts.append(ProviderAttempt(
                            provider=provider, key_id=key.key_id, model=model,
                            error_code=408, error_msg="Timeout de red",
                        ))
                        logger.warning(f"Router: timeout en {provider}/{key.key_id} para modelo {model}")
                        break

                    except Exception as e:
                        attempts.append(ProviderAttempt(
                            provider=provider, key_id=key.key_id, model=model,
                            error_code=500, error_msg=str(e)[:200],
                        ))
                        logger.error(f"Router: error inesperado en {provider}/{key.key_id}: {e}")
                        break

                # Si logramos el éxito con alguna key, retornamos (se maneja dentro del try)
                # Si fallaron las keys para este modelo de OpenRouter, el bucle avanzará al siguiente modelo free
                if key_attempts_succeeded:
                    break

        # Todos los providers fallaron — log detallado para diagnóstico
        providers_tried = list({a.provider for a in attempts})
        rate_limits = [a for a in attempts if a.error_code == 429]
        auth_errors  = [a for a in attempts if a.error_code in (401, 403)]

        logger.error(
            f"Router: ❌ todos los providers fallaron. "
            f"Intentos: {len(attempts)} | 429s: {len(rate_limits)} | "
            f"Auth errors: {len(auth_errors)} | "
            f"Providers: {providers_tried}"
        )
        for a in attempts:
            logger.error(
                f"  → {a.provider}/{a.model} [{a.error_code}] retry_after={a.retry_after} — {a.error_msg[:120]}"
            )

        raise InferenceError(
            f"Todos los providers fallaron ({', '.join(providers_tried)}). "
            f"{len(attempts)} intentos realizados.",
            attempts=attempts,
        )

    def _dispatch(
        self,
        provider: str,
        model: str,
        messages: List[Dict[str, str]],
        api_key: str,
        system_prompt: Optional[str],
        temperature: float,
        max_tokens: Optional[int],
    ) -> InferenceResult:
        """Despacha la llamada al provider correspondiente."""
        kwargs = dict(
            messages=messages,
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )
        if provider == "groq":
            return _call_groq(**kwargs)
        elif provider == "google":
            return _call_gemini(**kwargs)
        elif provider == "cohere":
            return _call_cohere(**kwargs)
        elif provider == "anthropic":
            return _call_anthropic(**kwargs)
        elif provider == "huggingface":
            return _call_huggingface(**kwargs)
        elif provider == "cloudflare":
            account_id = "default"
            token = api_key
            if ":" in api_key:
                account_id, token = api_key.split(":", 1)
            base_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1"
            return _call_openai_compatible(
                provider=provider,
                base_url=base_url,
                messages=messages,
                model=model,
                api_key=token,
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
        elif provider == "watsonx":
            return _call_watsonx(**kwargs)
        elif provider == "openrouter":
            return _call_openrouter(**kwargs)
        elif provider == "ollama":
            base_url = f"{api_key.rstrip('/')}/v1"
            actual_model = model[7:] if model.startswith("ollama/") else model
            return _call_openai_compatible(
                provider=provider,
                base_url=base_url,
                messages=messages,
                model=actual_model,
                api_key="ollama",
                temperature=temperature,
                max_tokens=max_tokens,
                system_prompt=system_prompt,
            )
        elif provider in OPENAI_COMPATIBLE_PROVIDERS:
            base_url = OPENAI_COMPATIBLE_PROVIDERS[provider]
            return _call_openai_compatible(
                provider=provider,
                base_url=base_url,
                **kwargs
            )
        else:
            raise ValueError(f"Provider desconocido: {provider}")


# Singleton global
provider_router = ProviderRouterService()
