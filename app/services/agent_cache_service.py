"""
agent_cache_service.py
Cache de respuestas por agente con feedback +1/-1 y re-síntesis controlada.

Estrategia de cache:
  - Hash determinista de la query normalizada (minúsculas, sin espacios extra).
  - Cache lookup en Supabase (tabla agent_cache) antes de llamar al LLM.
  - Si HIT: devuelve respuesta cacheada, incrementa times_used.
  - Si MISS: llama al LLM, guarda en cache.
  - TTL implícito: last_used_at permite purgar entradas antiguas (cron externo).

Feedback:
  - +1 / -1 por message_id (chat_messages.id).
  - Se guarda en chat_messages.metadata["feedback"].
  - Si el mensaje está cacheado, se propaga a agent_cache.user_feedback.
  - Umbral: ≥3 feedbacks negativos → sugiere re-síntesis de versión.

Re-síntesis:
  - Analiza los mensajes con feedback -1 del agente.
  - Genera un resumen de fallos y lo pasa al AFT Compiler.
  - Crea una nueva versión del agente con las instrucciones mejoradas.
  - El usuario debe aprobar explícitamente la nueva versión (no es automático).
"""
import hashlib
import logging
import re
from typing import Optional, List, Dict, Any

from supabase import create_client, Client
from app import config

logger = logging.getLogger(__name__)

# ─── Umbrales ─────────────────────────────────────────────────────────────────
FEEDBACK_NEGATIVE_THRESHOLD = 3   # feedbacks -1 para disparar alerta de re-síntesis
CACHE_MAX_QUERY_LENGTH = 2000     # queries más largas no se cachean (contexto demasiado específico)
CACHE_MIN_QUERY_LENGTH = 10       # queries muy cortas no se cachean


def _normalize_query(query: str) -> str:
    """Normaliza la query para el hash: minúsculas, sin espacios extra."""
    return re.sub(r"\s+", " ", query.strip().lower())


def _compute_hash(agent_id: str, query: str) -> str:
    """Hash SHA-256 determinista de (agent_id, query_normalizada)."""
    normalized = _normalize_query(query)
    payload = f"{agent_id}::{normalized}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_cacheable(query: str) -> bool:
    """Decide si una query merece ser cacheada."""
    stripped = query.strip()
    if len(stripped) < CACHE_MIN_QUERY_LENGTH:
        return False
    if len(stripped) > CACHE_MAX_QUERY_LENGTH:
        return False
    return True


