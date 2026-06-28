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

# Cache en memoria para otros proveedores (5 minutos de expiración)
_providers_models_cache: Dict[str, Dict[str, Any]] = {}

# Modelos estáticos
GOOGLE_MODELS = [
    {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "provider": "google", "free": True},
    {"id": "gemini-2.0-flash-lite", "name": "Gemini 2.0 Flash Lite", "provider": "google", "free": True},
    {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash", "provider": "google", "free": True},
    {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro", "provider": "google", "free": True},
]

COHERE_MODELS = [
    {"id": "command-r-plus", "name": "Command R+", "provider": "cohere", "free": False},
    {"id": "command-r", "name": "Command R", "provider": "cohere", "free": True},
    {"id": "command", "name": "Command", "provider": "cohere", "free": False},
    {"id": "command-light", "name": "Command Light", "provider": "cohere", "free": True},
]

ANTHROPIC_MODELS = [
    {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet", "provider": "anthropic", "free": False},
    {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "provider": "anthropic", "free": False},
    {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus", "provider": "anthropic", "free": False},
]

NVIDIA_MODELS = [
    {"id": "meta/llama-3.3-70b-instruct", "name": "Llama 3.3 70B Instruct (NVIDIA)", "provider": "nvidia", "free": True},
    {"id": "nvidia/llama-3.1-nemotron-70b-instruct", "name": "Nemotron 70B Instruct (NVIDIA)", "provider": "nvidia", "free": True},
    {"id": "meta/llama-3.1-8b-instruct", "name": "Llama 3.1 8B Instruct (NVIDIA)", "provider": "nvidia", "free": True},
]

CLOUDFLARE_MODELS = [
    {"id": "@cf/meta/llama-3-8b-instruct", "name": "Llama 3 8B Instruct (Cloudflare)", "provider": "cloudflare", "free": True},
    {"id": "@cf/qwen/qwen1.5-7b-chat", "name": "Qwen 1.5 7B (Cloudflare)", "provider": "cloudflare", "free": True},
    {"id": "@cf/mistral/mistral-7b-instruct-v0.2", "name": "Mistral 7B Instruct (Cloudflare)", "provider": "cloudflare", "free": True},
]

HUGGINGFACE_MODELS = [
    {"id": "meta-llama/Llama-3.2-3B-Instruct", "name": "Llama 3.2 3B Instruct (Hugging Face)", "provider": "huggingface", "free": True},
    {"id": "Qwen/Qwen2.5-7B-Instruct", "name": "Qwen 2.5 7B Instruct (Hugging Face)", "provider": "huggingface", "free": True},
    {"id": "microsoft/Phi-3-mini-4k-instruct", "name": "Phi 3 Mini 4K (Hugging Face)", "provider": "huggingface", "free": True},
    {"id": "google/gemma-2-9b-it", "name": "Gemma 2 9B IT (Hugging Face)", "provider": "huggingface", "free": True},
]

ZAI_MODELS = [
    {"id": "glm-4-flash", "name": "GLM 4 Flash (Z.ai)", "provider": "zai", "free": True},
    {"id": "glm-4v-flash", "name": "GLM 4V Flash Multimodal (Z.ai)", "provider": "zai", "free": True},
]

NOVITA_MODELS = [
    {"id": "deepseek/deepseek_v3", "name": "DeepSeek V3 (Novita)", "provider": "novita", "free": False},
    {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1 (Novita)", "provider": "novita", "free": False},
    {"id": "meta-llama/llama-3.1-8b-instruct", "name": "Llama 3.1 8B Instruct (Novita)", "provider": "novita", "free": True},
]

SCALEWAY_MODELS = [
    {"id": "llama-3.1-8b-instruct", "name": "Llama 3.1 8B (Scaleway)", "provider": "scaleway", "free": True},
    {"id": "llama-3.1-70b-instruct", "name": "Llama 3.1 70B (Scaleway)", "provider": "scaleway", "free": False},
    {"id": "mistral-nemo-instruct-2407", "name": "Mistral Nemo (Scaleway)", "provider": "scaleway", "free": True},
]

WATSONX_MODELS = [
    {"id": "meta-llama/llama-3-3-70b-instruct", "name": "Llama 3.3 70B (Watsonx)", "provider": "watsonx", "free": False},
    {"id": "ibm/granite-3-8b-instruct", "name": "Granite 3.0 8B (Watsonx)", "provider": "watsonx", "free": True},
    {"id": "meta-llama/llama-3-8b-instruct", "name": "Llama 3 8B (Watsonx)", "provider": "watsonx", "free": True},
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
    Devuelve la lista de modelos disponibles según las API keys activas en el sistema o del usuario.
    Intenta obtener modelos dinámicamente desde sus APIs oficiales y hace fallback a estáticos si falla.
    """
    from app.services.provider_router_service import OPENAI_COMPATIBLE_PROVIDERS

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

    # Obtener claves descifradas del usuario para poder hacer la llamada dinámica
    decrypted_keys = provider_keys_db_service.get_decrypted_user_keys(current_user["user_id"])
    user_keys_map = {k["provider"]: k["api_key"] for k in decrypted_keys}

    models = []
    
    # Google Gemini: Listado dinámico
    if "google" in active_providers:
        google_key = user_keys_map.get("google") or config.GEMINI_API_KEY
        google_models_dyn = []
        if google_key:
            google_models_dyn = await _fetch_google_models_dynamically(google_key)
        if google_models_dyn:
            models.extend(google_models_dyn)
        else:
            models.extend(GOOGLE_MODELS)
        
    # OpenRouter: Llamada dinámica a su API
    if "openrouter" in active_providers:
        openrouter_list = await _fetch_openrouter_models()
        models.extend(openrouter_list)

    # Groq (con base_url propia o config.GROQ_API_KEY)
    if "groq" in active_providers:
        groq_key = user_keys_map.get("groq") or config.GROQ_API_KEY
        groq_models_dyn = []
        if groq_key:
            groq_models_dyn = await _fetch_provider_models_dynamically("groq", "https://api.groq.com/openai/v1", groq_key)
        if groq_models_dyn:
            models.extend(groq_models_dyn)
        else:
            models.extend(GROQ_MODELS)

    # Otros compatibles
    compatibles = {
        "deepseek": DEEPSEEK_MODELS,
        "xai": XAI_MODELS,
        "perplexity": PERPLEXITY_MODELS,
        "mistral": MISTRAL_MODELS,
        "cerebras": CEREBRAS_MODELS,
        "sambanova": SAMBANOVA_MODELS,
        "together": TOGETHER_MODELS,
        "fireworks": FIREWORKS_MODELS,
        "siliconflow": SILICONFLOW_MODELS,
        "nvidia": NVIDIA_MODELS,
        "zai": ZAI_MODELS,
        "novita": NOVITA_MODELS,
        "scaleway": SCALEWAY_MODELS
    }

    for provider, static_list in compatibles.items():
        if provider in active_providers:
            # Obtener clave (usuario o sistema si aplica)
            key = user_keys_map.get(provider)
            # También soportar claves de sistema si se añadieron en config
            if not key:
                if provider == "deepseek":
                    key = getattr(config, "DEEPSEEK_API_KEY", None)
                elif provider == "xai":
                    key = getattr(config, "XAI_API_KEY", None)
                elif provider == "nvidia":
                    key = getattr(config, "NVIDIA_API_KEY", None)
            
            # Buscar base URL en el router
            base_url = OPENAI_COMPATIBLE_PROVIDERS.get(provider)
            
            dyn_models = []
            if key and base_url:
                dyn_models = await _fetch_provider_models_dynamically(provider, base_url, key)
                
            if dyn_models:
                models.extend(dyn_models)
            else:
                models.extend(static_list)

    # Cohere: Listado dinámico
    if "cohere" in active_providers:
        cohere_key = user_keys_map.get("cohere")
        cohere_models_dyn = []
        if cohere_key:
            cohere_models_dyn = await _fetch_cohere_models_dynamically(cohere_key)
        if cohere_models_dyn:
            models.extend(cohere_models_dyn)
        else:
            models.extend(COHERE_MODELS)

    # Anthropic: Listado estático
    if "anthropic" in active_providers:
        models.extend(ANTHROPIC_MODELS)

    # Cloudflare: Listado estático
    if "cloudflare" in active_providers:
        models.extend(CLOUDFLARE_MODELS)

    # Hugging Face: Listado estático
    if "huggingface" in active_providers:
        models.extend(HUGGINGFACE_MODELS)

    # IBM Watsonx: Listado estático
    if "watsonx" in active_providers:
        models.extend(WATSONX_MODELS)

    return models

@router.post("/recommend", response_model=List[RecommendationItem], summary="Asistente de recomendación de modelos")
async def recommend_models(
    req: RecommendRequest,
    current_user: dict = Depends(require_platform_user)
):
    """
    Analiza la especialización propuesta y los modelos disponibles del usuario
    para recomendar los 3 mejores modelos (Capacidad, Rentabilidad y Equilibrio).
    """
    # 1. Obtener modelos disponibles del usuario
    available = await list_available_models(current_user=current_user)
    if not available:
        # Fallback si no tiene claves de perfil
        return [
            {"provider": "groq", "model": "llama-3.3-70b-versatile", "reason": "Capacidad (groq): Llama 3.3 es el modelo recomendado por su gran capacidad de razonamiento."},
            {"provider": "google", "model": "gemini-2.0-flash", "reason": "Equilibrio (google): Gemini 2.0 Flash ofrece un gran equilibrio entre velocidad y calidad."},
            {"provider": "openrouter", "model": "meta-llama/llama-3.1-8b-instruct:free", "reason": "Rentabilidad (openrouter): La versión gratuita de Llama 3.1 en OpenRouter es muy rentable."}
        ]

    # Preparamos el fallback inteligente por código (en caso de que falle la inferencia o no haya claves)
    active_providers = {m["provider"] for m in available}
    code_recommendations = []
    
    # - Buscar capaz
    capable_model = None
    for p in ["google", "groq", "anthropic", "nvidia", "deepseek", "cohere"]:
        if p in active_providers:
            for m in available:
                if m["provider"] == p and ("pro" in m["id"].lower() or "70b" in m["id"].lower() or "sonnet" in m["id"].lower() or "plus" in m["id"].lower() or "opus" in m["id"].lower()):
                    capable_model = m
                    break
            if capable_model:
                break
    if not capable_model and available:
        capable_model = available[0]
        
    if capable_model:
        code_recommendations.append(RecommendationItem(
            provider=capable_model["provider"],
            model=capable_model["id"],
            reason=f"Capacidad: {capable_model['name']} destaca en razonamiento estructurado para esta especialidad."
        ))
        
    # - Buscar rentable
    rentable_model = None
    for p in ["groq", "cloudflare", "huggingface", "google", "cohere", "zai"]:
        if p in active_providers:
            for m in available:
                if m["provider"] == p and ("lite" in m["id"].lower() or "8b" in m["id"].lower() or "light" in m["id"].lower() or "flash" in m["id"].lower() or "free" in m["id"].lower() or "mini" in m["id"].lower()):
                    if m["id"] != (capable_model["id"] if capable_model else None):
                        rentable_model = m
                        break
            if rentable_model:
                break
    if not rentable_model:
        for m in available:
            if m["id"] != (capable_model["id"] if capable_model else None):
                rentable_model = m
                break
    if not rentable_model and available:
        rentable_model = available[0]
        
    if rentable_model:
        code_recommendations.append(RecommendationItem(
            provider=rentable_model["provider"],
            model=rentable_model["id"],
            reason=f"Rentabilidad: {rentable_model['name']} es altamente rápido, rentable y con gran disponibilidad de tokens."
        ))
        
    # - Buscar equilibrado
    balanced_model = None
    for m in available:
        m_id = m["id"]
        if m_id != (capable_model["id"] if capable_model else None) and m_id != (rentable_model["id"] if rentable_model else None):
            balanced_model = m
            break
    if not balanced_model and available:
        balanced_model = available[0]
        
    if balanced_model:
        code_recommendations.append(RecommendationItem(
            provider=balanced_model["provider"],
            model=balanced_model["id"],
            reason=f"Equilibrio: {balanced_model['name']} es el modelo ideal para balancear latencia y calidad conversacional."
        ))

    # Intentar obtener recomendación del LLM mediante el router
    from app.services.provider_router_service import provider_router
    models_desc = "\n".join([f"- Proveedor: {m['provider']} | ID: {m['id']} | Nombre: {m['name']}" for m in available])
    
    prompt = f"""
Como experto arquitecto de IA de la plataforma Arzor, analiza la siguiente especialización de un agente de IA:
"{req.specialization}"

Aquí tienes la lista de modelos de lenguaje disponibles que el usuario tiene activos actualmente (según sus API keys):
{models_desc}

Elige exactamente los 3 mejores modelos de la lista anterior que mejor se adapten a esta especialización, asegurándote de que:
1. El primero sea el más CAPAZ (calidad premium de razonamiento/análisis).
2. El segundo sea el más RENTABLE (alta disponibilidad, velocidad y bajo consumo de tokens).
3. El tercero sea el más EQUILIBRADO (mejor balance global latencia/precisión).

Explica en una sola frase breve en español por qué recomiendas cada modelo específico destacando si es Capacidad, Rentabilidad o Equilibrio.

RESPONDE ESTRICTAMENTE en formato JSON con la siguiente estructura (un array con exactamente 3 objetos):
[
  {{
    "provider": "<proveedor del modelo recomendado>",
    "model": "<id de modelo recomendado>",
    "reason": "<explicación de una frase en español de por qué es óptimo para esta tarea>"
  }},
  ...
]
No añadas texto adicional antes ni después del JSON.
"""

    try:
        # Cargar temporalmente las claves descifradas del usuario en memoria para la inferencia
        from app.services.provider_keys_db_service import provider_keys_db_service
        from app.services.provider_key_pool_service import key_pool
        decrypted_keys = provider_keys_db_service.get_decrypted_user_keys(current_user["user_id"])
        for uk in decrypted_keys:
            key_pool.add_user_key(
                key_id=uk["key_id"],
                provider=uk["provider"],
                api_key=uk["api_key"],
                user_id=current_user["user_id"],
                label=uk["key_label"],
                priority=10
            )
            
        try:
            result = provider_router.infer(
                messages=[{"role": "user", "content": prompt}],
                tier="balanced",
                user_id=current_user["user_id"]
            )
        finally:
            key_pool.remove_user_keys(current_user["user_id"])
            
        text = result.content.strip()
        
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
        recommendations = []
        for it in items[:3]:
            # Validar que pertenezcan a los disponibles
            provider_val = it.get("provider", "").lower()
            model_val = it.get("model", "")
            # Asegurarse de que no esté vacío
            if provider_val and model_val:
                recommendations.append(RecommendationItem(
                    provider=provider_val,
                    model=model_val,
                    reason=it.get("reason", "Modelo recomendado por especialización.")
                ))
                
        if len(recommendations) == 3:
            return recommendations
            
    except Exception as e:
        logger.error(f"Error en recommend_models LLM: {e}. Usando fallback por código.")
        
    return code_recommendations

async def _fetch_provider_models_dynamically(provider: str, base_url: str, api_key: str) -> List[Dict[str, Any]]:
    """
    Intenta obtener dinámicamente los modelos del proveedor desde su endpoint de API OpenAI-compatible.
    Si falla, devuelve una lista vacía para que el llamador haga fallback a la lista estática.
    """
    now = time.time()
    # Cache key basada en proveedor y hash parcial de la clave
    key_hash = api_key[-8:] if len(api_key) > 8 else "key"
    cache_key = f"{provider}_{key_hash}"
    
    if cache_key in _providers_models_cache:
        cached = _providers_models_cache[cache_key]
        if now - cached["last_updated"] < 300: # 5 minutos
            return cached["data"]
            
    url = f"{base_url.rstrip('/')}/models"
    
    # Ajustes finos de URLs específicas
    if provider == "groq":
        url = "https://api.groq.com/openai/v1/models"
    elif provider == "together":
        url = "https://api.together.xyz/v1/models"
    elif provider == "fireworks":
        url = "https://api.fireworks.ai/inference/v1/models"
    elif provider == "siliconflow":
        url = "https://api.siliconflow.cn/v1/models"
        
    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        async with httpx.AsyncClient(timeout=3.5) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json().get("data", [])
                models = []
                for m in data:
                    model_id = m.get("id")
                    if not model_id:
                        continue
                        
                    # Estimar si es gratis
                    is_free = ":free" in model_id
                    
                    if provider == "mistral" and ("codestral" in model_id.lower() or "small" in model_id.lower() or "ministral" in model_id.lower()):
                        is_free = True
                    elif provider == "groq" and ("llama-3.1-8b" in model_id.lower() or "gemma2-9b" in model_id.lower()):
                        is_free = True
                    elif provider == "siliconflow" and ("free" in model_id.lower() or "deepseek-v3" in model_id.lower() or "deepseek-r1" in model_id.lower()):
                        is_free = True
                    elif provider == "sambanova" and ("8b" in model_id.lower() or "free" in model_id.lower()):
                        is_free = True
                        
                    model_name = m.get("name") or model_id
                    models.append({
                        "id": model_id,
                        "name": f"{model_name} ({provider.upper()})",
                        "provider": provider,
                        "free": is_free
                    })
                
                # Guardar en caché
                _providers_models_cache[cache_key] = {
                    "data": models,
                    "last_updated": now
                }
                logger.info(f"Detección dinámica: {len(models)} modelos recuperados de {provider}")
                return models
    except Exception as e:
        logger.warning(f"No se pudieron obtener modelos dinámicos para {provider} desde {url}: {e}")
        
    return []


async def _fetch_google_models_dynamically(api_key: str) -> List[Dict[str, Any]]:
    """
    Intenta obtener dinámicamente los modelos disponibles de Google Gemini usando su API.
    Si falla, hace fallback a GOOGLE_MODELS.
    """
    now = time.time()
    key_hash = api_key[-8:] if len(api_key) > 8 else "key"
    cache_key = f"google_{key_hash}"
    
    if cache_key in _providers_models_cache:
        cached = _providers_models_cache[cache_key]
        if now - cached["last_updated"] < 300: # 5 minutos
            return cached["data"]
            
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        async with httpx.AsyncClient(timeout=3.5) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json().get("models", [])
                models = []
                for m in data:
                    model_id = m.get("name", "")
                    if model_id.startswith("models/"):
                        model_id = model_id.replace("models/", "")
                    
                    # Filtrar sólo modelos generativos de texto
                    supported_methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" not in supported_methods:
                        continue
                        
                    model_name = m.get("displayName") or model_id
                    models.append({
                        "id": model_id,
                        "name": f"{model_name} (GOOGLE)",
                        "provider": "google",
                        "free": True
                    })
                
                if models:
                    _providers_models_cache[cache_key] = {
                        "data": models,
                        "last_updated": now
                    }
                    logger.info(f"Detección dinámica: {len(models)} modelos recuperados de Google")
                    return models
    except Exception as e:
        logger.warning(f"No se pudieron obtener modelos dinámicos para Google: {e}")
        
    return []


async def _fetch_cohere_models_dynamically(api_key: str) -> List[Dict[str, Any]]:
    """
    Intenta obtener dinámicamente los modelos de Cohere mediante su API oficial.
    Si falla, hace fallback a COHERE_MODELS.
    """
    now = time.time()
    key_hash = api_key[-8:] if len(api_key) > 8 else "key"
    cache_key = f"cohere_{key_hash}"
    
    if cache_key in _providers_models_cache:
        cached = _providers_models_cache[cache_key]
        if now - cached["last_updated"] < 300: # 5 minutos
            return cached["data"]
            
    try:
        url = "https://api.cohere.com/v1/models"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        async with httpx.AsyncClient(timeout=3.5) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                data = resp.json().get("models", [])
                models = []
                for m in data:
                    model_id = m.get("name")
                    if not model_id:
                        continue
                    
                    endpoints = m.get("endpoints", [])
                    if "chat" not in endpoints and "generate" not in endpoints:
                        continue
                        
                    model_name = m.get("display_name") or model_id
                    is_free = "light" in model_id.lower() or "command-r" in model_id.lower()
                    models.append({
                        "id": model_id,
                        "name": f"{model_name} (COHERE)",
                        "provider": "cohere",
                        "free": is_free
                    })
                
                if models:
                    _providers_models_cache[cache_key] = {
                        "data": models,
                        "last_updated": now
                    }
                    logger.info(f"Detección dinámica: {len(models)} modelos recuperados de Cohere")
                    return models
    except Exception as e:
        logger.warning(f"No se pudieron obtener modelos dinámicos para Cohere: {e}")
        
    return []


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
