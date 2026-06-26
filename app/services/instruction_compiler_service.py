"""
instruction_compiler_service.py
AFT Compiler — Adaptive Fractal Tuning.

Convierte la descripción informal de un agente en un perfil AFT estructurado,
validado y listo para ser guardado como versión en agent_versions.

Estrategia de compilación:
  1. Meta-prompt altamente ingeniado → Gemini genera JSON estructurado.
  2. Extracción robusta de JSON (maneja markdown, texto suelto, bloques parciales).
  3. Validación Pydantic estricta (AFTProfile).
  4. Hasta 3 intentos con backoff exponencial + jitter.
  5. En el intento 3: prompt de reparación dirigida (muestra el error al modelo).
  6. Resultado: AFTProfile validado o excepción con razón clara.

El AFT NO modifica pesos del modelo. Es especialización operacional,
auditable y reversible mediante versionado.
"""
import re
import json
import time
import random
import logging
from typing import Optional
from pydantic import ValidationError

import google.generativeai as genai
from app import config
from app.services.aft_models import AFTProfile, CompileProfileRequest

logger = logging.getLogger(__name__)

# ─── Constantes ───────────────────────────────────────────────────────────────

MAX_ATTEMPTS = 3
BACKOFF_BASE = 2.0          # segundos base del backoff exponencial
BACKOFF_JITTER = 0.8        # factor de jitter aleatorio (±40%)
COMPILER_MODEL = "gemini-2.5-flash"   # Modelo por defecto del compilador
COMPILER_TEMPERATURE = 0.25  # Baja temperatura para consistencia estructural


# ─── Meta-prompt del compilador ───────────────────────────────────────────────

_META_SYSTEM_PROMPT = """\
Eres el compilador AFT (Adaptive Fractal Tuning) de la plataforma Arzor.
Tu función exclusiva es transformar la descripción informal de un agente de IA en un
perfil de especialización estructurado, denso y de alta calidad.

REGLAS ABSOLUTAS:
1. Responde ÚNICAMENTE con un objeto JSON válido. Sin texto previo, sin markdown, sin explicaciones.
2. El JSON debe seguir exactamente el schema indicado. Sin campos extra, sin omisiones.
3. Los behavior_examples deben ser REALES, VARIADOS y ESPECÍFICOS del dominio descrito.
   - No uses ejemplos genéricos como "¿Cómo estás?" o "¿Qué puedes hacer?".
   - Cada ejemplo debe mostrar un caso de uso real del agente.
   - Los outputs deben ser ricos, técnicos y demostrar verdadera expertise.
4. Las system_instructions deben ser un prompt maestro completo (mínimo 400 caracteres):
   - Identidad clara del agente.
   - Dominio de conocimiento específico.
   - Comportamiento en casos borde (preguntas fuera de dominio, ambigüedad, etc.).
   - Formato de respuesta esperado.
   - Nivel de expertise asumido.
5. NUNCA dejes campos con placeholders, arrays vacíos obligatorios o valores genéricos.
6. El idioma de los ejemplos y respuestas debe coincidir con el campo `language` indicado.
"""

_JSON_SCHEMA = """\
{
  "system_instructions": "<string: prompt maestro completo, mínimo 400 chars>",
  "behavior_examples": [
    {
      "input": "<pregunta real del usuario, específica del dominio>",
      "output": "<respuesta completa y experta del agente>",
      "reasoning": "<por qué esta respuesta es la correcta para este agente>"
    }
    // ... exactamente 12 ejemplos (mínimo 10, máximo 15)
  ],
  "style_rules": {
    "tone": "<descripción del tono: técnico/didáctico/formal/etc.>",
    "response_format": "<formato: markdown con código / texto estructurado / etc.>",
    "verbosity": "conciso | detallado | adaptativo",
    "code_style": "<convenciones de código o null si no aplica>",
    "custom_rules": ["<regla específica 1>", "<regla específica 2>", "..."]
  },
  "domain_constraints": {
    "allowed_topics": ["<tema principal 1>", "<tema principal 2>", "..."],
    "forbidden_topics": ["<tema prohibido 1>", "..."],
    "expertise_level": "junior | mid | senior | experto",
    "preferred_sources": ["<fuente 1>", "..."],
    "language": "<idioma de respuesta>",
    "out_of_scope_response": "<respuesta exacta cuando preguntan fuera del dominio>"
  },
  "retrieval_profile": {
    "trigger_keywords": ["<keyword 1>", "<keyword 2>", "... (mínimo 5)"],
    "always_retrieve": false,
    "top_k": 5,
    "context_injection": "prefix | inline | suffix",
    "relevance_threshold": 0.6
  }
}"""


