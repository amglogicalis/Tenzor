"""
aft_models.py
Modelos Pydantic del sistema AFT (Adaptive Fractal Tuning).
Definen la estructura y validación estricta del perfil compilado de un agente.

El AFT Profile es la representación canónica de un agente especializado.
No modifica pesos del modelo: es una capa de especialización operacional,
auditable y reversible mediante versionado.
"""
import re
from typing import Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from datetime import datetime, timezone


# ─── Sub-modelos del perfil ────────────────────────────────────────────────────

class BehaviorExample(BaseModel):
    """
    Ejemplo de comportamiento few-shot de alta calidad.
    Cada ejemplo enseña al modelo cómo debe responder en su dominio.
    """
    input: str = Field(..., min_length=5, description="Pregunta o input del usuario")
    output: str = Field(..., min_length=20, description="Respuesta ideal del agente")
    reasoning: Optional[str] = Field(
        None,
        description="Razonamiento interno de por qué esta respuesta es la correcta (no se muestra al usuario)"
    )

    @field_validator("input", "output")
    @classmethod
    def no_placeholder(cls, v: str) -> str:
        placeholders = [
            "[input]", "[output]", "[ejemplo]", "[aquí]", "...",
            "[input aquí]", "[output aquí]", "[respuesta]", "placeholder",
            "<input>", "<output>", "<example>",
        ]
        v_lower = v.lower()
        if any(p in v_lower for p in placeholders):
            raise ValueError(f"El campo contiene un placeholder sin rellenar: '{v[:80]}'")
        return v.strip()


class StyleRules(BaseModel):
    """
    Reglas de estilo y formato de respuesta del agente.
    Controlan el tono, longitud, formato y convenciones de código.
    """
    tone: str = Field(
        ...,
        min_length=5,
        description="Tono del agente. Ej: 'técnico y preciso', 'didáctico y accesible'"
    )
    response_format: str = Field(
        ...,
        description="Formato preferido. Ej: 'markdown con bloques de código', 'texto plano estructurado'"
    )
    verbosity: str = Field(
        ...,
        pattern=r"^(conciso|detallado|adaptativo)$",
        description="Nivel de detalle de las respuestas"
    )
    code_style: Optional[str] = Field(
        None,
        description="Convenciones de código si aplica. Ej: 'PEP 8, type hints, docstrings'"
    )
    custom_rules: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Reglas adicionales específicas del agente"
    )

    @field_validator("custom_rules")
    @classmethod
    def rules_not_empty_strings(cls, v: list) -> list:
        cleaned = [r.strip() for r in v if r.strip()]
        return cleaned


class DomainConstraints(BaseModel):
    """
    Límites del dominio de conocimiento del agente.
    Define qué puede y qué no puede tratar, y con qué nivel de expertise.
    """
    allowed_topics: list[str] = Field(
        ...,
        min_length=2,
        description="Temas principales de expertise del agente"
    )
    forbidden_topics: list[str] = Field(
        default_factory=list,
        description="Temas que el agente debe declinar o redirigir"
    )
    expertise_level: str = Field(
        ...,
        pattern=r"^(junior|mid|senior|experto)$",
        description="Nivel de expertise asumido en las respuestas"
    )
    preferred_sources: list[str] = Field(
        default_factory=list,
        description="Fuentes de referencia preferidas. Ej: 'documentación oficial', 'RFC'"
    )
    language: str = Field(
        "español",
        description="Idioma principal de respuesta"
    )
    out_of_scope_response: str = Field(
        ...,
        min_length=20,
        description="Respuesta exacta que da el agente cuando se le pregunta algo fuera de su dominio"
    )

    @field_validator("allowed_topics", "forbidden_topics", "preferred_sources")
    @classmethod
    def strip_items(cls, v: list) -> list:
        return [item.strip() for item in v if item.strip()]


