"""
crew_service.py
Arzor DevCrew — orquestador de desarrollo asistido por IA.

Flujo:
  /plan  → Recibe una descripción de tarea y devuelve:
             - Un plan de implementación estructurado (lista de pasos).
             - Estimación de complejidad y tiempo.
             - Archivos a crear/modificar (mapa de cambios).
           Usa el primer agente disponible del usuario (tier balanced o pro).
           Si el usuario pasa agent_id, usa ese agente concreto.

  /write → Recibe un paso del plan + contexto de código y devuelve:
             - El código generado para ese paso.
             - El nombre del archivo de destino.
             - Instrucciones de integración.

El DevCrew no ejecuta código: genera el plan y el código, el desarrollador
revisa y aplica. Es una herramienta de aumento de capacidad, no de autonomía.
"""
import logging
from typing import Optional, List
from supabase import create_client, Client
from app import config
from app.services.provider_router_service import provider_router, InferenceError

logger = logging.getLogger(__name__)


# ─── Prompts ──────────────────────────────────────────────────────────────────

_PLAN_SYSTEM = """\
Eres DevCrew, un arquitecto de software senior especializado en planificación \
de tareas de desarrollo. Tu misión es analizar una solicitud de desarrollo y \
producir un plan de implementación claro, estructurado y accionable.

Reglas:
- Sé concreto: nombra archivos reales, clases, funciones.
- Usa terminología técnica precisa.
- Ordena los pasos por dependencia (lo que se debe hacer primero va primero).
- Responde ÚNICAMENTE en el formato JSON indicado, sin texto extra.
"""

_PLAN_USER = """\
Tarea de desarrollo:
{task}

Tecnologías del proyecto:
{tech_stack}

Contexto adicional (opcional):
{context}

Genera un plan de implementación en este formato JSON exacto:
{{
  "summary": "Resumen ejecutivo en 1-2 frases",
  "complexity": "low | medium | high",
  "estimated_hours": <número>,
  "steps": [
    {{
      "id": 1,
      "title": "Título del paso",
      "description": "Descripción detallada",
      "files": ["ruta/archivo.py"],
      "type": "create | modify | delete | config | test"
    }}
  ],
  "risks": ["riesgo 1", "riesgo 2"],
  "dependencies": ["paquete o servicio requerido"]
}}
"""

_WRITE_SYSTEM = """\
Eres DevCrew, un desarrollador senior experto. Tu misión es generar código \
de alta calidad para un paso específico de un plan de implementación.

Reglas:
- Genera código completo y funcional, listo para copiar y pegar.
- Incluye todos los imports necesarios.
- Añade docstrings y comentarios donde sea útil.
- No generes placeholders: todo el código debe ser real e implementado.
- Responde ÚNICAMENTE en el formato JSON indicado, sin texto extra.
"""

_WRITE_USER = """\
Paso a implementar:
{step_title}

Descripción:
{step_description}

Archivos de destino: {files}

Código existente (contexto):
{existing_code}

Instrucciones del agente:
{agent_instructions}

Genera el código en este formato JSON exacto:
{{
  "file": "ruta/del/archivo/principal.py",
  "language": "python | typescript | sql | yaml | other",
  "code": "...código completo...",
  "integration_notes": "Instrucciones para integrar este código",
  "test_hints": ["Qué probar", "Qué casos cubrir"]
}}
"""


