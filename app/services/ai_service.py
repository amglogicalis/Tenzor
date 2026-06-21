import time
import uuid
import logging
import base64
from typing import List, Optional
from groq import Groq
import google.generativeai as genai
from app.models import Message, ChatCompletionResponse, ChatCompletionResponseChoice, ChatCompletionResponseUsage
from app.prompts.system_prompt import SYSTEM_PROMPT
from app import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AIService:
    def __init__(self):
        # Inicializar Groq si la API key está presente
        self.groq_client = None
        if config.GROQ_API_KEY:
            try:
                self.groq_client = Groq(api_key=config.GROQ_API_KEY)
                logger.info("Cliente Groq inicializado con éxito.")
            except Exception as e:
                logger.error(f"Error inicializando Groq: {e}")

        # Inicializar Gemini si la API key está presente
        self.gemini_enabled = False
        if config.GEMINI_API_KEY:
            try:
                genai.configure(api_key=config.GEMINI_API_KEY)
                self.gemini_enabled = True
                logger.info("Cliente Google Gemini inicializado con éxito.")
            except Exception as e:
                logger.error(f"Error inicializando Gemini: {e}")

    def generate_chat_completion(
        self, 
        messages: List[Message], 
        model: str = "tenzor-dev",
        key_info: Optional[dict] = None,
        temperature: float = 0.7, 
        max_tokens: Optional[int] = None
    ) -> ChatCompletionResponse:
        # Verificar si solicita el modelo personalizado de Tenzor (Tenzor Meteor)
        if model == config.CUSTOM_MODEL_NAME:
            if key_info is not None and not key_info.get("allow_custom_model", False):
                raise ValueError("Tu API Key no tiene permisos para acceder al modelo personalizado Tenzor Meteor.")
            
            # 1. Si el proveedor es local (Ollama) o genérico compatible con OpenAI
            if config.CUSTOM_MODEL_PROVIDER in ["ollama", "openai"]:
                try:
                    logger.info(f"Intentando llamada a modelo personalizado local/externo ({config.CUSTOM_MODEL_NAME})...")
                    import httpx
                    headers = {"Content-Type": "application/json"}
                    if config.CUSTOM_MODEL_API_KEY:
                        headers["Authorization"] = f"Bearer {config.CUSTOM_MODEL_API_KEY}"
                    
                    api_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
                    for m in messages:
                        api_messages.append({"role": m.role, "content": m.content})
                    
                    payload = {
                        "model": config.CUSTOM_MODEL_BACKING_NAME,
                        "messages": api_messages,
                        "temperature": temperature
                    }
                    if max_tokens:
                        payload["max_tokens"] = max_tokens
                    
                    with httpx.Client(timeout=60.0) as client:
                        url = f"{config.CUSTOM_MODEL_ENDPOINT.rstrip('/')}/chat/completions"
                        resp = client.post(url, json=payload, headers=headers)
                        
                        if resp.status_code == 200:
                            data = resp.json()
                            choices = []
                            for idx, choice in enumerate(data.get("choices", [])):
                                choices.append(
                                    ChatCompletionResponseChoice(
                                        index=idx,
                                        message=Message(
                                            role=choice["message"]["role"],
                                            content=choice["message"]["content"]
                                        ),
                                        finish_reason=choice.get("finish_reason", "stop")
                                    )
                                )
                            usage_data = data.get("usage", {})
                            usage = ChatCompletionResponseUsage(
                                prompt_tokens=usage_data.get("prompt_tokens", 0),
                                completion_tokens=usage_data.get("completion_tokens", 0),
                                total_tokens=usage_data.get("total_tokens", 0)
                            )
                            return ChatCompletionResponse(
                                id=data.get("id", f"tenz-custom-{uuid.uuid4().hex[:8]}"),
                                created=data.get("created", int(time.time())),
                                model=f"tenzor-dev ({config.CUSTOM_MODEL_NAME})",
                                choices=choices,
                                usage=usage
                            )
                        else:
                            raise RuntimeError(f"Código de respuesta de error del servidor local/externo: {resp.status_code}")
                except Exception as custom_err:
                    logger.warning(f"Error conectando con el modelo personalizado ({config.CUSTOM_MODEL_NAME}): {custom_err}. Activando FALLBACK automático a la nube...")
                    # Cae al flujo normal si hay error (Auto-Fallback)

            # 2. Si el proveedor es Gemini Custom (Tuned Model en Google AI Studio)
            elif config.CUSTOM_MODEL_PROVIDER == "gemini" and self.gemini_enabled:
                try:
                    logger.info(f"Intentando llamada a Gemini Tuned Model ({config.CUSTOM_MODEL_BACKING_NAME})...")
                    return self._generate_gemini_completion(
                        messages=messages,
                        model_name=config.CUSTOM_MODEL_BACKING_NAME,
                        temperature=temperature,
                        max_tokens=max_tokens
                    )
                except Exception as custom_gemini_err:
                    logger.warning(f"Error en Gemini Tuned Model: {custom_gemini_err}. Activando FALLBACK automático a la nube...")
                    # Cae al flujo normal

        # Preparar mensajes incluyendo el System Prompt
        formatted_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in messages:
            # Nos aseguramos de mantener roles limpios (user, assistant, system)
            role = msg.role if msg.role in ["user", "assistant", "system"] else "user"
            formatted_messages.append({"role": role, "content": msg.content})

        # Comprobar si hay imágenes en la conversación para forzar el uso de Gemini
        has_images = any(msg.images for msg in messages if msg.images)

        # 1. Intentar con la lista de modelos de Groq (en orden de prioridad), si no hay imágenes
        if self.groq_client and not has_images:
            groq_models = ["llama-3.3-70b-versatile", "qwen/qwen3.6-27b"]
            for model_name in groq_models:
                try:
                    logger.info(f"Intentando generación con Groq ({model_name})...")
                    
                    # Ajuste de parámetros
                    kwargs = {
                        "model": model_name,
                        "messages": formatted_messages,
                        "temperature": temperature,
                    }
                    if max_tokens:
                        kwargs["max_tokens"] = max_tokens

                    response = self.groq_client.chat.completions.create(**kwargs)
                    
                    # Mapear respuesta al estándar OpenAI
                    choices = []
                    for idx, choice in enumerate(response.choices):
                        choices.append(
                            ChatCompletionResponseChoice(
                                index=idx,
                                message=Message(
                                    role=choice.message.role,
                                    content=choice.message.content
                                ),
                                finish_reason=choice.finish_reason
                            )
                        )
                    
                    usage = ChatCompletionResponseUsage(
                        prompt_tokens=response.usage.prompt_tokens,
                        completion_tokens=response.usage.completion_tokens,
                        total_tokens=response.usage.total_tokens
                    )

                    return ChatCompletionResponse(
                        id=response.id,
                        created=response.created,
                        model=f"tenzor-dev (groq:{model_name})",
                        choices=choices,
                        usage=usage
                    )
                except Exception as e:
                    logger.warning(f"Error en Groq con el modelo {model_name}: {e}. Intentando siguiente fallback...")

        # 2. Fallback a los modelos de Gemini (en orden de prioridad)
        if self.gemini_enabled:
            gemini_models = ["gemini-2.5-pro", "gemini-2.5-flash"]
            for model_name in gemini_models:
                try:
                    logger.info(f"Intentando fallback con Google Gemini ({model_name})...")
                    return self._generate_gemini_completion(
                        messages=messages,
                        model_name=model_name,
                        temperature=temperature,
                        max_tokens=max_tokens
                    )
                except Exception as e:
                    logger.warning(f"Error en Gemini con el modelo {model_name}: {e}. Intentando siguiente fallback...")

            raise RuntimeError("Ambos proveedores de IA (Groq y Gemini) han fallado para todos los modelos disponibles.")

        raise RuntimeError("No hay proveedores de IA configurados correctamente. Verifica tus API keys.")

    def _generate_gemini_completion(
        self, 
        messages: List[Message], 
        model_name: str,
        temperature: float = 0.7, 
        max_tokens: Optional[int] = None
    ) -> ChatCompletionResponse:
        # Creamos el modelo inyectando el system prompt como instruction
        model_with_instruction = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=SYSTEM_PROMPT
        )
        
        # Convertimos el historial de conversación a la API de Gemini
        gemini_contents = []
        for msg in messages:
            # Mapeamos roles a los aceptados por Gemini (user, model)
            role = "user" if msg.role == "user" else "model"
            parts = [msg.content]
            if msg.images:
                for img_b64 in msg.images:
                    try:
                        if ";base64," in img_b64:
                            header, data = img_b64.split(";base64,")
                            mime_type = header.replace("data:", "")
                        else:
                            mime_type = "image/jpeg"
                            data = img_b64
                        
                        parts.append({
                            "mime_type": mime_type,
                            "data": base64.b64decode(data)
                        })
                    except Exception as img_err:
                        logger.error(f"Error decodificando imagen base64: {img_err}")
            
            gemini_contents.append({
                "role": role,
                "parts": parts
            })
        
        generation_config = genai.types.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens
        )

        response = model_with_instruction.generate_content(
            contents=gemini_contents,
            generation_config=generation_config
        )
        
        completion_text = response.text
        
        # Estimar uso de tokens
        prompt_text = "".join([m.content for m in messages])
        prompt_tokens = len(prompt_text) // 4
        completion_tokens = len(completion_text) // 4
        
        choices = [
            ChatCompletionResponseChoice(
                index=0,
                message=Message(role="assistant", content=completion_text),
                finish_reason="stop"
            )
        ]
        
        usage = ChatCompletionResponseUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens
        )

        return ChatCompletionResponse(
            id=f"tenzor-gemini-{uuid.uuid4().hex[:8]}",
            created=int(time.time()),
            model=f"tenzor-dev (gemini:{model_name})",
            choices=choices,
            usage=usage
        )