class RetrievalProfile(BaseModel):
    """
    Estrategia RAG del agente.
    Controla cuándo y cómo buscar en la base de conocimiento.
    """
    trigger_keywords: list[str] = Field(
        ...,
        min_length=3,
        description="Palabras clave que activan la búsqueda en la knowledge base"
    )
    always_retrieve: bool = Field(
        False,
        description="Si True, siempre busca en la knowledge base antes de responder"
    )
    top_k: int = Field(
        5,
        ge=1,
        le=20,
        description="Número de chunks a recuperar por consulta"
    )
    context_injection: str = Field(
        "prefix",
        pattern=r"^(prefix|inline|suffix)$",
        description="Cómo inyectar el contexto recuperado en el prompt"
    )
    relevance_threshold: float = Field(
        0.6,
        ge=0.0,
        le=1.0,
        description="Umbral mínimo de relevancia para incluir un chunk (0=todo, 1=exacto)"
    )

    @field_validator("trigger_keywords")
    @classmethod
    def strip_keywords(cls, v: list) -> list:
        return [k.strip().lower() for k in v if k.strip()]


# ─── Perfil AFT principal ──────────────────────────────────────────────────────

class AFTProfile(BaseModel):
    """
    Perfil AFT (Adaptive Fractal Tuning) completo de un agente.
    Es la representación canónica que define cómo se especializa el agente.
    """
    system_instructions: str = Field(
        ...,
        min_length=300,
        max_length=8000,
        description="Prompt maestro compilado. Rico en contexto, reglas y ejemplos de comportamiento."
    )
    behavior_examples: list[BehaviorExample] = Field(
        ...,
        min_length=10,
        description="10-15 ejemplos few-shot de alta calidad y variedad"
    )
    style_rules: StyleRules
    domain_constraints: DomainConstraints
    retrieval_profile: RetrievalProfile
    aft_version: str = Field("1.0", description="Versión del esquema AFT usado")
    compiled_at: Optional[str] = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp de compilación"
    )

    @model_validator(mode="after")
    def check_examples_variety(self) -> "AFTProfile":
        """
        Valida:
        - No más de 15 ejemplos (límite de calidad).
        - Los inputs no pueden ser casi idénticos entre sí.
        """
        if len(self.behavior_examples) > 15:
            raise ValueError(
                f"Se permiten máximo 15 behavior_examples, se recibieron {len(self.behavior_examples)}."
            )
        inputs = [ex.input.lower().strip() for ex in self.behavior_examples]
        seen = set()
        duplicates = []
        for inp in inputs:
            fp = inp[:50]
            if fp in seen:
                duplicates.append(fp)
            seen.add(fp)
        if duplicates:
            raise ValueError(
                f"Los behavior_examples contienen inputs demasiado similares o duplicados: {duplicates[:3]}"
            )
        return self

    @field_validator("system_instructions")
    @classmethod
    def instructions_not_generic(cls, v: str) -> str:
        """Rechaza prompts que sean demasiado genéricos o estén incompletos."""
        generic_phrases = [
            "eres un asistente útil",
            "you are a helpful assistant",
            "responde preguntas",
            "[instrucciones aquí]",
            "fill in",
        ]
        lower = v.lower()
        for phrase in generic_phrases:
            if phrase in lower and len(v) < 500:
                raise ValueError(
                    "Las system_instructions son demasiado genéricas. "
                    "Deben ser específicas, ricas en contexto y al menos 300 caracteres."
                )
        return v.strip()

    def to_agent_version_dict(self) -> dict:
        """Convierte el perfil en el dict compatible con la tabla agent_versions."""
        return {
            "system_instructions": self.system_instructions,
            "behavior_examples": [ex.model_dump() for ex in self.behavior_examples],
            "style_rules": self.style_rules.model_dump(),
            "domain_constraints": self.domain_constraints.model_dump(),
            "retrieval_profile": self.retrieval_profile.model_dump(),
        }


# ─── Input del compilador ──────────────────────────────────────────────────────

class CompileProfileRequest(BaseModel):
    """Input del usuario para el compilador AFT."""
    agent_name: str = Field(..., min_length=2, max_length=100)
    description: str = Field(
        ...,
        min_length=50,
        max_length=3000,
        description="Descripción informal del agente: qué hace, cómo responde, su dominio"
    )
    category: str = Field(..., pattern=r"^(dev|data|ops|creative|science|custom)$")
    base_tier: str = Field("balanced", pattern=r"^(fast|balanced|pro)$")
    language: str = Field("español", description="Idioma de las respuestas del agente")
    user_examples: Optional[list[dict]] = Field(
        None,
        max_length=5,
        description="Hasta 5 ejemplos opcionales aportados por el usuario (input/output)"
    )
    # Si True, sobreescribe la versión activa. Si False, crea versión nueva (default).
    replace_current: bool = False