_REACT_SYSTEM = """\
Eres Arzor Agent, un desarrollador autónomo senior. Estás ejecutando tareas de desarrollo directamente en el ordenador local del usuario.
Tu objetivo es completar la tarea del usuario utilizando las herramientas locales que se te proporcionan.

Reglas críticas de comportamiento:
1. Analiza con cuidado el directorio antes de escribir código o tomar decisiones. Utiliza list_directory o read_file_content si necesitas entender el contexto.
2. Si creas o modificas código, escribe código funcional, completo y real (no placeholders ni comentarios de "escribir aquí").
3. Tras realizar cambios, intenta siempre ejecutar tests o comandos de validación (por ejemplo, execute_system_command con "pytest" o similar) para verificar tu trabajo.
4. Si un comando o test falla, lee el error de stdout/stderr y corrígelo de inmediato.
5. Cuando la tarea esté totalmente finalizada y verificada, responde con action = "finish".

Debes responder ÚNICAMENTE en el siguiente formato JSON, sin añadir texto libre antes ni después:
{{
  "thought": "Tu razonamiento paso a paso sobre el estado actual y lo que planeas hacer a continuación.",
  "action": "list_directory | read_file_content | write_file_content | edit_file_content | execute_system_command | finish",
  "args": {{
    // Si la acción es list_directory:
    //   "path": "ruta/al/directorio" (opcional, por defecto ".")
    // Si la acción es read_file_content:
    //   "path": "ruta/al/archivo"
    // Si la acción es write_file_content:
    //   "path": "ruta/al/archivo", "content": "contenido completo del archivo"
    // Si la acción es edit_file_content:
    //   "path": "ruta/al/archivo", "target_text": "texto exacto a reemplazar", "replacement_text": "nuevo texto"
    // Si la acción es execute_system_command:
    //   "command": "comando de consola a ejecutar"
    // Si la acción es finish:
    //   "message": "Resumen final detallado del trabajo realizado"
  }}
}}
"""


