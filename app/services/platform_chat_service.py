"""
platform_chat_service.py
Servicio de chat con agentes personalizados.

Flujo por mensaje:
  1. Cargar agente (con versión activa y system_instructions compiladas por AFT).
  2. Crear o reanudar sesión de chat.
  3. Cargar historial de la sesión (últimos N mensajes).
  4. Decidir si activar RAG:
       - always_retrieve = True  →  siempre busca.
       - trigger_keywords        →  busca si alguna keyword está en la query.
  5. Buscar chunks relevantes en la knowledge base del agente.
  6. Construir system prompt final:
       system_instructions + bloque de contexto RAG (si hay).
  7. Llamar a ProviderRouter → InferenceResult.
  8. Persistir user_message + assistant_message en chat_messages.
  9. Actualizar updated_at de la sesión.
  10. Devolver ChatResponse.

Seguridad:
  - El agente debe ser del usuario O público.
  - La sesión siempre pertenece al usuario autenticado.
  - El historial se carga con RLS (service key para operaciones del backend).
"""
import json
import logging
from typing import Optional, List, Dict, Any

from supabase import Client
from app import config
from app.db import supabase_admin
from app.services.provider_router_service import provider_router, InferenceError
from app.services.platform_rag_service import PlatformRAGService
from app.services.agent_cache_service import AgentCacheService

logger = logging.getLogger(__name__)

# Número máximo de turnos del historial que se envían al modelo.
# Evita contextos gigantes; los más recientes son los más relevantes.
MAX_HISTORY_TURNS = 20   # 20 mensajes (10 turnos user/assistant)

# Encabezado del bloque de contexto RAG inyectado en el system prompt
_RAG_BLOCK_HEADER = (
    "\n\n[BASE DE CONOCIMIENTO — CONTEXTO RELEVANTE]\n"
    "Usa la siguiente información recuperada de la base de conocimiento del agente "
    "para responder con precisión. Prioriza estos datos sobre tu conocimiento general:\n"
)


class ChatSession:
    """DTO ligero que representa una sesión activa."""
    def __init__(self, session_id: str, agent_id: str, user_id: str,
                 title: Optional[str] = None):
        self.session_id = session_id
        self.agent_id = agent_id
        self.user_id = user_id
        self.title = title


class ChatMessage:
    def __init__(self, role: str, content: str, metadata: Optional[dict] = None):
        self.role = role
        self.content = content
        self.metadata = metadata or {}


class ChatResponse:
    def __init__(
        self,
        session_id: str,
        message_id: str,
        content: str,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        latency_ms: float,
        rag_chunks_used: int = 0,
    ):
        self.session_id = session_id
        self.message_id = message_id
        self.content = content
        self.provider = provider
        self.model = model
        self.tokens_in = tokens_in
        self.tokens_out = tokens_out
        self.latency_ms = latency_ms
        self.rag_chunks_used = rag_chunks_used

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "message_id": self.message_id,
            "content": self.content,
            "provider": self.provider,
            "model": self.model,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "latency_ms": self.latency_ms,
            "rag_chunks_used": self.rag_chunks_used,
        }