def _build_compile_prompt(req: CompileProfileRequest, error_hint: Optional[str] = None) -> str:
    """Construye el prompt de usuario para el compilador."""
    user_examples_block = ""
    if req.user_examples:
        examples_str = "\n".join(
            f"  - INPUT: {ex.get('input', '')}\n    OUTPUT: {ex.get('output', '')}"
            for ex in req.user_examples[:5]
        )
        user_examples_block = f"""
EJEMPLOS APORTADOS POR EL USUARIO (úsalos como base e inspírate en ellos, pero crea 12 en total):
{examples_str}
"""

    error_block = ""
    if error_hint:
        error_block = f"""
⚠️ INTENTO ANTERIOR FALLIDO. ERRORES DE VALIDACIÓN A CORREGIR:
{error_hint}
Analiza los errores anteriores y genera el JSON corrigiéndolos.
"""

    return f"""Compila el siguiente agente en un perfil AFT completo.

DATOS DEL AGENTE:
- Nombre: {req.agent_name}
- Categoría: {req.category}
- Tier base: {req.base_tier}
- Idioma de respuesta: {req.language}
- Descripción del creador:
  \"{req.description}\"
{user_examples_block}{error_block}
SCHEMA JSON EXACTO A SEGUIR:
{_JSON_SCHEMA}

Genera ahora el JSON del perfil AFT. Recuerda: SOLO JSON, sin texto adicional."""


def _build_repair_prompt(partial_json: str, errors: str, req: CompileProfileRequest) -> str:
    """Prompt de reparación: muestra el JSON parcial y los errores para que el modelo lo corrija."""
    return f"""El siguiente JSON tiene errores de validación. Corrígelos y devuelve el JSON completo y válido.

ERRORES:
{errors}

JSON CON ERRORES (corrige SOLO lo necesario, mantén el resto):
{partial_json[:3000]}

AGENTE: {req.agent_name} | CATEGORÍA: {req.category} | IDIOMA: {req.language}

Devuelve ÚNICAMENTE el JSON corregido y completo. Sin texto adicional."""


# ─── Extracción robusta de JSON ────────────────────────────────────────────────

def _extract_json(text: str) -> str:
    """
    Extrae el bloque JSON de la respuesta del LLM con múltiples estrategias:
    1. Markdown code block (```json ... ```)
    2. Primer bloque {} de nivel raíz
    3. El texto completo como fallback
    """
    text = text.strip()

    # Estrategia 1: bloque markdown ```json
    md_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if md_match:
        return md_match.group(1).strip()

    # Estrategia 2: Primer { hasta el } correspondiente de cierre
    start = text.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escape_next = False
        for i, ch in enumerate(text[start:], start=start):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"' and not escape_next:
                in_string = not in_string
                continue
            if not in_string:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]

    # Fallback: texto completo
    return text


def _format_validation_errors(e: ValidationError) -> str:
    """Formatea los errores de Pydantic de forma legible para el prompt de reparación."""
    lines = []
    for err in e.errors():
        loc = " -> ".join(str(l) for l in err["loc"])
        lines.append(f"  • Campo '{loc}': {err['msg']} (valor recibido: {str(err.get('input', '?'))[:80]})")
    return "\n".join(lines)


# ─── Función principal de compilación ─────────────────────────────────────────