class DevCrewService:
    """Orquestador DevCrew: plan y generación de código asistido por IA."""

    def __init__(self):
        self._sb: Optional[Client] = None
        if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
            try:
                self._sb = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
            except Exception as e:
                logger.error(f"DevCrewService: error Supabase: {e}")
        elif config.SUPABASE_URL and config.SUPABASE_KEY:
            self._sb = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

    # ──────────────────────────────────────────────────────────────────────────
    # PLAN
    # ──────────────────────────────────────────────────────────────────────────

    def generate_plan(
        self,
        user_id: str,
        task: str,
        tech_stack: str = "Python, FastAPI, Supabase",
        context: str = "",
        agent_id: Optional[str] = None,
        tier: str = "balanced",
    ) -> dict:
        """
        Genera un plan de implementación estructurado para una tarea de desarrollo.

        Args:
            user_id:    UUID del usuario.
            task:       Descripción de la tarea a implementar.
            tech_stack: Tecnologías del proyecto (ej. "Python, FastAPI, React").
            context:    Contexto adicional (arquitectura, restricciones, etc.).
            agent_id:   UUID del agente a usar (opcional). Si None, usa tier por defecto.
            tier:       Tier del provider si no se especifica agente.

        Returns:
            dict con el plan de implementación.
        """
        if len(task.strip()) < 10:
            raise ValueError("La descripción de la tarea debe tener al menos 10 caracteres.")

        instructions = self._load_agent_instructions(agent_id, user_id) if agent_id else None
        system = instructions or _PLAN_SYSTEM

        prompt = _PLAN_USER.format(
            task=task,
            tech_stack=tech_stack,
            context=context or "No hay contexto adicional.",
        )

        try:
            result = provider_router.infer(
                messages=[{"role": "user", "content": prompt}],
                tier=tier,
                user_id=user_id,
                system_prompt=system,
                temperature=0.3,   # baja temp para planes precisos
                max_tokens=2000,
            )
            plan = self._parse_json_response(result.content)
            plan["_meta"] = {
                "provider": result.provider,
                "model": result.model,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "latency_ms": result.latency_ms,
            }
            return plan
        except InferenceError as e:
            raise ValueError(f"Error al generar el plan: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # WRITE
    # ──────────────────────────────────────────────────────────────────────────

    def generate_code(
        self,
        user_id: str,
        step_title: str,
        step_description: str,
        files: List[str],
        existing_code: str = "",
        agent_id: Optional[str] = None,
        tier: str = "balanced",
    ) -> dict:
        """
        Genera el código para un paso concreto del plan.

        Args:
            user_id:          UUID del usuario.
            step_title:       Título del paso (del plan).
            step_description: Descripción detallada del paso.
            files:            Lista de archivos a crear/modificar.
            existing_code:    Código existente en el archivo (contexto).
            agent_id:         UUID del agente (opcional).
            tier:             Tier del provider.

        Returns:
            dict con el código generado, archivo de destino e instrucciones.
        """
        if not step_title or not step_description:
            raise ValueError("Título y descripción del paso son requeridos.")

        instructions = self._load_agent_instructions(agent_id, user_id) if agent_id else None
        system = instructions or _WRITE_SYSTEM

        prompt = _WRITE_USER.format(
            step_title=step_title,
            step_description=step_description,
            files=", ".join(files) if files else "según el paso",
            existing_code=existing_code[:3000] if existing_code else "(archivo nuevo)",
            agent_instructions=instructions or "Genera código limpio y bien documentado.",
        )

        try:
            result = provider_router.infer(
                messages=[{"role": "user", "content": prompt}],
                tier=tier,
                user_id=user_id,
                system_prompt=system,
                temperature=0.2,   # muy baja: código debe ser determinista
                max_tokens=3000,
            )
            code_result = self._parse_json_response(result.content)
            code_result["_meta"] = {
                "provider": result.provider,
                "model": result.model,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "latency_ms": result.latency_ms,
            }
            return code_result
        except InferenceError as e:
            raise ValueError(f"Error al generar el código: {e}")

    def agent_step(
        self,
        user_id: str,
        messages: List[dict],
        tier: str = "balanced",
        agent_id: Optional[str] = None,
    ) -> dict:
        """
        Recibe el historial de la conversación del agente autónomo local,
        aplica el prompt de sistema del agente ReAct y devuelve el pensamiento
        y acción de la herramienta en formato estructurado.
        """
        if not messages:
            raise ValueError("El historial de mensajes no puede estar vacío.")

        instructions = self._load_agent_instructions(agent_id, user_id) if agent_id else None
        system_prompt = instructions or _REACT_SYSTEM

        try:
            result = provider_router.infer(
                messages=messages,
                tier=tier,
                user_id=user_id,
                system_prompt=system_prompt,
                temperature=0.2,   # baja temperatura para consistencia de JSON
                max_tokens=3000,
            )
            
            step_result = self._parse_json_response(result.content)
            # Asegurar estructura mínima si el parser falló
            if "error" in step_result and "raw_response" in step_result:
                # Si falló el JSON, intentamos forzar un finish con la respuesta cruda para no colgar el cliente
                step_result = {
                    "thought": "Error de parseo JSON del LLM.",
                    "action": "finish",
                    "args": {"message": step_result["raw_response"]}
                }
            
            step_result["_meta"] = {
                "provider": result.provider,
                "model": result.model,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "latency_ms": result.latency_ms,
            }
            return step_result
        except InferenceError as e:
            raise ValueError(f"Error de inferencia en el agente: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    def _load_agent_instructions(self, agent_id: str, user_id: str) -> Optional[str]:
        """Carga las instrucciones del agente AFT desde Supabase."""
        if not self._sb:
            return None
        try:
            resp = (
                self._sb.table("custom_agents")
                .select("name, current_version_id")
                .eq("id", agent_id)
                .is_("deleted_at", "null")
                .execute()
            )
            if not resp.data:
                return None
            agent = resp.data[0]
            if agent.get("current_version_id"):
                ver = (
                    self._sb.table("agent_versions")
                    .select("system_instructions")
                    .eq("id", agent["current_version_id"])
                    .execute()
                )
                if ver.data and ver.data[0].get("system_instructions"):
                    return ver.data[0]["system_instructions"]
        except Exception as e:
            logger.warning(f"DevCrewService: no se pudo cargar el agente {agent_id}: {e}")
        return None

    def _parse_json_response(self, content: str) -> dict:
        """
        Extrae y parsea el JSON de la respuesta del LLM.
        El LLM puede añadir markdown code fences (```json ... ```) — las limpiamos.
        """
        import json
        import re
        cleaned = content.strip()
        # Eliminar code fences si existen
        match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)
        else:
            # Buscar el primer { y el último }
            start = cleaned.find('{')
            end = cleaned.rfind('}')
            if start != -1 and end != -1:
                cleaned = cleaned[start:end+1]
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Si el LLM no respetó el formato JSON, devolver en crudo
            logger.warning("DevCrewService: respuesta no es JSON válido, devolviendo raw.")
            return {"raw_response": content, "error": "El LLM no respetó el formato JSON."}
