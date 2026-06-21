import time
import uuid
import logging
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
        temperature: float = 0.7, 
        max_tokens: Optional[int] = None
    ) -> ChatCompletionResponse:
        # Preparar mensajes incluyendo el System Prompt
        formatted_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in messages:
            # Nos aseguramos de mantener roles limpios (user, assistant, system)
            role = msg.role if msg.role in ["user", "assistant", "system"] else "user"
            formatted_messages.append({"role": role, "content": msg.content})

        # 1. Intentar con la lista de modelos de Groq (en orden de prioridad)
        if self.groq_client:
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
                        gemini_contents.append({
                            "role": role,
                            "parts": [msg.content]
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

                except Exception as e:
                    logger.warning(f"Error en Gemini con el modelo {model_name}: {e}. Intentando siguiente fallback...")

            raise RuntimeError("Ambos proveedores de IA (Groq y Gemini) han fallado para todos los modelos disponibles.")

        raise RuntimeError("No hay proveedores de IA configurados correctamente. Verifica tus API keys.")
