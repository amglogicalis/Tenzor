import logging
import time
import httpx
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import google.generativeai as genai

from app.middleware.platform_auth_middleware import require_platform_user
from app.services.provider_keys_db_service import provider_keys_db_service
from app.services.provider_key_pool_service import key_pool
from app import config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platform/keys", tags=["platform-keys"])

# Cache en memoria para OpenRouter models (5 minutos de expiración)
_openrouter_models_cache: Dict[str, Any] = {
    "data": [],
    "last_updated": 0
}

# Modelos estáticos
GOOGLE_MODELS = [
    {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "provider": "google", "free": True},
    {"id": "gemini-2.0-flash-lite", "name": "Gemini 2.0 Flash Lite", "provider": "google", "free": True},
    {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash", "provider": "google", "free": True},
    {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro", "provider": "google", "free": True},
]

GROQ_MODELS = [
    {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B Versatile", "provider": "groq", "free": True},
    {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B Instant", "provider": "groq", "free": True},
    {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B", "provider": "groq", "free": True},
    {"id": "gemma2-9b-it", "name": "Gemma 2 9B", "provider": "groq", "free": True},
]

DEEPSEEK_MODELS = [
    {"id": "deepseek-chat", "name": "DeepSeek V3 (Chat)", "provider": "deepseek", "free": False},
    {"id": "deepseek-reasoner", "name": "DeepSeek R1 (Reasoning)", "provider": "deepseek", "free": False},
]

XAI_MODELS = [
    {"id": "grok-2-1212", "name": "Grok 2", "provider": "xai", "free": False},
    {"id": "grok-beta", "name": "Grok Beta", "provider": "xai", "free": False},
]

PERPLEXITY_MODELS = [
    {"id": "sonar", "name": "Perplexity Sonar", "provider": "perplexity", "free": False},
    {"id": "sonar-reasoning", "name": "Perplexity Sonar Reasoning", "provider": "perplexity", "free": False},
]

MISTRAL_MODELS = [
    {"id": "mistral-large-latest", "name": "Mistral Large", "provider": "mistral", "free": False},
    {"id": "codestral-latest", "name": "Codestral (Coding)", "provider": "mistral", "free": True},
    {"id": "mistral-small-latest", "name": "Mistral Small", "provider": "mistral", "free": True},
]

CEREBRAS_MODELS = [
    {"id": "llama3.1-8b", "name": "Llama 3.1 8B (Cerebras)", "provider": "cerebras", "free": True},
    {"id": "llama3.1-70b", "name": "Llama 3.1 70B (Cerebras)", "provider": "cerebras", "free": True},
]

SAMBANOVA_MODELS = [
    {"id": "Meta-Llama-3.1-8B-Instruct", "name": "Llama 3.1 8B (SambaNova)", "provider": "sambanova", "free": True},
    {"id": "Meta-Llama-3.1-70B-Instruct", "name": "Llama 3.1 70B (SambaNova)", "provider": "sambanova", "free": True},
    {"id": "DeepSeek-V3", "name": "DeepSeek V3 (SambaNova)", "provider": "sambanova", "free": True},
]

TOGETHER_MODELS = [
    {"id": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo", "name": "Llama 3.1 8B (Together)", "provider": "together", "free": False},
    {"id": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo", "name": "Llama 3.1 70B (Together)", "provider": "together", "free": False},
]

FIREWORKS_MODELS = [
    {"id": "accounts/fireworks/models/llama-v3p1-8b-instruct", "name": "Llama 3.1 8B (Fireworks)", "provider": "fireworks", "free": False},
    {"id": "accounts/fireworks/models/llama-v3p1-70b-instruct", "name": "Llama 3.1 70B (Fireworks)", "provider": "fireworks", "free": False},
]

SILICONFLOW_MODELS = [
    {"id": "deepseek-ai/DeepSeek-V3", "name": "DeepSeek V3 (SiliconFlow)", "provider": "siliconflow", "free": True},
    {"id": "deepseek-ai/DeepSeek-R1", "name": "DeepSeek R1 (SiliconFlow)", "provider": "siliconflow", "free": True},
]

class AddKeyRequest(BaseModel):
    provider: str = Field(..., pattern=r"^(google|groq|openrouter|xai|perplexity|deepseek|together|fireworks|mistral|sambanova|cerebras|siliconflow)$", description="Proveedor compatible")
    key_label: str = Field("", max_length=100, description="Etiqueta para identificar la clave")
    api_key: str = Field(..., min_length=5, description="La clave de API real")

class KeyResponse(BaseModel):
    id: str
    provider: str
    key_label: str
    is_active: bool
    created_at: str
    masked_key: str

class RecommendRequest(BaseModel):
    specialization: str = Field(..., min_length=5, max_length=1000, description="Especialización del agente")

class RecommendationItem(BaseModel):
    provider: str
    model: str
    reason: str

@router.post("", response_model=KeyResponse, summary="Añadir o actualizar una clave de proveedor")
async def add_provider_key(
    req: AddKeyRequest,
    current_user: dict = Depends(require_platform_user)
):
    try:
        new_key = provider_keys_db_service.add_key(
            user_id=current_user["user_id"],
            provider=req.provider,
            key_label=req.key_label,
            raw_key=req.api_key
        )
        return new_key
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error en add_provider_key router: {e}")
        raise HTTPException(status_code=500, detail="Error interno al guardar la clave.")

@router.get("", response_model=List[KeyResponse], summary="Listar mis claves de proveedores")
async def list_provider_keys(
    current_user: dict = Depends(require_platform_user)
):
    try:
        keys = provider_keys_db_service.list_keys(user_id=current_user["user_id"])
        for k in keys:
            if hasattr(k["created_at"], "isoformat"):
                k["created_at"] = k["created_at"].isoformat()
        return keys
    except Exception as e:
        logger.error(f"Error en list_provider_keys router: {e}")
        raise HTTPException(status_code=500, detail="Error al listar claves.")

@router.delete("/{key_id}", summary="Eliminar una clave de proveedor")
async def delete_provider_key(
    key_id: str,
    current_user: dict = Depends(require_platform_user)
):
    try:
        success = provider_keys_db_service.delete_key(
            user_id=current_user["user_id"],
            key_id=key_id
        )
        if not success:
            raise HTTPException(status_code=400, detail="No se pudo eliminar la clave.")
        return {"status": "success", "message": "Clave de API eliminada correctamente."}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logger.error(f"Error en delete_provider_key router: {e}")
        raise HTTPException(status_code=500, detail="Error al eliminar la clave.")

@router.get("/models/available", summary="Listar modelos disponibles para el usuario")
async def list_available_models(
    current_user: dict = Depends(require_platform_user)
):
    """
    Devuelve la lista de modelos disponibles (Google, Groq y OpenRouter)
    según las API keys activas en el sistema o del usuario.
    """
    # 1. Obtener qué claves tiene configuradas el usuario
    user_keys = provider_keys_db_service.list_keys(user_id=current_user["user_id"])
    active_providers = {k["provider"] for k in user_keys if k["is_active"]}

    # Siempre incluir los proveedores que tengan claves de sistema
    if config.GEMINI_API_KEY:
        active_providers.add("google")
    if config.GROQ_API_KEY:
        active_providers.add("groq")
    if config.OPENROUTER_API_KEY:
        active_providers.add("openrouter")

    models = []
    if "google" in active_providers:
        models.extend(GOOGLE_MODELS)
    if "groq" in active_providers:
        models.extend(GROQ_MODELS)
    if "openrouter" in active_providers:
        openrouter_list = await _fetch_openrouter_models()
        models.extend(openrouter_list)
    if "deepseek" in active_providers:
        models.extend(DEEPSEEK_MODELS)
    if "xai" in active_providers:
        models.extend(XAI_MODELS)
    if "perplexity" in active_providers:
        models.extend(PERPLEXITY_MODELS)
    if "mistral" in active_providers:
        models.extend(MISTRAL_MODELS)
    if "cerebras" in active_providers:
        models.extend(CEREBRAS_MODELS)
    if "sambanova" in active_providers:
        models.extend(SAMBANOVA_MODELS)
    if "together" in active_providers:
        models.extend(TOGETHER_MODELS)
    if "fireworks" in active_providers:
        models.extend(FIREWORKS_MODELS)
    if "siliconflow" in active_providers:
        models.extend(SILICONFLOW_MODELS)

    return models

@router.post("/recommend", response_model=List[RecommendationItem], summary="Asistente de recomendación de modelos")
async def recommend_models(
    req: RecommendRequest,
    current_user: dict = Depends(require_platform_user)
):
    """
    Analiza la especialización propuesta y los modelos disponibles del usuario
    para recomendar los 3 mejores modelos.
    """
    if not config.GEMINI_API_KEY:
        # Fallback a recomendación fija si no hay Gemini configurado
        return [
            {"provider": "groq", "model": "llama-3.3-70b-versatile", "reason": "Llama 3.3 es ideal para razonamiento rápido y formateo de datos."},
            {"provider": "google", "model": "gemini-2.0-flash", "reason": "Gemini 2.0 Flash es excelente para tareas multimodales y contextos extensos."},
            {"provider": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free", "reason": "La versión gratuita de Llama 3.3 en OpenRouter es muy balanceada para desarrollo general."}
        ]

    # Obtener modelos disponibles del usuario
    available = await list_available_models(current_user=current_user)
    if not available:
        raise HTTPException(status_code=400, detail="No tienes proveedores activos configurados.")

    models_desc = "\n".join([f"- Proveedor: {m['provider']} | ID de Modelo: {m['id']} | Nombre: {m['name']}" for m in available])

    prompt = f"""
Como experto arquitecto de IA de la plataforma Arzor, analiza la siguiente especialización/tarea de un agente de IA:
"{req.specialization}"

Aquí tienes la lista de modelos de lenguaje disponibles que el usuario tiene activos actualmente (según sus API keys):
{models_desc}

Elige exactamente los 3 mejores modelos de la lista anterior que mejor se adapten a esta especialización.
Debe ser una selección variada (o repetidos si es el mejor de distintos proveedores) que optimice calidad, velocidad o coste.
Explica en una sola frase breve y técnica por qué recomiendas cada modelo específico para esta especialidad.

RESPONDE ESTRICTAMENTE en formato JSON con la siguiente estructura (un array con exactamente 3 objetos):
[
  {{
    "provider": "<proveedor del modelo recomendado>",
    "model": "<id de modelo recomendado>",
    "reason": "<breve explicación de una frase en español de por qué es óptimo para esta tarea>"
  }},
  ...
]
No añadas texto adicional antes ni después del JSON.
"""

    try:
        genai.configure(api_key=config.GEMINI_API_KEY, transport="rest")
        # Usamos gemini-1.5-flash que es rápido y altamente disponible
        model = genai.GenerativeModel("gemini-1.5-flash")
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        # Extraer JSON de forma robusta
        import json
        import re
        md_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        if md_match:
            json_str = md_match.group(1).strip()
        else:
            json_str = text
            
        start = json_str.find("[")
        end = json_str.rfind("]")
        if start != -1 and end != -1:
            json_str = json_str[start:end+1]
            
        items = json.loads(json_str)
        # Asegurar que sean exactamente 3 y válidos
        recommendations = []
        for it in items[:3]:
            recommendations.append(RecommendationItem(
                provider=it.get("provider", "desconocido"),
                model=it.get("model", "desconocido"),
                reason=it.get("reason", "Modelo recomendado por especialización.")
            ))
        return recommendations
    except Exception as e:
        logger.error(f"Error en recommend_models: {e}")
        # Fallback en caso de error de parseo o API
        return [
            {"provider": "google", "model": "gemini-2.0-flash", "reason": "Recomendación por defecto: Gemini 2.0 Flash es excelente para propósitos generales."},
            {"provider": "groq", "model": "llama-3.3-70b-versatile", "reason": "Llama 3.3 70B de Groq ofrece un rendimiento de vanguardia a muy baja latencia."},
            {"provider": "openrouter", "model": "meta-llama/llama-3.3-70b-instruct:free", "reason": "Modelo alternativo gratis con alto nivel para prototipado rápido."}
        ]

async def _fetch_openrouter_models() -> List[Dict[str, Any]]:
    """Obtiene de forma segura la lista de modelos de OpenRouter con caché en memoria."""
    now = time.time()
    # Retornar del caché si no ha expirado (5 minutos)
    if _openrouter_models_cache["data"] and (now - _openrouter_models_cache["last_updated"] < 300):
        return _openrouter_models_cache["data"]

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get("https://openrouter.ai/api/v1/models")
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                models = []
                for m in data:
                    model_id = m.get("id")
                    # Filtrar sólo los modelos gratuitos de OpenRouter por ahora para el pool free
                    # o incluir de pago también para que los BYOK puedan seleccionarlos
                    is_free = ":free" in model_id or m.get("pricing", {}).get("prompt") == "0"
                    models.append({
                        "id": model_id,
                        "name": f"{m.get('name')} (OpenRouter)",
                        "provider": "openrouter",
                        "free": is_free
                    })
                # Ordenar para que los gratuitos salgan primero
                models.sort(key=lambda x: not x["free"])
                
                # Actualizar caché
                _openrouter_models_cache["data"] = models
                _openrouter_models_cache["last_updated"] = now
                return models
    except Exception as e:
        logger.error(f"Error recuperando modelos de OpenRouter: {e}")
    
    # En caso de error, retornar del caché si existe, o lista vacía
    return _openrouter_models_cache["data"]


@router.get("/debug/gemini-test", summary="Endpoint de diagnóstico para error 403 de Gemini en producción")
async def debug_gemini_test(key_override: Optional[str] = None):
    """
    Realiza una petición HTTP cruda a la API de Google Gemini (AI Studio)
    y devuelve los headers y el status code exactos de la respuesta para diagnóstico.
    """
    api_key = key_override or config.GEMINI_API_KEY
    if not api_key:
        return {"error": "GEMINI_API_KEY no configurado en el servidor ni provisto en query."}
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    payload = {
        "contents": [{
            "parts": [{"text": "Test de conectividad. Responde con un ok."}]
        }]
    }
    
    import time
    t0 = time.monotonic()
    result = {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
            latency = (time.monotonic() - t0) * 1000
            
            # Sanitizar headers para no exponer info sensible pero ver el resto
            headers = {}
            for k, v in resp.headers.items():
                if k.lower() not in ("set-cookie", "cookie", "authorization"):
                    headers[k] = v
                    
            result = {
                "status_code": resp.status_code,
                "latency_ms": round(latency, 1),
                "headers": headers,
                "body": resp.text[:4000] # Primeros 4KB
            }
    except Exception as e:
        result = {
            "error": f"Excepción durante la conexión HTTP: {str(e)}",
            "latency_ms": round((time.monotonic() - t0) * 1000, 1)
        }
        
    return result
