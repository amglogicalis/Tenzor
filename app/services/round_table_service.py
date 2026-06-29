"""
round_table_service.py
Servicio de debate multi-agente Arzor Round Table.

Flujo de un debate:
  1. Usuario crea una mesa (POST /round-table) con un tema (topic).
  2. Añade entre 2 y 6 agentes como miembros, con turn_order definido.
  3. Llama a start() → el servicio orquesta el debate ronda a ronda:
       - Cada agente recibe el topic + el historial de turnos anteriores.
       - El system_prompt de cada agente se carga desde su versión AFT activa.
       - El provider_router gestiona la inferencia (Anti-429 incluido).
       - Cada turno se guarda en round_tables.result (JSONB).
  4. Al terminar, un moderador sintetiza el consenso/conclusiones.
  5. El resultado se guarda en round_tables.result y el status pasa a "done".

Límites de seguridad:
  - Mínimo 2 agentes, máximo 6.
  - Mínimo 1 ronda, máximo 5.
  - Máximo 400 tokens de respuesta por turno (para controlar coste y latencia).
"""
import json
import logging
from typing import Optional, List

from supabase import create_client, Client
from app import config
from app.services.provider_router_service import provider_router, InferenceError

logger = logging.getLogger(__name__)

# ─── Configuración del debate ─────────────────────────────────────────────────
MIN_AGENTS = 2
MAX_AGENTS = 6
MIN_ROUNDS = 1
MAX_ROUNDS = 9999
MAX_TOKENS_PER_TURN = 400
DEBATE_TEMPERATURE = 0.75


# ─── Prompts ──────────────────────────────────────────────────────────────────

_DEBATE_TURN_PROMPT = """\
Estás participando en un comité técnico ejecutivo llamado "Round Table" para debatir de forma pragmática sobre una propuesta.

TEMA A DISCUTIR:
{topic}

PARTICIPANTES EN LA MESA:
{participants_list}

HISTORIAL DEL DEBATE HASTA EL MOMENTO:
{history}

---
Es tu turno. Responde bajo las siguientes directrices estrictas:
- **Tono Profesional y Natural**: Habla como un experto real en una reunión técnica de nivel. No utilices saludos formales, disculpas, ni preámbulos de cortesía vacíos. Ve directo a la materia.
- **Defiende tu Especialidad y Objetivos**: El desacuerdo no debe ser artificial, sino nacer de tus prioridades en conflicto:
  * Si tu rol es MLOps/Dev/Science: Tu objetivo es maximizar la velocidad de innovación, despliegue y precisión de los modelos.
  * Si tu rol es SRE/Ops: Tu objetivo es la estabilidad operativa, disponibilidad del sistema, minimizar caídas y mitigar riesgos.
  * Si tu rol es Seguridad: Tu objetivo es la protección de datos, control de accesos y reducción de superficie de ataque.
  * Si tu rol es FinOps/Finanzas: Tu objetivo es el control de costes, optimización de recursos y ROI del cómputo.
- **Contraargumentación**: No te limites a exponer tu tema. Analiza críticamente el historial. Si un participante propone algo que pone en riesgo tus objetivos, exprésalo de forma inequívoca (ej: "No aprobaría este cambio", "Existe un riesgo inaceptable en esa propuesta", "Bloquearía este despliegue si no se añade redundancia"). Acepta únicamente argumentos sólidos.
- **Brevedad**: Sé conciso. Máximo 2 o 3 párrafos de lectura ágil.
- **Cierre Obligatorio**: Debes finalizar tu mensaje exactamente con esta estructura al final de tu intervención:
  Decisión: [✔ Apruebo | ⚠ Apruebo con condiciones | ✖ Rechazo]
  Motivo principal: [Una frase corta que resume tu decisión]
  — {agent_name}
"""

_SYNTHESIS_PROMPT = """\
Has moderado un debate técnico del comité ejecutivo sobre el siguiente tema:

TEMA DISCUTIDO:
{topic}

HISTORIAL COMPLETO DEL DEBATE:
{full_debate}

---
Actúas como el CTO de la compañía. Tu misión es tomar una decisión ejecutiva final basada en las posturas del comité. No puedes responder "depende" ni evitar decidir de forma neutral.

Genera tu veredicto con la siguiente estructura corporativa estricta:

1. **Decisión Ejecutiva (CTO Verdict)**: Elige de forma clara entre **APROBADO**, **APROBADO CON CONDICIONES** o **RECHAZADO**.
2. **Puntos Críticos**: Resumen de los principales conflictos técnicos y riesgos expuestos por los especialistas.
3. **Condiciones Obligatorias para Ingeniería**: Lista de requisitos numerados ineludibles que el equipo de desarrollo/sistemas debe cumplir obligatoriamente para proceder.

Sé conciso, corporativo y directo. Máximo 4 párrafos de resolución.
"""