class AgentCacheService:
    """
    Gestiona el cache semántico, el sistema de feedback y la re-síntesis de agentes.

    Thread-safe a nivel de Supabase (cada operación es atómica via UPSERT/UPDATE).
    """

    def __init__(self):
        self._sb: Optional[Client] = None

        if config.SUPABASE_URL and config.SUPABASE_SERVICE_KEY:
            try:
                self._sb = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_KEY)
                logger.info("AgentCacheService: cliente Supabase (service key) inicializado.")
            except Exception as e:
                logger.error(f"AgentCacheService: error inicializando Supabase: {e}")
        elif config.SUPABASE_URL and config.SUPABASE_KEY:
            self._sb = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

    # ──────────────────────────────────────────────────────────────────────────
    # CACHE
    # ──────────────────────────────────────────────────────────────────────────

    def get_cached_response(self, agent_id: str, query: str) -> Optional[str]:
        """
        Busca una respuesta cacheada para (agent_id, query).
        Si existe: incrementa times_used y devuelve el contenido.
        Si no: devuelve None.
        """
        if not self._sb or not _is_cacheable(query):
            return None

        query_hash = _compute_hash(agent_id, query)
        try:
            resp = (
                self._sb.table("agent_cache")
                .select("id, response, user_feedback")
                .eq("agent_id", agent_id)
                .eq("query_hash", query_hash)
                .execute()
            )
            if not resp.data:
                return None

            entry = resp.data[0]
            # No devolver respuestas con feedback muy negativo
            if entry.get("user_feedback", 0) <= -3:
                logger.info(f"Cache HIT ignorado por feedback negativo: {query_hash[:12]}...")
                return None

            # Incrementar contador de uso
            self._sb.table("agent_cache").update({
                "times_used": entry.get("times_used", 1) + 1,
                "last_used_at": "now()",
            }).eq("id", entry["id"]).execute()

            logger.info(f"Cache HIT agent={agent_id} hash={query_hash[:12]}...")
            return entry["response"]

        except Exception as e:
            logger.warning(f"Error en cache lookup: {e}")
            return None

    def store_response(
        self,
        agent_id: str,
        query: str,
        response: str,
    ) -> bool:
        """
        Guarda una nueva respuesta en cache (UPSERT por agent_id + query_hash).
        Devuelve True si se guardó correctamente.
        """
        if not self._sb or not _is_cacheable(query):
            return False

        query_hash = _compute_hash(agent_id, query)
        normalized = _normalize_query(query)

        try:
            self._sb.table("agent_cache").upsert({
                "agent_id": agent_id,
                "query_hash": query_hash,
                "query": normalized[:500],   # truncar para el campo legible
                "response": response,
                "times_used": 1,
                "last_used_at": "now()",
            }, on_conflict="agent_id,query_hash").execute()

            logger.info(f"Cache STORE agent={agent_id} hash={query_hash[:12]}...")
            return True

        except Exception as e:
            logger.warning(f"Error guardando en cache: {e}")
            return False

    def invalidate_cache(self, agent_id: str) -> int:
        """
        Invalida todo el cache de un agente (útil tras una re-síntesis de versión).
        Devuelve el número de entradas eliminadas.
        """
        if not self._sb:
            return 0
        try:
            resp = (
                self._sb.table("agent_cache")
                .delete()
                .eq("agent_id", agent_id)
                .execute()
            )
            count = len(resp.data) if resp.data else 0
            logger.info(f"Cache INVALIDATED agent={agent_id}: {count} entradas eliminadas.")
            return count
        except Exception as e:
            logger.warning(f"Error invalidando cache: {e}")
            return 0

    def get_cache_stats(self, agent_id: str) -> dict:
        """Devuelve estadísticas del cache del agente."""
        if not self._sb:
            return {"total_entries": 0, "total_hits": 0, "avg_feedback": 0.0}
        try:
            resp = (
                self._sb.table("agent_cache")
                .select("times_used, user_feedback")
                .eq("agent_id", agent_id)
                .execute()
            )
            entries = resp.data or []
            total_entries = len(entries)
            total_hits = sum(e.get("times_used", 1) for e in entries)
            feedbacks = [e.get("user_feedback", 0) for e in entries if e.get("user_feedback", 0) != 0]
            avg_feedback = sum(feedbacks) / len(feedbacks) if feedbacks else 0.0
            return {
                "total_entries": total_entries,
                "total_hits": total_hits,
                "avg_feedback": round(avg_feedback, 2),
            }
        except Exception as e:
            logger.warning(f"Error obteniendo stats de cache: {e}")
            return {"total_entries": 0, "total_hits": 0, "avg_feedback": 0.0}

    # ──────────────────────────────────────────────────────────────────────────
    # FEEDBACK
    # ──────────────────────────────────────────────────────────────────────────

    def submit_feedback(
        self,
        message_id: str,
        agent_id: str,
        user_id: str,
        value: int,  # +1 o -1
    ) -> dict:
        """
        Registra un voto de feedback sobre un mensaje del asistente.

        - Actualiza chat_messages.metadata con el feedback.
        - Propaga el valor al cache si la entrada existe.
        - Devuelve un resumen del estado del feedback del agente.
        """
        if value not in (1, -1):
            raise ValueError("El valor de feedback debe ser +1 o -1.")

        if not self._sb:
            return {"message_id": message_id, "feedback": value, "negative_count": 0}

        # 1. Leer el mensaje para verificar propiedad (via sesión)
        msg_resp = (
            self._sb.table("chat_messages")
            .select("id, role, content, metadata, session_id")
            .eq("id", message_id)
            .execute()
        )
        if not msg_resp.data:
            raise ValueError("Mensaje no encontrado.")

        msg = msg_resp.data[0]
        if msg["role"] != "assistant":
            raise ValueError("Solo se puede dar feedback a mensajes del asistente.")

        # Verificar que la sesión pertenece al usuario
        sess_resp = (
            self._sb.table("chat_sessions")
            .select("user_id")
            .eq("id", msg["session_id"])
            .execute()
        )
        if not sess_resp.data or sess_resp.data[0]["user_id"] != user_id:
            raise ValueError("No tienes acceso a este mensaje.")

        # 2. Actualizar metadata del mensaje con el feedback
        metadata = msg.get("metadata") or {}
        metadata["feedback"] = value
        self._sb.table("chat_messages").update({"metadata": metadata}).eq("id", message_id).execute()

        # 3. Propagar al cache si la query está cacheada
        query = metadata.get("original_query", "")
        if query:
            query_hash = _compute_hash(agent_id, query)
            try:
                self._sb.table("agent_cache").update({
                    "user_feedback": value,
                }).eq("agent_id", agent_id).eq("query_hash", query_hash).execute()
            except Exception:
                pass  # No crítico

        # 4. Contar feedbacks negativos del agente para sugerir re-síntesis
        negative_count = self._count_negative_feedback(agent_id)
        needs_resynthesis = negative_count >= FEEDBACK_NEGATIVE_THRESHOLD

        logger.info(
            f"Feedback registrado: message={message_id} value={value:+d} "
            f"agent={agent_id} negatives={negative_count}"
        )

        return {
            "message_id": message_id,
            "feedback": value,
            "negative_count": negative_count,
            "needs_resynthesis": needs_resynthesis,
        }

    def _count_negative_feedback(self, agent_id: str) -> int:
        """Cuenta mensajes con feedback -1 para el agente en los últimos 7 días."""
        if not self._sb:
            return 0
        try:
            # Contar mensajes negativos en sesiones del agente
            resp = (
                self._sb.rpc(
                    "count_negative_feedback",
                    {"p_agent_id": agent_id}
                ).execute()
            )
            return int(resp.data) if resp.data is not None else 0
        except Exception:
            # Fallback: sin RPC, contar desde agent_cache
            try:
                resp = (
                    self._sb.table("agent_cache")
                    .select("id", count="exact")
                    .eq("agent_id", agent_id)
                    .lte("user_feedback", -1)
                    .execute()
                )
                return resp.count or 0
            except Exception:
                return 0

    def get_negative_messages(
        self, agent_id: str, user_id: str, limit: int = 20
    ) -> List[dict]:
        """
        Devuelve los mensajes con feedback negativo del agente.
        Usado por el compilador AFT para la re-síntesis.
        """
        if not self._sb:
            return []
        try:
            # Obtener sesiones del usuario con este agente
            sessions_resp = (
                self._sb.table("chat_sessions")
                .select("id")
                .eq("user_id", user_id)
                .eq("agent_id", agent_id)
                .execute()
            )
            session_ids = [s["id"] for s in (sessions_resp.data or [])]
            if not session_ids:
                return []

            # Obtener mensajes del asistente con feedback -1
            msgs_resp = (
                self._sb.table("chat_messages")
                .select("id, content, metadata")
                .in_("session_id", session_ids)
                .eq("role", "assistant")
                .execute()
            )
            negative = [
                m for m in (msgs_resp.data or [])
                if (m.get("metadata") or {}).get("feedback") == -1
            ]
            return negative[:limit]
        except Exception as e:
            logger.warning(f"Error obteniendo mensajes negativos: {e}")
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # RE-SÍNTESIS
    # ──────────────────────────────────────────────────────────────────────────

    def prepare_resynthesis_context(
        self,
        agent_id: str,
        user_id: str,
        current_instructions: str,
    ) -> dict:
        """
        Prepara el contexto para re-sintetizar el agente vía AFT Compiler.

        Devuelve un dict con:
          - failure_summary: resumen de los fallos detectados
          - negative_examples: lista de respuestas con -1
          - suggested_prompt: instrucciones de mejora para el compilador
          - can_resynthesize: bool indicando si hay suficientes datos

        El usuario debe llamar explícitamente al compilador con este contexto.
        """
        negative_msgs = self.get_negative_messages(agent_id, user_id)

        if len(negative_msgs) < 1:
            return {
                "can_resynthesize": False,
                "reason": "No hay suficientes feedbacks negativos para re-sintetizar.",
                "negative_count": 0,
            }

        # Construir resumen de fallos
        failure_examples = []
        for msg in negative_msgs[:10]:
            failure_examples.append({
                "bad_response": msg["content"][:300],
                "feedback": -1,
            })

        failure_summary = (
            f"El agente ha recibido {len(negative_msgs)} respuesta(s) valoradas negativamente. "
            f"Los principales problemas detectados en las respuestas son:\n"
        )
        for i, ex in enumerate(failure_examples[:5], 1):
            failure_summary += f"\n[Fallo {i}]: {ex['bad_response'][:200]}..."

        suggested_prompt = (
            f"{current_instructions}\n\n"
            f"[MEJORAS REQUERIDAS BASADAS EN FEEDBACK NEGATIVO]\n"
            f"Las siguientes respuestas anteriores fueron valoradas negativamente. "
            f"Debes evitar estos patrones y mejorar la calidad de las respuestas:\n"
            f"{failure_summary}"
        )

        return {
            "can_resynthesize": True,
            "negative_count": len(negative_msgs),
            "failure_summary": failure_summary,
            "negative_examples": failure_examples,
            "suggested_prompt": suggested_prompt,
        }