def compile_aft_profile(req: CompileProfileRequest) -> AFTProfile:
    """
    Compila el perfil AFT del agente descrito en `req`.

    Flujo:
      - Intento 1: compilación estándar
      - Intento 2: mismo prompt + hint del error anterior
      - Intento 3: prompt de reparación con JSON parcial + errores
      - Si los 3 fallan: lanza ValueError con el último error de validación

    Returns:
        AFTProfile validado y listo para guardar en agent_versions.

    Raises:
        ValueError: Si no se puede compilar un perfil válido tras 3 intentos.
        RuntimeError: Si Gemini no está configurado.
    """
    if not config.GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY no configurado. El compilador AFT requiere acceso a Gemini."
        )

    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name=COMPILER_MODEL,
        system_instruction=_META_SYSTEM_PROMPT,
        generation_config=genai.GenerationConfig(
            temperature=COMPILER_TEMPERATURE,
            max_output_tokens=8192,
        ),
    )

    last_error: Optional[Exception] = None
    last_raw: str = ""
    last_validation_error: Optional[str] = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        logger.info(f"AFT Compiler: intento {attempt}/{MAX_ATTEMPTS} para agente '{req.agent_name}'")

        # Construir el prompt según el intento
        if attempt < MAX_ATTEMPTS:
            prompt = _build_compile_prompt(req, error_hint=last_validation_error)
        else:
            # Último intento: prompt de reparación con el JSON anterior
            prompt = _build_repair_prompt(
                partial_json=last_raw,
                errors=last_validation_error or "JSON inválido o incompleto",
                req=req,
            )

        try:
            response = model.generate_content(prompt)
            raw_text = response.text
            last_raw = raw_text

            logger.debug(f"AFT Compiler: respuesta del modelo ({len(raw_text)} chars)")

            # Extraer JSON
            json_str = _extract_json(raw_text)

            # Parsear JSON
            try:
                data = json.loads(json_str)
            except json.JSONDecodeError as je:
                raise ValueError(f"JSON inválido: {je}. Primeros 200 chars: {json_str[:200]}")

            # Validar con Pydantic
            profile = AFTProfile(**data)
            logger.info(
                f"AFT Compiler: perfil compilado exitosamente en intento {attempt}. "
                f"{len(profile.behavior_examples)} ejemplos, "
                f"{len(profile.system_instructions)} chars en instrucciones."
            )
            return profile

        except ValidationError as ve:
            last_error = ve
            last_validation_error = _format_validation_errors(ve)
            logger.warning(f"AFT Compiler intento {attempt}: errores de validación:\n{last_validation_error}")

        except ValueError as ve:
            last_error = ve
            last_validation_error = str(ve)
            logger.warning(f"AFT Compiler intento {attempt}: {ve}")

        except Exception as e:
            last_error = e
            last_validation_error = f"Error inesperado: {e}"
            logger.error(f"AFT Compiler intento {attempt}: error inesperado: {e}")

        # Backoff exponencial con jitter antes del siguiente intento
        if attempt < MAX_ATTEMPTS:
            wait = BACKOFF_BASE ** attempt * (1 + random.uniform(-BACKOFF_JITTER / 2, BACKOFF_JITTER / 2))
            wait = max(0.5, wait)
            logger.info(f"AFT Compiler: esperando {wait:.1f}s antes del siguiente intento...")
            time.sleep(wait)

    # Si llegamos aquí, los 3 intentos fallaron
    raise ValueError(
        f"El compilador AFT no pudo generar un perfil válido tras {MAX_ATTEMPTS} intentos. "
        f"Último error: {last_validation_error}"
    )


# ─── Wrapper con integración al AgentService ──────────────────────────────────

def compile_and_save(
    req: CompileProfileRequest,
    agent_id: str,
    user_id: str,
) -> dict:
    """
    Compila el perfil AFT y lo guarda como nueva versión del agente.

    Returns:
        dict con {profile, version} donde version es el dict guardado en agent_versions.

    Raises:
        ValueError: si la compilación o el guardado fallan.
    """
    from app.services.agent_service import agent_service

    # 1. Compilar
    profile = compile_aft_profile(req)

    # 2. Guardar como nueva versión
    version_data = profile.to_agent_version_dict()
    new_version = agent_service.create_new_version(
        agent_id=agent_id,
        user_id=user_id,
        system_instructions=version_data["system_instructions"],
        behavior_examples=version_data["behavior_examples"],
        style_rules=version_data["style_rules"],
        domain_constraints=version_data["domain_constraints"],
        retrieval_profile=version_data["retrieval_profile"],
    )

    logger.info(f"AFT Compiler: perfil guardado como versión {new_version.get('version')} del agente {agent_id}")
    return {
        "profile": profile.model_dump(),
        "version": new_version,
    }