class RoundTableTurn:
    """Representa un turno individual en el debate."""
    def __init__(self, agent_id: str, agent_name: str, round_num: int,
                 content: str, provider: str, model: str,
                 tokens_in: int, tokens_out: int, latency_ms: float):
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.round_num = round_num
        self.content = content
        self.provider = provider
        self.model = model
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.latency_ms = latency_ms

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "agent_name": self.agent_name,
            "round": self.round_num,
            "content": self.content,
            "provider": self.provider,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "latency_ms": self.latency_ms,
        }


class RoundTableResult:
    """Resultado completo de un debate."""
    def __init__(self, table_id: str, topic: str, turns: List[RoundTableTurn],
                 synthesis: str, total_tokens: int, total_latency_ms: float):
        self.table_id = table_id
        self.topic = topic
        self.turns = turns
        self.synthesis = synthesis
        self.total_tokens = total_tokens
        self.total_latency_ms = total_latency_ms

    def to_dict(self) -> dict:
        return {
            "table_id": self.table_id,
            "topic": self.topic,
            "turns": [t.to_dict() for t in self.turns],
            "synthesis": self.synthesis,
            "total_tokens": self.total_tokens,
            "total_latency_ms": self.total_latency_ms,
            "turn_count": len(self.turns),
        }


class RoundTableService:
    """
    Orquesta debates multi-agente con múltiples rondas.
    Integra system_instructions AFT de cada agente y el ProviderRouter.
    """

    def __init__(self):
        self._sb: Optional[Client] = None

        if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
            try:
                self._sb = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
                logger.info("RoundTableService: Supabase (service key) inicializado.")
            except Exception as e:
                logger.error(f"RoundTableService: error inicializando Supabase: {e}")
        elif config.SUPABASE_URL and config.SUPABASE_KEY:
            self._sb = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

    # ──────────────────────────────────────────────────────────────────────────
    # CRUD DE MESAS
    # ──────────────────────────────────────────────────────────────────────────

    def create_table(self, user_id: str, name: str,
                     description: Optional[str], topic: str) -> dict:
        """Crea una nueva mesa de debate en estado 'idle'."""
        if not self._sb:
            raise ValueError("Supabase no disponible.")
        if len(topic.strip()) < 10:
            raise ValueError("El tema del debate debe tener al menos 10 caracteres.")
        resp = (
            self._sb.table("round_tables")
            .insert({"user_id": user_id, "name": name,
                     "description": description, "topic": topic, "status": "idle"})
            .execute()
        )
        return resp.data[0]

    def list_tables(self, user_id: str, limit: int = 20) -> List[dict]:
        """Lista las mesas del usuario, más recientes primero."""
        if not self._sb:
            return []
        resp = (
            self._sb.table("round_tables")
            .select("*")
            .eq("user_id", user_id)
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        return resp.data or []

    def get_table(self, table_id: str, user_id: str) -> dict:
        """Obtiene una mesa verificando propiedad."""
        if not self._sb:
            raise ValueError("Supabase no disponible.")
        resp = (
            self._sb.table("round_tables")
            .select("*")
            .eq("id", table_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not resp.data:
            raise ValueError("Mesa no encontrada o sin acceso.")
        return resp.data[0]

    def delete_table(self, table_id: str, user_id: str) -> bool:
        """Borra una mesa y sus miembros (CASCADE)."""
        self.get_table(table_id, user_id)
        self._sb.table("round_tables").delete().eq("id", table_id).execute()
        return True

    # ──────────────────────────────────────────────────────────────────────────
    # GESTIÓN DE MIEMBROS
    # ──────────────────────────────────────────────────────────────────────────

    def add_member(self, table_id: str, user_id: str,
                   agent_id: str, turn_order: int = 0) -> dict:
        """Añade un agente a la mesa (máx. MAX_AGENTS, estado 'idle')."""
        table = self.get_table(table_id, user_id)
        if table["status"] != "idle":
            raise ValueError("Solo se pueden añadir miembros a mesas en estado 'idle'.")

        count_resp = (
            self._sb.table("round_table_members")
            .select("id", count="exact")
            .eq("table_id", table_id)
            .execute()
        )
        if (count_resp.count or 0) >= MAX_AGENTS:
            raise ValueError(f"Máximo {MAX_AGENTS} agentes por mesa.")

        self._load_agent(agent_id, user_id)  # verifica acceso

        resp = (
            self._sb.table("round_table_members")
            .upsert({"table_id": table_id, "agent_id": agent_id,
                     "turn_order": turn_order}, on_conflict="table_id,agent_id")
            .execute()
        )
        return resp.data[0]

    def remove_member(self, table_id: str, user_id: str, agent_id: str) -> bool:
        """Elimina un agente de la mesa."""
        self.get_table(table_id, user_id)
        self._sb.table("round_table_members").delete().eq(
            "table_id", table_id).eq("agent_id", agent_id).execute()
        return True

    def list_members(self, table_id: str, user_id: str) -> List[dict]:
        """Lista agentes miembros con nombre enriquecido."""
        self.get_table(table_id, user_id)
        resp = (
            self._sb.table("round_table_members")
            .select("id, agent_id, turn_order")
            .eq("table_id", table_id)
            .order("turn_order")
            .execute()
        )
        members = resp.data or []
        for m in members:
            try:
                agent = self._load_agent(m["agent_id"], user_id)
                m["agent_name"] = agent.get("name", "Agente")
            except Exception:
                m["agent_name"] = "Agente desconocido"
        return members

    # ──────────────────────────────────────────────────────────────────────────
    # DEBATE
    # ──────────────────────────────────────────────────────────────────────────

    def start_debate(self, table_id: str, user_id: str, rounds: int = 1) -> RoundTableResult:
        """
        Inicia el debate multi-agente.

        Cada ronda: todos los agentes responden en turn_order.
        Al final: un moderador sintetiza el resultado.
        El debate es síncrono (llamadas secuenciales al provider).
        """
        if not (MIN_ROUNDS <= rounds <= MAX_ROUNDS):
            raise ValueError(f"El número de rondas debe estar entre {MIN_ROUNDS} y {MAX_ROUNDS}.")

        table = self.get_table(table_id, user_id)
        if table["status"] == "running":
            raise ValueError("El debate ya está en curso.")
        if table["status"] == "done":
            raise ValueError("El debate ya ha concluido. Crea una nueva mesa.")

        topic = table["topic"]

        members_resp = (
            self._sb.table("round_table_members")
            .select("agent_id, turn_order")
            .eq("table_id", table_id)
            .order("turn_order")
            .execute()
        )
        members = members_resp.data or []
        if len(members) < MIN_AGENTS:
            raise ValueError(f"Necesitas al menos {MIN_AGENTS} agentes en la mesa.")

        # Cargar agentes con instrucciones AFT
        agents_data = []
        for m in members:
            agent = self._load_agent(m["agent_id"], user_id)
            agents_data.append({
                "agent_id": m["agent_id"],
                "name": agent.get("name", "Agente"),
                "instructions": self._extract_instructions(agent),
                "tier": agent.get("base_tier", "balanced"),
            })

        # Marcar como running
        self._sb.table("round_tables").update({"status": "running"}).eq("id", table_id).execute()

        participants_list = "\n".join(f"- {a['name']}" for a in agents_data)
        all_turns: List[RoundTableTurn] = []
        total_tokens = 0
        total_latency = 0.0

        # Rondas de debate
        for round_num in range(1, rounds + 1):
            logger.info(f"Round Table {table_id}: ronda {round_num}/{rounds}")
            for agent_data in agents_data:
                turn = self._run_agent_turn(
                    agent_data=agent_data,
                    topic=topic,
                    participants_list=participants_list,
                    history=all_turns,
                    round_num=round_num,
                    user_id=user_id,
                )
                all_turns.append(turn)
                total_tokens += turn.tokens_in + turn.tokens_out
                total_latency += turn.latency_ms

        # Síntesis final
        synthesis = self._synthesize(
            topic=topic, turns=all_turns,
            user_id=user_id, tier=agents_data[0]["tier"],
        )

        result = RoundTableResult(
            table_id=table_id, topic=topic, turns=all_turns,
            synthesis=synthesis, total_tokens=total_tokens,
            total_latency_ms=total_latency,
        )

        # Guardar y cerrar
        self._sb.table("round_tables").update({
            "status": "done",
            "result": json.dumps(result.to_dict()),
        }).eq("id", table_id).execute()

        logger.info(f"Round Table {table_id}: completado. {len(all_turns)} turnos, {total_tokens} tokens.")
        return result

    def get_result(self, table_id: str, user_id: str) -> dict:
        """Obtiene el resultado de un debate completado."""
        table = self.get_table(table_id, user_id)
        if table["status"] != "done":
            raise ValueError(f"El debate no ha concluido (estado: {table['status']}).")
        result_raw = table.get("result")
        if not result_raw:
            raise ValueError("No hay resultado disponible.")
        return json.loads(result_raw) if isinstance(result_raw, str) else result_raw

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS PRIVADOS
    # ──────────────────────────────────────────────────────────────────────────

    def _run_agent_turn(self, agent_data: dict, topic: str, participants_list: str,
                        history: List[RoundTableTurn], round_num: int, user_id: str) -> RoundTableTurn:
        """Ejecuta un único turno de un agente."""
        turn_prompt = _DEBATE_TURN_PROMPT.format(
            topic=topic,
            participants_list=participants_list,
            history=self._format_history(history) if history else "(Eres el primero en hablar.)",
            agent_name=agent_data["name"],
        )
        try:
            result = provider_router.infer(
                messages=[{"role": "user", "content": turn_prompt}],
                tier=agent_data["tier"],
                user_id=user_id,
                system_prompt=agent_data["instructions"],
                temperature=DEBATE_TEMPERATURE,
                max_tokens=MAX_TOKENS_PER_TURN,
            )
            return RoundTableTurn(
                agent_id=agent_data["agent_id"], agent_name=agent_data["name"],
                round_num=round_num, content=result.content,
                provider=result.provider, model=result.model,
                tokens_in=result.tokens_in, tokens_out=result.tokens_out,
                latency_ms=result.latency_ms,
            )
        except InferenceError as e:
            logger.error(f"InferenceError en turno de {agent_data['name']} ronda {round_num}: {e}")
            return RoundTableTurn(
                agent_id=agent_data["agent_id"], agent_name=agent_data["name"],
                round_num=round_num,
                content=f"[{agent_data['name']} no pudo responder: error del provider.]",
                provider="error", model="error",
                tokens_in=0, tokens_out=0, latency_ms=0.0,
            )

    def _synthesize(self, topic: str, turns: List[RoundTableTurn],
                    user_id: str, tier: str) -> str:
        """Genera la síntesis final del debate con el moderador."""
        synthesis_prompt = _SYNTHESIS_PROMPT.format(
            topic=topic,
            full_debate=self._format_history(turns),
        )
        try:
            result = provider_router.infer(
                messages=[{"role": "user", "content": synthesis_prompt}],
                tier=tier, user_id=user_id,
                system_prompt=(
                    "Eres un moderador experto e imparcial. "
                    "Tu misión es sintetizar debates de forma clara y estructurada."
                ),
                temperature=0.5,
                max_tokens=600,
            )
            return result.content
        except InferenceError:
            return "No se pudo generar la síntesis debido a un error del provider."

    def _format_history(self, turns: List[RoundTableTurn]) -> str:
        """Formatea el historial de turnos en texto legible."""
        if not turns:
            return ""
        return "\n\n---\n\n".join(
            f"[Ronda {t.round_num} — {t.agent_name}]\n{t.content}"
            for t in turns
        )

    def _load_agent(self, agent_id: str, user_id: str) -> dict:
        """Carga un agente verificando acceso (propio o público) con versión activa."""
        if not self._sb:
            raise ValueError("Supabase no disponible.")
        resp = (
            self._sb.table("custom_agents")
            .select("*")
            .eq("id", agent_id)
            .is_("deleted_at", "null")
            .execute()
        )
        if not resp.data:
            raise ValueError(f"Agente {agent_id} no encontrado.")
        agent = resp.data[0]
        if agent["user_id"] != user_id and not agent.get("is_public", False):
            raise ValueError(f"Sin acceso al agente {agent_id}.")
        if agent.get("current_version_id"):
            ver_resp = (
                self._sb.table("agent_versions")
                .select("system_instructions, retrieval_profile")
                .eq("id", agent["current_version_id"])
                .execute()
            )
            if ver_resp.data:
                agent["current_version"] = ver_resp.data[0]
        return agent

    def _extract_instructions(self, agent: dict) -> str:
        """Extrae las system_instructions de la versión activa del agente."""
        version = agent.get("current_version")
        if version and version.get("system_instructions"):
            return version["system_instructions"]
        return agent.get(
            "system_instructions",
            f"Eres {agent.get('name', 'un asistente')} con expertise técnico."
        )
