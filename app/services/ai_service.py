import os
import time
import uuid
import logging
import base64
from typing import Any, Dict, List, Optional
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

        # Estado en memoria para despliegue On-Demand de Vertex AI
        self.current_op_name = None
        self.current_op_kind = None
        self.current_op_error = None
        self.last_activity_time = time.time()

        # Inicializar servicio RAG de documentación
        from app.services.rag_service import RAGService
        self.rag_service = RAGService()


    def generate_chat_completion(
        self, 
        messages: List[Message], 
        model: str = "tenzor-dev",
        key_info: Optional[dict] = None,
        temperature: float = 0.7, 
        max_tokens: Optional[int] = None
    ) -> ChatCompletionResponse:
        # Obtener la consulta del usuario más reciente para el RAG
        user_query = ""
        for msg in reversed(messages):
            if msg.role == "user":
                user_query = msg.content
                break

        dynamic_system_prompt = SYSTEM_PROMPT
        if user_query:
            try:
                rag_results = self.rag_service.search(user_query)
                if rag_results:
                    context_blocks = []
                    for chunk in rag_results:
                        context_blocks.append(
                            f"--- ARCHIVO: {os.path.basename(chunk.source_file)} (Sección: {chunk.heading}) ---\n{chunk.content}"
                        )
                    context_str = "\n\n".join(context_blocks)
                    dynamic_system_prompt = f"{SYSTEM_PROMPT}\n\n[CONTEXTO DE DOCUMENTACIÓN INTERNA DE LA ORGANIZACIÓN]\nUsa la siguiente información de contexto para responder de forma precisa. Prioriza estos datos internos sobre el conocimiento general:\n{context_str}\n"
                    logger.info(f"RAG: Inyectados {len(rag_results)} chunks de documentación de contexto.")
            except Exception as rag_err:
                logger.error(f"Error al realizar búsqueda RAG: {rag_err}")

        # Verificar si solicita el modelo personalizado Tenzor Nova
        if model == config.CUSTOM_MODEL_NAME:
            if key_info is not None and not key_info.get("allow_custom_model", False):
                raise ValueError("Tu API Key no tiene permisos para acceder al modelo personalizado Tenzor Nova.")
            
            # 1. Si el proveedor es local (Ollama) o genérico compatible con OpenAI
            if config.CUSTOM_MODEL_PROVIDER in ["ollama", "openai"]:
                try:
                    logger.info(f"Intentando llamada a modelo personalizado local/externo ({config.CUSTOM_MODEL_NAME})...")
                    import httpx
                    headers = {"Content-Type": "application/json"}
                    if config.CUSTOM_MODEL_API_KEY:
                        headers["Authorization"] = f"Bearer {config.CUSTOM_MODEL_API_KEY}"
                    
                    api_messages = [{"role": "system", "content": dynamic_system_prompt}]
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
                    # Cae al flujo normal si hay error (A            # 2. Si el proveedor es Gemini Custom (Tuned Model en Google AI Studio)
            elif config.CUSTOM_MODEL_PROVIDER == "gemini" and self.gemini_enabled:
                try:
                    logger.info(f"Intentando llamada a Gemini Tuned Model ({config.CUSTOM_MODEL_BACKING_NAME})...")
                    return self._generate_gemini_completion(
                        messages=messages,
                        model_name=config.CUSTOM_MODEL_BACKING_NAME,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        system_prompt=dynamic_system_prompt
                    )
                except Exception as custom_gemini_err:
                    logger.warning(f"Error en Gemini Tuned Model: {custom_gemini_err}. Activando FALLBACK automático a la nube...")
                    # Cae al flujo normal
 
            # 3. Si el proveedor es Vertex AI (GCP)
            elif config.CUSTOM_MODEL_PROVIDER == "vertexai":
                try:
                    if "endpoints/" in config.CUSTOM_MODEL_BACKING_NAME:
                        logger.info(f"Intentando llamada a Vertex AI Custom Endpoint ({config.CUSTOM_MODEL_BACKING_NAME})...")
                        return self._generate_custom_vertex_completion(
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            system_prompt=dynamic_system_prompt
                        )
                    else:
                        logger.info(f"Intentando llamada a Vertex AI Tuned Model ({config.CUSTOM_MODEL_BACKING_NAME})...")
                        return self._generate_vertexai_completion(
                            messages=messages,
                            model_name=config.CUSTOM_MODEL_BACKING_NAME,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            system_prompt=dynamic_system_prompt
                        )
                except Exception as custom_vertex_err:
                    logger.warning(f"Error en Vertex AI Tuned Model: {custom_vertex_err}. Activando FALLBACK automático a la nube...")


        # Preparar mensajes incluyendo el System Prompt
        formatted_messages = [{"role": "system", "content": dynamic_system_prompt}]
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
                        max_tokens=max_tokens,
                        system_prompt=dynamic_system_prompt
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
        max_tokens: Optional[int] = None,
        system_prompt: str = SYSTEM_PROMPT
    ) -> ChatCompletionResponse:
        # Creamos el modelo inyectando el system prompt como instruction
        model_with_instruction = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system_prompt
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

    def _generate_vertexai_completion(
        self,
        messages: List[Message],
        model_name: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        system_prompt: str = SYSTEM_PROMPT
    ) -> ChatCompletionResponse:
        import os
        import json
        import httpx
        from google.oauth2 import service_account
        import google.auth.transport.requests

        # 1. Cargar credenciales
        creds = None
        google_creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if google_creds_json:
            try:
                info = json.loads(google_creds_json)
                creds = service_account.Credentials.from_service_account_info(
                    info,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
                logger.info("Credenciales de Vertex AI cargadas de GOOGLE_CREDENTIALS_JSON.")
            except Exception as e:
                logger.error(f"Error cargando GOOGLE_CREDENTIALS_JSON: {e}")
        
        if not creds:
            # Rutas locales
            sa_paths = [
                "service_account.json",
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "service_account.json")
            ]
            for sa_path in sa_paths:
                if os.path.exists(sa_path):
                    try:
                        creds = service_account.Credentials.from_service_account_file(
                            sa_path,
                            scopes=["https://www.googleapis.com/auth/cloud-platform"]
                        )
                        logger.info(f"Credenciales de Vertex AI cargadas desde {sa_path}.")
                        break
                    except Exception as e:
                        logger.error(f"Error cargando credentials de {sa_path}: {e}")

        if not creds:
            raise RuntimeError("No se encontraron credenciales de Vertex AI (GOOGLE_CREDENTIALS_JSON o service_account.json).")

        # 2. Generar token de acceso
        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        access_token = creds.token

        # 3. Determinar región
        parts = model_name.split("/")
        region = "us-central1"
        if "locations" in parts:
            idx = parts.index("locations")
            if idx + 1 < len(parts):
                region = parts[idx + 1]

        # 4. Construir URL
        url = f"https://{region}-aiplatform.googleapis.com/v1/{model_name}:generateContent"

        # 5. Formatear payload
        gemini_contents = []
        for msg in messages:
            role = "user" if msg.role == "user" else "model"
            parts_list = [{"text": msg.content}]
            if msg.images:
                for img_b64 in msg.images:
                    try:
                        if ";base64," in img_b64:
                            header, data = img_b64.split(";base64,")
                            mime_type = header.replace("data:", "")
                        else:
                            mime_type = "image/jpeg"
                            data = img_b64
                        
                        parts_list.append({
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": data
                            }
                        })
                    except Exception as img_err:
                        logger.error(f"Error decodificando imagen base64 para Vertex AI: {img_err}")
            
            gemini_contents.append({
                "role": role,
                "parts": parts_list
            })

        payload = {
            "contents": gemini_contents,
            "systemInstruction": {
                "parts": [{"text": system_prompt}]
            },
            "generationConfig": {
                "temperature": temperature
            }
        }
        if max_tokens:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        # 6. Realizar petición POST
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                raise RuntimeError(f"Error de Vertex AI ({resp.status_code}): {resp.text}")
            
            data = resp.json()

        # 7. Mapear y responder
        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError("La respuesta de Vertex AI no contiene candidates.")
        
        first_candidate = candidates[0]
        content_obj = first_candidate.get("content", {})
        parts_obj = content_obj.get("parts", [])
        completion_text = parts_obj[0].get("text", "") if parts_obj else ""

        usage_meta = data.get("usageMetadata", {})
        prompt_tokens = usage_meta.get("promptTokenCount", len(json.dumps(payload)) // 4)
        completion_tokens = usage_meta.get("candidatesTokenCount", len(completion_text) // 4)
        
        choices = [
            ChatCompletionResponseChoice(
                index=0,
                message=Message(role="assistant", content=completion_text),
                finish_reason=first_candidate.get("finishReason", "stop").lower()
            )
        ]
        
        usage = ChatCompletionResponseUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens
        )

        return ChatCompletionResponse(
            id=data.get("responseId", f"tenz-vertex-{uuid.uuid4().hex[:8]}"),
            created=int(time.time()),
            model=f"tenzor-dev ({config.CUSTOM_MODEL_NAME})",
            choices=choices,
            usage=usage
        )

    def _generate_custom_vertex_completion(
        self,
        messages: List[Message],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        system_prompt: str = SYSTEM_PROMPT
    ) -> ChatCompletionResponse:
        import time
        import uuid
        import httpx

        # 1. Obtener token de acceso
        token = self._get_vertex_token()

        # 2. Registrar actividad para evitar auto-apagado
        self.last_activity_time = time.time()

        # 3. Formatear prompt en ChatML (Qwen template)
        prompt = ""
        prompt += f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        for msg in messages:
            role = msg.role if msg.role in ["user", "assistant", "system"] else "user"
            prompt += f"<|im_start|>{role}\n{msg.content}<|im_end|>\n"
        prompt += "<|im_start|>assistant\n"

        # 4. Construir payload
        payload = {
            "instances": [
                {
                    "prompt": prompt
                }
            ],
            "parameters": {
                "temperature": temperature,
                "max_tokens": max_tokens or 2048,
                "stop": ["<|im_end|>", "<|im_start|>"]
            }
        }

        # 5. Enviar petición POST a :predict en el endpoint
        # El endpoint URL es: https://{region}-aiplatform.googleapis.com/v1/{endpoint_name}:predict
        url = f"https://{config.VERTEX_LOCATION}-aiplatform.googleapis.com/v1/{config.CUSTOM_MODEL_BACKING_NAME}:predict"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        logger.info(f"Llamando a predicción en Vertex AI Endpoint: {url}")
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                raise RuntimeError(f"Error de Vertex AI Endpoint ({resp.status_code}): {resp.text}")
            
            data = resp.json()

        predictions = data.get("predictions", [])
        if not predictions:
            raise RuntimeError("La respuesta del Endpoint no contiene predicciones.")
        
        raw_text = predictions[0]
        # Procesar y limpiar respuesta
        completion_text = raw_text
        # Si vLLM devuelve el prompt original, lo quitamos
        if completion_text.startswith(prompt):
            completion_text = completion_text[len(prompt):]
        
        # Eliminar etiquetas ChatML sobrantes si las hay
        for token in ["<|im_end|>", "<|im_start|>", "<|im_start|>assistant", "<|im_start|>user"]:
            completion_text = completion_text.replace(token, "")
        completion_text = completion_text.strip()

        # Estimar uso de tokens
        prompt_tokens = len(prompt) // 4
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
            id=f"tenz-nova-vertex-{uuid.uuid4().hex[:8]}",
            created=int(time.time()),
            model=config.CUSTOM_MODEL_NAME,
            choices=choices,
            usage=usage
        )

    def _get_vertex_token(self) -> str:
        import os
        import json
        from google.oauth2 import service_account
        import google.auth.transport.requests

        creds = None
        google_creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if google_creds_json:
            try:
                info = json.loads(google_creds_json)
                creds = service_account.Credentials.from_service_account_info(
                    info,
                    scopes=["https://www.googleapis.com/auth/cloud-platform"]
                )
            except Exception as e:
                logger.error(f"Error cargando GOOGLE_CREDENTIALS_JSON: {e}")
        
        if not creds:
            sa_paths = [
                "service_account.json",
                os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "service_account.json")
            ]
            for sa_path in sa_paths:
                if os.path.exists(sa_path):
                    try:
                        creds = service_account.Credentials.from_service_account_file(
                            sa_path,
                            scopes=["https://www.googleapis.com/auth/cloud-platform"]
                        )
                        break
                    except Exception as e:
                        logger.error(f"Error cargando credentials de {sa_path}: {e}")

        if not creds:
            raise RuntimeError("No se encontraron credenciales de Vertex AI (GOOGLE_CREDENTIALS_JSON o service_account.json).")

        auth_req = google.auth.transport.requests.Request()
        creds.refresh(auth_req)
        return creds.token

    def _vertex_api_url(self, resource_name: str, suffix: str = "") -> str:
        return f"https://{config.VERTEX_LOCATION}-aiplatform.googleapis.com/v1/{resource_name}{suffix}"

    def _vertex_endpoint_resource(self) -> str:
        if getattr(config, "VERTEX_ENDPOINT_RESOURCE", ""):
            return config.VERTEX_ENDPOINT_RESOURCE
        return f"projects/{config.VERTEX_PROJECT_ID}/locations/{config.VERTEX_LOCATION}/endpoints/{config.VERTEX_ENDPOINT_ID}"

    def _vertex_model_resource(self) -> str:
        model_resource = getattr(config, "VERTEX_MODEL_RESOURCE", "")
        if model_resource:
            return model_resource

        model_resource = f"projects/{config.VERTEX_PROJECT_ID}/locations/{config.VERTEX_LOCATION}/models/{config.VERTEX_MODEL_ID}"
        if config.VERTEX_MODEL_VERSION:
            return f"{model_resource}@{config.VERTEX_MODEL_VERSION}"
        return model_resource

    def _vertex_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_vertex_token()}",
            "Content-Type": "application/json"
        }

    def _operation_matches_model_lifecycle(self, op: Dict[str, Any]) -> bool:
        metadata = op.get("metadata") or {}
        metadata_text = str(metadata)
        op_type = metadata.get("@type", "")
        endpoint_resource = self._vertex_endpoint_resource()
        model_resource = self._vertex_model_resource().split("@", 1)[0]

        is_lifecycle_operation = any(name in op_type for name in ("DeployModel", "UndeployModel"))
        mentions_target = endpoint_resource in metadata_text or model_resource in metadata_text
        return is_lifecycle_operation and mentions_target

    def _operation_lifecycle_kind(self, op: Dict[str, Any]) -> Optional[str]:
        op_type = (op.get("metadata") or {}).get("@type", "")
        if "UndeployModel" in op_type:
            return "undeploy"
        if "DeployModel" in op_type:
            return "deploy"
        return None

    def _get_endpoint_deployed_models(self, headers: Dict[str, str]) -> Optional[List[Dict[str, Any]]]:
        import httpx

        endpoint_url = self._vertex_api_url(self._vertex_endpoint_resource())
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(endpoint_url, headers=headers)
            if resp.status_code != 200:
                logger.error(f"Error consultando endpoint en Vertex AI ({resp.status_code}): {resp.text}")
                return None
            data = resp.json()
            return data.get("deployedModels", [])

    def get_model_status(self) -> str:
        import httpx

        try:
            headers = self._vertex_headers()
        except Exception as e:
            logger.error(f"Error obteniendo token para el estado: {e}")
            self.current_op_error = f"Error de autenticacion GCP: {e}"
            return "error"

        try:
            deployed_models = self._get_endpoint_deployed_models(headers)
            if deployed_models:
                self.current_op_name = None
                self.current_op_kind = None
                self.current_op_error = None
                return "active"
        except Exception as e:
            logger.error(f"Excepcion consultando endpoint: {e}")

        if self.current_op_name:
            op_url = self._vertex_api_url(self.current_op_name)
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.get(op_url, headers=headers)
                    if resp.status_code == 200:
                        op_data = resp.json()
                        if not op_data.get("done"):
                            return "sleeping" if self.current_op_kind == "undeploy" else "waking"

                        finished_kind = self.current_op_kind
                        self.current_op_name = None
                        self.current_op_kind = None
                        if "error" in op_data:
                            self.current_op_error = str(op_data["error"])
                            logger.error(f"La operacion de lifecycle Vertex fallo: {self.current_op_error}")
                            return "error"

                        deployed_models = self._get_endpoint_deployed_models(headers)
                        if deployed_models:
                            self.current_op_error = None
                            return "active"

                        if finished_kind == "undeploy":
                            self.current_op_error = None
                            return "sleep"

                        # La LRO puede finalizar unos segundos antes de que el endpoint refleje deployedModels.
                        return "waking"
                    logger.error(f"Error consultando operacion ({resp.status_code}): {resp.text}")
            except Exception as e:
                logger.error(f"Excepcion consultando operacion de lifecycle: {e}")

        try:
            list_ops_url = self._vertex_api_url(
                f"projects/{config.VERTEX_PROJECT_ID}/locations/{config.VERTEX_LOCATION}/operations"
            )
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(list_ops_url, headers=headers)
                if resp.status_code == 200:
                    ops_data = resp.json()
                    for op in ops_data.get("operations", []):
                        if not op.get("done") and self._operation_matches_model_lifecycle(op):
                            self.current_op_name = op.get("name")
                            self.current_op_kind = self._operation_lifecycle_kind(op)
                            return "sleeping" if self.current_op_kind == "undeploy" else "waking"
        except Exception as e:
            logger.error(f"Error listando operaciones del proyecto: {e}")

        return "error" if self.current_op_error else "sleep"

    def wake_model(self) -> dict:
        import httpx

        status = self.get_model_status()
        if status == "active":
            return {"status": "active", "message": "El modelo ya esta activo."}
        if status == "waking":
            return {"status": "waking", "message": "El modelo se esta activando actualmente."}

        try:
            headers = self._vertex_headers()
        except Exception as e:
            return {"status": "error", "message": f"Error de autenticacion GCP: {str(e)}"}

        deploy_url = self._vertex_api_url(self._vertex_endpoint_resource(), ":deployModel")
        payload = {
            "deployedModel": {
                "model": self._vertex_model_resource(),
                "displayName": config.VERTEX_DEPLOYED_MODEL_DISPLAY_NAME,
                "dedicatedResources": {
                    "machineSpec": {
                        "machineType": config.VERTEX_MACHINE_TYPE,
                        "acceleratorType": config.VERTEX_ACCELERATOR_TYPE,
                        "acceleratorCount": config.VERTEX_ACCELERATOR_COUNT,
                    },
                    "minReplicaCount": 1,
                    "maxReplicaCount": 1,
                },
            }
        }

        try:
            logger.info("Enviando peticion de despliegue a Vertex AI (Wake-on-Demand)...")
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(deploy_url, json=payload, headers=headers)
                if resp.status_code in [200, 202]:
                    op_data = resp.json()
                    self.current_op_name = op_data.get("name")
                    self.current_op_kind = "deploy"
                    self.current_op_error = None
                    self.last_activity_time = time.time()
                    logger.info(f"Despliegue iniciado correctamente. LRO: {self.current_op_name}")
                    return {
                        "status": "waking",
                        "message": "Activacion iniciada con exito. La GPU se esta levantando.",
                        "operation": self.current_op_name,
                    }

                self.current_op_error = resp.text
                logger.error(f"Error enviando peticion de despliegue ({resp.status_code}): {resp.text}")
                return {
                    "status": "error",
                    "message": f"Error al iniciar el despliegue en Vertex AI: {resp.text}",
                }
        except Exception as e:
            self.current_op_error = str(e)
            logger.error(f"Excepcion en wake_model: {e}")
            return {"status": "error", "message": f"Error interno en el servidor: {str(e)}"}

    def sleep_model(self) -> dict:
        import httpx

        try:
            headers = self._vertex_headers()
        except Exception as e:
            return {"status": "error", "message": f"Error de autenticacion GCP: {str(e)}"}

        endpoint_url = self._vertex_api_url(self._vertex_endpoint_resource())
        undeploy_url = f"{endpoint_url}:undeployModel"

        try:
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(endpoint_url, headers=headers)
                if resp.status_code != 200:
                    return {"status": "error", "message": f"Error consultando el endpoint: {resp.text}"}

                deployed_models = resp.json().get("deployedModels", [])
                if not deployed_models:
                    self.current_op_name = None
                    self.current_op_kind = None
                    self.current_op_error = None
                    return {"status": "sleep", "message": "El modelo ya esta en reposo."}

                undeployed_count = 0
                operation_name = None
                for model in deployed_models:
                    deployed_model_id = model.get("id")
                    if not deployed_model_id:
                        continue

                    und_resp = client.post(
                        undeploy_url,
                        json={"deployedModelId": deployed_model_id},
                        headers=headers,
                    )
                    if und_resp.status_code in [200, 202]:
                        undeployed_count += 1
                        operation_name = und_resp.json().get("name") or operation_name
                    else:
                        logger.error(f"Error apagando modelo {deployed_model_id} ({und_resp.status_code}): {und_resp.text}")

                if undeployed_count:
                    self.current_op_name = operation_name
                    self.current_op_kind = "undeploy"
                    self.current_op_error = None
                    return {
                        "status": "sleeping",
                        "message": f"Se ha solicitado apagar el modelo. Desasociados {undeployed_count} modelos del endpoint.",
                        "operation": operation_name,
                    }

                return {"status": "error", "message": "No se pudo desasociar ningun modelo del endpoint."}
        except Exception as e:
            self.current_op_error = str(e)
            logger.error(f"Excepcion en sleep_model: {e}")
            return {"status": "error", "message": f"Error interno al apagar la GPU: {str(e)}"}

    def check_idle_shutdown(self) -> None:
        """
        Verifica el tiempo de inactividad. Si se supera el límite configurado (VERTEX_AUTOSHUTDOWN_MINUTES),
        apaga la GPU automáticamente desasociando el modelo del endpoint.
        """
        if config.CUSTOM_MODEL_PROVIDER != "vertexai":
            return

        try:
            status = self.get_model_status()
            if status == "waking":
                # Mientras se está levantando el modelo, reseteamos el temporizador de actividad
                # para que no cuente el tiempo de despliegue/descarga como inactividad.
                self.last_activity_time = time.time()
                return

            elapsed_minutes = (time.time() - self.last_activity_time) / 60.0
            if elapsed_minutes >= config.VERTEX_AUTOSHUTDOWN_MINUTES:
                if status == "active":
                    logger.info(f"Inactividad detectada ({elapsed_minutes:.1f} minutos). Apagando modelo para ahorrar costes...")
                    self.sleep_model()
        except Exception as e:
            logger.error(f"Error durante el auto-apagado por inactividad: {e}")