class PlatformChatService:
    """
    Gestiona sesiones de chat multi-turno con agentes personalizados.
    Integra AFT (system prompt compilado) + RAG + ProviderRouter Anti-429.
    """

    def __init__(self):
        self._sb: Optional[Client] = supabase_admin
        self._rag = PlatformRAGService()
        self._cache = AgentCacheService()
        if not self._sb:
            logger.warning("PlatformChatService: Supabase no configurado.")
        else:
            logger.info("PlatformChatService: usando cliente admin (service_role).")


    # ──────────────────────────────────────────────────────────────────────────
    # PUNTO DE ENTRADA PRINCIPAL
    # ──────────────────────────────────────────────────────────────────────────

    def chat(
        self,
        user_id: str,
        agent_id: str,
        user_message: str,
        session_id: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        force_provider: Optional[str] = None,
    ) -> ChatResponse:
        """
        Procesa un mensaje de usuario y devuelve la respuesta del agente.

        Args:
            user_id:       UUID del usuario autenticado.
            agent_id:      UUID del agente con el que se quiere chatear.
            user_message:  Texto del mensaje del usuario.
            session_id:    UUID de sesión existente (None = nueva sesión).
            temperature:   Temperatura de generación.
            max_tokens:    Límite de tokens de salida (None = default del provider).
            force_provider: Override de provider para debug.
        """
        # 1. Cargar agente + versión activa
        agent = self._load_agent(agent_id=agent_id, user_id=user_id)
        system_instructions = self._extract_system_instructions(agent)
        tier = agent.get("base_tier", "balanced")
        retrieval_profile = self._extract_retrieval_profile(agent)

        # Cargar preferencias de proveedor y modelo del perfil del agente
        preferred_provider = retrieval_profile.get("preferred_provider", None) if retrieval_profile else None
        preferred_model = retrieval_profile.get("preferred_model", None) if retrieval_profile else None

        # Cargar claves de usuario descifradas en memoria al iniciar la petición
        from app.services.provider_keys_db_service import provider_keys_db_service
        from app.services.provider_key_pool_service import key_pool
        
        user_keys = provider_keys_db_service.get_decrypted_user_keys(user_id)
        for uk in user_keys:
            key_pool.add_user_key(
                key_id=uk["key_id"],
                provider=uk["provider"],
                api_key=uk["api_key"],
                user_id=user_id,
                label=uk["key_label"],
                priority=10  # Claves de usuario tienen prioridad
            )

        # 2. Sesión
        session = self._get_or_create_session(
            user_id=user_id, agent_id=agent_id,
            session_id=session_id, first_message=user_message,
        )

        # 3. Historial de conversación
        history = self._load_history(session.session_id)

        # 4. RAG — decidir si buscar
        rag_chunks_used = 0
        rag_context = ""
        if self._should_retrieve(user_message, retrieval_profile):
            top_k = retrieval_profile.get("top_k", 5) if retrieval_profile else 5
            chunks = self._rag.search(
                agent_id=agent_id,
                query=user_message,
                top_k=top_k,
            )
            if chunks:
                rag_context = self._build_rag_block(chunks)
                rag_chunks_used = len(chunks)
                logger.info(f"Chat RAG: {len(chunks)} chunks recuperados para agent={agent_id}")

        # 5. System prompt final (instrucciones + contexto RAG)
        final_system_prompt = system_instructions
        if rag_context:
            inject_mode = (retrieval_profile or {}).get("context_injection", "prefix")
            if inject_mode == "suffix":
                final_system_prompt = system_instructions + rag_context
            else:
                # prefix (default) o inline → el contexto va al inicio
                final_system_prompt = rag_context + "\n\n" + system_instructions

        # 6. Cache lookup — antes de llamar al LLM
        cached_response = self._cache.get_cached_response(
            agent_id=agent_id, query=user_message
        )
        if cached_response:
            # HIT: devolver respuesta cacheada sin llamar al LLM
            msg_id = self._save_message(
                session_id=session.session_id, role="user",
                content=user_message, metadata={},
            )
            cached_msg_id = self._save_message(
                session_id=session.session_id, role="assistant",
                content=cached_response,
                metadata={"cached": True, "provider": "cache", "rag_chunks_used": rag_chunks_used},
            )
            self._touch_session(session.session_id)
            return ChatResponse(
                session_id=session.session_id,
                message_id=cached_msg_id,
                content=cached_response,
                provider="cache",
                model="cache",
                tokens_in=0, tokens_out=0, latency_ms=0.0,
                rag_chunks_used=rag_chunks_used,
            )

        # 7. Construir lista de mensajes para el provider
        messages = self._build_messages(history=history, user_message=user_message)

        # 7. Llamar al router de providers
        try:
            try:
                result = provider_router.infer(
                    messages=messages,
                    tier=tier,
                    user_id=user_id,
                    system_prompt=final_system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    force_provider=force_provider,
                    preferred_provider=preferred_provider,
                    preferred_model=preferred_model,
                )
            finally:
                key_pool.remove_user_keys(user_id)
        except InferenceError as e:
            logger.error(f"Chat InferenceError: {e} | tier={tier} | intentos={len(e.attempts)}")
            for a in e.attempts:
                logger.error(
                    f"  >> provider={a.provider} model={a.model} "
                    f"code={a.error_code} retry_after={a.retry_after} msg={a.error_msg[:200]}"
                )
            providers_tried = list({a.provider for a in e.attempts})
            pref_text = ""
            if preferred_provider:
                pref_text = f"Tu proveedor preferido ({preferred_provider}) no pudo responder en este momento. "
            raise ValueError(
                f"{pref_text}Todos los providers están saturados. "
                f"Por favor, intenta de nuevo en unos minutos o añade más claves API en tu perfil. "
                f"(providers intentados: {', '.join(providers_tried) or 'ninguno'})"
            )

        # 8. Persistir mensajes
        self._save_message(
            session_id=session.session_id,
            role="user",
            content=user_message,
            metadata={},
        )
        msg_id = self._save_message(
            session_id=session.session_id,
            role="assistant",
            content=result.content,
            metadata={
                "provider": result.provider,
                "model": result.model,
                "tokens_in": result.tokens_in,
                "tokens_out": result.tokens_out,
                "latency_ms": result.latency_ms,
                "rag_chunks_used": rag_chunks_used,
                "original_query": user_message[:500],  # para propagar feedback al cache
            },
        )

        # 9. Guardar en cache
        self._cache.store_response(
            agent_id=agent_id,
            query=user_message,
            response=result.content,
        )

        # 10. Actualizar timestamp de la sesión
        self._touch_session(session.session_id)

        return ChatResponse(
            session_id=session.session_id,
            message_id=msg_id,
            content=result.content,
            provider=result.provider,
            model=result.model,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            latency_ms=result.latency_ms,
            rag_chunks_used=rag_chunks_used,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # SESIONES
    # ──────────────────────────────────────────────────────────────────────────

    def list_sessions(self, user_id: str, limit: int = 20) -> List[dict]:
        """Lista las sesiones del usuario, más recientes primero."""
        if not self._sb:
            return []
        try:
            resp = (
                self._sb.table("chat_sessions")
                .select("id, agent_id, title, created_at, updated_at")
                .eq("user_id", user_id)
                .order("updated_at", desc=True)
                .limit(limit)
                .execute()
            )
            return resp.data or []
        except Exception as e:
            logger.error(f"Error listando sesiones de {user_id}: {e}")
            return []

    def get_session_history(
        self, session_id: str, user_id: str, limit: int = 100
    ) -> List[dict]:
        """Devuelve el historial de una sesión verificando que pertenece al usuario."""
        if not self._sb:
            return []
        # Verificar propiedad
        sess = self._sb.table("chat_sessions").select("user_id").eq("id", session_id).execute()
        if not sess.data or sess.data[0]["user_id"] != user_id:
            raise ValueError("Sesión no encontrada o sin acceso.")
        try:
            resp = (
                self._sb.table("chat_messages")
                .select("id, role, content, metadata, created_at")
                .eq("session_id", session_id)
                .order("created_at", desc=False)
                .limit(limit)
                .execute()
            )
            return resp.data or []
        except Exception as e:
            logger.error(f"Error obteniendo historial sesión {session_id}: {e}")
            return []

    def delete_session(self, session_id: str, user_id: str) -> bool:
        """Borra una sesión (y sus mensajes por CASCADE) verificando propiedad."""
        if not self._sb:
            return False
        sess = self._sb.table("chat_sessions").select("user_id").eq("id", session_id).execute()
        if not sess.data or sess.data[0]["user_id"] != user_id:
            raise ValueError("Sesión no encontrada o sin acceso.")
        self._sb.table("chat_sessions").delete().eq("id", session_id).execute()
        return True

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS PRIVADOS
    # ──────────────────────────────────────────────────────────────────────────

    def _load_agent(self, agent_id: str, user_id: str) -> dict:
        """Carga el agente con su versión activa. Verifica acceso."""
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
            raise ValueError("Agente no encontrado.")

        agent = resp.data[0]
        if agent["user_id"] != user_id and not agent.get("is_public", False):
            raise ValueError("No tienes acceso a este agente.")

        # Cargar versión activa
        if agent.get("current_version_id"):
            ver_resp = (
                self._sb.table("agent_versions")
                .select("*")
                .eq("id", agent["current_version_id"])
                .execute()
            )
            if ver_resp.data:
                agent["current_version"] = ver_resp.data[0]

        return agent

    def _extract_system_instructions(self, agent: dict) -> str:
        """Extrae las system_instructions de la versión activa del agente."""
        version = agent.get("current_version")
        if version and version.get("system_instructions"):
            return version["system_instructions"]
        # Fallback al campo directo del agente
        return agent.get("system_instructions", "Eres un asistente de IA útil y preciso.")

    def _extract_retrieval_profile(self, agent: dict) -> Optional[dict]:
        """Extrae el retrieval_profile de la versión activa."""
        version = agent.get("current_version")
        if not version:
            return None
        rp = version.get("retrieval_profile")
        if isinstance(rp, str):
            try:
                return json.loads(rp)
            except Exception:
                return None
        return rp if isinstance(rp, dict) else None

    def _should_retrieve(self, query: str, retrieval_profile: Optional[dict]) -> bool:
        """
        Decide si activar el RAG para este query.
        - Si always_retrieve=True → siempre.
        - Si algún trigger_keyword aparece en la query → activa.
        - Si no hay retrieval_profile → no busca.
        """
        if not retrieval_profile:
            return False
        if retrieval_profile.get("always_retrieve", False):
            return True
        keywords = retrieval_profile.get("trigger_keywords", [])
        query_lower = query.lower()
        return any(kw.lower() in query_lower for kw in keywords)

    def _build_rag_block(self, chunks: list) -> str:
        """Formatea los chunks RAG en un bloque de texto para el system prompt."""
        lines = [_RAG_BLOCK_HEADER]
        for i, chunk in enumerate(chunks, 1):
            heading = getattr(chunk, "heading", None) or ""
            content = getattr(chunk, "content", str(chunk))
            label = f"[{i}] {heading}" if heading else f"[{i}]"
            lines.append(f"{label}\n{content}")
        return "\n\n".join(lines)

    def _get_or_create_session(
        self,
        user_id: str,
        agent_id: str,
        session_id: Optional[str],
        first_message: str,
    ) -> ChatSession:
        """Obtiene la sesión existente o crea una nueva."""
        if not self._sb:
            # Modo sin DB: usar ID ficticio para tests
            return ChatSession(
                session_id=session_id or "local-session",
                agent_id=agent_id,
                user_id=user_id,
            )

        if session_id:
            resp = (
                self._sb.table("chat_sessions")
                .select("id, agent_id, user_id, title")
                .eq("id", session_id)
                .eq("user_id", user_id)
                .execute()
            )
            if resp.data:
                s = resp.data[0]
                return ChatSession(
                    session_id=s["id"], agent_id=s["agent_id"],
                    user_id=s["user_id"], title=s.get("title"),
                )
            # Si no existe → crear igualmente
        # Nueva sesión
        title = first_message[:60] + "..." if len(first_message) > 60 else first_message
        new_session = (
            self._sb.table("chat_sessions")
            .insert({"user_id": user_id, "agent_id": agent_id, "title": title})
            .execute()
        )
        s = new_session.data[0]
        return ChatSession(
            session_id=s["id"], agent_id=agent_id, user_id=user_id, title=title
        )

    def _load_history(self, session_id: str) -> List[Dict[str, str]]:
        """
        Carga el historial de mensajes de la sesión.
        Devuelve los últimos MAX_HISTORY_TURNS en formato OpenAI [{"role":..,"content":..}].
        """
        if not self._sb or session_id in ("local-session",):
            return []
        try:
            resp = (
                self._sb.table("chat_messages")
                .select("role, content")
                .eq("session_id", session_id)
                .order("created_at", desc=False)
                .limit(MAX_HISTORY_TURNS)
                .execute()
            )
            return [
                {"role": m["role"], "content": m["content"]}
                for m in (resp.data or [])
                if m["role"] in ("user", "assistant")
            ]
        except Exception as e:
            logger.error(f"Error cargando historial de sesión {session_id}: {e}")
            return []

    def _build_messages(
        self, history: List[Dict[str, str]], user_message: str
    ) -> List[Dict[str, str]]:
        """Construye la lista de mensajes para el provider (historial + nuevo mensaje)."""
        messages = list(history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def _save_message(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict,
    ) -> str:
        """Persiste un mensaje y devuelve su ID."""
        if not self._sb or session_id in ("local-session",):
            return "local-msg-id"
        try:
            resp = (
                self._sb.table("chat_messages")
                .insert({
                    "session_id": session_id,
                    "role": role,
                    "content": content,
                    "metadata": metadata,
                })
                .execute()
            )
            return resp.data[0]["id"] if resp.data else "unknown"
        except Exception as e:
            logger.error(f"Error guardando mensaje en sesión {session_id}: {e}")
            return "error"

    def _touch_session(self, session_id: str) -> None:
        """Actualiza el updated_at de la sesión."""
        if not self._sb or session_id in ("local-session",):
            return
        try:
            self._sb.table("chat_sessions").update(
                {"updated_at": "now()"}
            ).eq("id", session_id).execute()
        except Exception as e:
            logger.warning(f"No se pudo actualizar updated_at de sesión {session_id}: {e}")
