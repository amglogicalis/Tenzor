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
    genai.configure(api_key=api_key)
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
    ) -> InferenceResult:
        """
        Punto de entrada principal.

        Args:
            messages:       Lista de mensajes estilo OpenAI [{"role":..., "content":...}]
            tier:           "fast" | "balanced" | "pro"
            user_id:        UUID del usuario (para priorizar sus keys)
            system_prompt:  System prompt del agente (ya compilado por AFT)
            temperature:    0.0 - 2.0
            max_tokens:     Máximo de tokens de salida
            force_provider: Forzar un provider concreto (debug/test)

        Returns:
            InferenceResult con el contenido y métricas.

        Raises:
            InferenceError si todos los providers y keys fallan.
        """
        provider_order = (
            [force_provider]
            if force_provider
            else key_pool.get_ordered_providers(tier)
        )

        attempts: List[ProviderAttempt] = []

        for provider in provider_order:
            model = key_pool.get_model_for_tier(provider, tier)
            if not model:
                logger.warning(f"Router: no hay modelo configurado para {provider}/{tier}")
                continue

            rpm_limit = PROVIDER_RPM_LIMITS.get(provider, 20)

            # Intentar con hasta 2 keys del mismo provider (si hay varias)
            for _ in range(2):
                key = key_pool.get_best_key(
                    provider=provider, tier=tier, user_id=user_id
                )
                if key is None:
                    logger.info(f"Router: no hay keys disponibles en {provider}/{tier}, pasando al siguiente provider")
                    break

                cooldown_service.record_request(key.key_id)
                logger.info(f"Router: intentando {provider}/{model} con key={key.key_id}")

                try:
                    result = self._dispatch(
                        provider=provider,
                        model=model,
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
                        f"Router: ✅ {provider}/{model} | {result.tokens_in}in "
                        f"{result.tokens_out}out | {result.latency_ms:.0f}ms"
                    )
                    return result

                except _RateLimitError as e:
                    cooldown_service.record_429(key.key_id, retry_after=e.retry_after)
                    attempts.append(ProviderAttempt(
                        provider=provider, key_id=key.key_id, model=model,
                        error_code=429, error_msg=str(e)[:200], retry_after=e.retry_after,
                    ))
                    logger.warning(f"Router: 429 en {provider}/{key.key_id} retry_after={e.retry_after}s")

                except _AuthError as e:
                    cooldown_service.record_auth_error(key.key_id)
                    attempts.append(ProviderAttempt(
                        provider=provider, key_id=key.key_id, model=model,
                        error_code=e.code, error_msg=str(e)[:200],
                    ))
                    logger.error(f"Router: auth error en {provider}/{key.key_id}")
                    break  # key inválida → pasar al siguiente provider

                except _ServiceError as e:
                    cooldown_service.record_503(key.key_id)
                    attempts.append(ProviderAttempt(
                        provider=provider, key_id=key.key_id, model=model,
                        error_code=503, error_msg=str(e)[:200],
                    ))
                    logger.warning(f"Router: 503 en {provider}/{key.key_id}")
                    break  # provider caído → siguiente provider

                except GroqRateLimitError as e:
                    # SDK de Groq tiene su propia excepción de rate limit
                    retry_after = None
                    if hasattr(e, 'response') and e.response is not None:
                        retry_after = _parse_retry_after(e.response.headers)
                    cooldown_service.record_429(key.key_id, retry_after=retry_after)
                    attempts.append(ProviderAttempt(
                        provider=provider, key_id=key.key_id, model=model,
                        error_code=429, error_msg=str(e)[:200], retry_after=retry_after,
                    ))

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
                    logger.warning(f"Router: timeout en {provider}/{key.key_id}")
                    break

                except Exception as e:
                    attempts.append(ProviderAttempt(
                        provider=provider, key_id=key.key_id, model=model,
                        error_code=500, error_msg=str(e)[:200],
                    ))
                    logger.error(f"Router: error inesperado en {provider}/{key.key_id}: {e}")
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
        elif provider == "openrouter":
            return _call_openrouter(**kwargs)
        else:
            raise ValueError(f"Provider desconocido: {provider}")


# Singleton global
provider_router = ProviderRouterService()
