"""
agent_service.py
CRUD de agentes personalizados y versionado de perfiles AFT.
Fase 2: operaciones completas contra Supabase con RLS.
"""
import logging
from typing import Optional, Dict, Any, List
from supabase import Client
from app import config
from app.db import supabase_admin

logger = logging.getLogger(__name__)


class AgentService:
    """
    Gestiona el ciclo de vida de los agentes personalizados:
    - Crear, leer, editar, borrar (soft-delete)
    - Publicar / hacer privado
    - Versionado de perfiles AFT
    """

    def __init__(self):
        # Usar siempre el cliente admin (service_role) para bypass de RLS
        self.supabase: Optional[Client] = supabase_admin
        if not self.supabase:
            logger.warning("AgentService: Supabase no configurado.")
        else:
            logger.info("AgentService: usando cliente admin (service_role).")


    # ──────────────────────────────────────────────────────────────────────────
    # CREAR AGENTE
    # ──────────────────────────────────────────────────────────────────────────

    def create_agent(
        self,
        user_id: str,
        name: str,
        description: Optional[str],
        category: str,
        base_tier: str,
        system_instructions: str,
        is_public: bool = False,
        preferred_provider: Optional[str] = None,
        preferred_model: Optional[str] = None,
        fallback_models: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """
        Crea un agente y su primera versión (v1) de perfil AFT.
        Devuelve el agente completo con la versión activa.
        """
        self._require_supabase()

        # 2. Insertar el agente (sin current_version_id por ahora)
        try:
            agent_resp = (
                self.supabase.table("custom_agents")
                .insert({
                    "user_id": user_id,
                    "name": name,
                    "description": description,
                    "category": category,
                    "base_tier": base_tier,
                    "is_public": is_public,
                })
                .execute()
            )
            agent = agent_resp.data[0]
            agent_id = agent["id"]
        except Exception as e:
            logger.error(f"Error creando agente para user {user_id}: {e}")
            raise ValueError("No se pudo crear el agente.")

        # 3. Crear la versión 1 del perfil
        retrieval_profile = {}
        if preferred_provider:
            retrieval_profile["preferred_provider"] = preferred_provider
        if preferred_model:
            retrieval_profile["preferred_model"] = preferred_model
        if fallback_models:
            retrieval_profile["fallback_models"] = fallback_models

        version = self._create_version(
            agent_id=agent_id,
            version_number=1,
            system_instructions=system_instructions,
            retrieval_profile=retrieval_profile,
        )

        # 4. Vincular el agente a su versión activa
        try:
            self.supabase.table("custom_agents").update(
                {"current_version_id": version["id"]}
            ).eq("id", agent_id).execute()
            agent["current_version_id"] = version["id"]
        except Exception as e:
            logger.error(f"Error vinculando versión al agente {agent_id}: {e}")

        agent["current_version"] = version
        return agent

    # ──────────────────────────────────────────────────────────────────────────
    # LEER AGENTES
    # ──────────────────────────────────────────────────────────────────────────

    def list_my_agents(self, user_id: str) -> List[Dict[str, Any]]:
        """Lista todos los agentes activos del usuario (sin soft-deleted)."""
        self._require_supabase()
        try:
            resp = (
                self.supabase.table("custom_agents")
                .select("*")
                .eq("user_id", user_id)
                .is_("deleted_at", "null")
                .order("created_at", desc=True)
                .execute()
            )
            agents = resp.data or []
            # Enriquecer con versión activa
            for a in agents:
                if a.get("current_version_id"):
                    a["current_version"] = self._get_version_by_id(a["current_version_id"])
            return agents
        except Exception as e:
            logger.error(f"Error listando agentes de user {user_id}: {e}")
            return []

    def get_agent(self, agent_id: str, user_id: str) -> Dict[str, Any]:
        """
        Obtiene un agente por ID.
        El usuario debe ser el dueño O el agente debe ser público.
        """
        self._require_supabase()
        try:
            resp = (
                self.supabase.table("custom_agents")
                .select("*")
                .eq("id", agent_id)
                .is_("deleted_at", "null")
                .execute()
            )
            if not resp.data:
                raise ValueError("Agente no encontrado.")

            agent = resp.data[0]

            # Verificar acceso
            if agent["user_id"] != user_id and not agent["is_public"]:
                raise ValueError("No tienes acceso a este agente.")

            if agent.get("current_version_id"):
                agent["current_version"] = self._get_version_by_id(agent["current_version_id"])

            return agent
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error obteniendo agente {agent_id}: {e}")
            raise ValueError("Error al obtener el agente.")

    def list_public_agents(self, category: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Lista agentes públicos (biblioteca). Opcionalmente filtra por categoría."""
        self._require_supabase()
        try:
            query = (
                self.supabase.table("custom_agents")
                .select("*")
                .eq("is_public", True)
                .is_("deleted_at", "null")
                .order("level", desc=True)
                .limit(limit)
            )
            if category:
                query = query.eq("category", category)
            resp = query.execute()
            agents = resp.data or []
            for a in agents:
                if a.get("current_version_id"):
                    a["current_version"] = self._get_version_by_id(a["current_version_id"])
            return agents
        except Exception as e:
            logger.error(f"Error listando agentes públicos: {e}")
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # ACTUALIZAR AGENTE
    # ──────────────────────────────────────────────────────────────────────────

    def update_agent(self, agent_id: str, user_id: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Actualiza campos de metadatos del agente (nombre, descripción, tier, etc.)."""
        self._require_supabase()
        self._assert_owner(agent_id, user_id)

        # Si se actualizan preferred_provider, preferred_model o fallback_models, guardarlos en la versión actual
        preferred_provider = fields.get("preferred_provider")
        preferred_model = fields.get("preferred_model")
        fallback_models = fields.get("fallback_models")
        
        if preferred_provider is not None or preferred_model is not None or fallback_models is not None:
            try:
                agent_curr_resp = self.supabase.table("custom_agents").select("current_version_id").eq("id", agent_id).execute()
                if agent_curr_resp.data and agent_curr_resp.data[0].get("current_version_id"):
                    v_id = agent_curr_resp.data[0]["current_version_id"]
                    version_data = self._get_version_by_id(v_id)
                    if version_data:
                        rp = version_data.get("retrieval_profile") or {}
                        if preferred_provider is not None:
                            rp["preferred_provider"] = preferred_provider
                        if preferred_model is not None:
                            rp["preferred_model"] = preferred_model
                        if fallback_models is not None:
                            rp["fallback_models"] = fallback_models
                        self.supabase.table("agent_versions").update({"retrieval_profile": rp}).eq("id", v_id).execute()
            except Exception as e:
                logger.error(f"Error actualizando preferencias de inferencia en versión actual del agente {agent_id}: {e}")

        allowed = {"name", "description", "category", "base_tier", "is_public"}
        update_data = {k: v for k, v in fields.items() if k in allowed and v is not None}

        # Permitir bypass si solo se cambiaron preferred_provider, preferred_model o fallback_models y no hay campos generales
        if not update_data:
            # Recuperar el agente completo para retornar
            try:
                resp = self.supabase.table("custom_agents").select("*").eq("id", agent_id).execute()
                agent = resp.data[0] if resp.data else {}
                if agent.get("current_version_id"):
                    agent["current_version"] = self._get_version_by_id(agent["current_version_id"])
                return agent
            except Exception as e:
                logger.error(f"Error recuperando agente {agent_id} tras actualización de versión: {e}")
                raise ValueError("No se pudo actualizar el agente.")

        try:
            resp = (
                self.supabase.table("custom_agents")
                .update(update_data)
                .eq("id", agent_id)
                .execute()
            )
            agent = resp.data[0] if resp.data else {}
            if agent.get("current_version_id"):
                agent["current_version"] = self._get_version_by_id(agent["current_version_id"])
            return agent
        except Exception as e:
            logger.error(f"Error actualizando agente {agent_id}: {e}")
            raise ValueError("No se pudo actualizar el agente.")

    def publish_agent(self, agent_id: str, user_id: str, is_public: bool) -> Dict[str, Any]:
        """Publica o hace privado un agente."""
        self._require_supabase()
        self._assert_owner(agent_id, user_id)
        try:
            resp = (
                self.supabase.table("custom_agents")
                .update({"is_public": is_public})
                .eq("id", agent_id)
                .execute()
            )
            return resp.data[0] if resp.data else {}
        except Exception as e:
            logger.error(f"Error publicando agente {agent_id}: {e}")
            raise ValueError("No se pudo cambiar la visibilidad del agente.")

    # ──────────────────────────────────────────────────────────────────────────
    # BORRAR AGENTE (soft-delete)
    # ──────────────────────────────────────────────────────────────────────────

    def delete_agent(self, agent_id: str, user_id: str) -> None:
        """Soft-delete: marca deleted_at, no borra la fila."""
        self._require_supabase()
        self._assert_owner(agent_id, user_id)
        from datetime import datetime, timezone
        try:
            self.supabase.table("custom_agents").update(
                {"deleted_at": datetime.now(timezone.utc).isoformat()}
            ).eq("id", agent_id).execute()
        except Exception as e:
            logger.error(f"Error borrando agente {agent_id}: {e}")
            raise ValueError("No se pudo borrar el agente.")

    # ──────────────────────────────────────────────────────────────────────────
    # VERSIONADO
    # ──────────────────────────────────────────────────────────────────────────

    def create_new_version(
        self,
        agent_id: str,
        user_id: str,
        system_instructions: str,
        behavior_examples: Optional[list] = None,
        style_rules: Optional[dict] = None,
        domain_constraints: Optional[dict] = None,
        retrieval_profile: Optional[dict] = None,
    ) -> Dict[str, Any]:
        """
        Crea una nueva versión del perfil AFT y la establece como activa.
        La versión anterior queda preservada para rollback.
        """
        self._require_supabase()
        self._assert_owner(agent_id, user_id)

        # Obtener el número de versión más alto actual
        versions_resp = (
            self.supabase.table("agent_versions")
            .select("version")
            .eq("agent_id", agent_id)
            .order("version", desc=True)
            .limit(1)
            .execute()
        )
        last_version = versions_resp.data[0]["version"] if versions_resp.data else 0
        new_version_number = last_version + 1

        version = self._create_version(
            agent_id=agent_id,
            version_number=new_version_number,
            system_instructions=system_instructions,
            behavior_examples=behavior_examples or [],
            style_rules=style_rules or {},
            domain_constraints=domain_constraints or {},
            retrieval_profile=retrieval_profile or {},
        )

        # Actualizar current_version_id del agente
        self.supabase.table("custom_agents").update(
            {"current_version_id": version["id"]}
        ).eq("id", agent_id).execute()

        return version

    def list_versions(self, agent_id: str, user_id: str) -> List[Dict[str, Any]]:
        """Lista todas las versiones de un agente (el dueño puede ver el historial)."""
        self._require_supabase()
        self._assert_owner(agent_id, user_id)
        try:
            resp = (
                self.supabase.table("agent_versions")
                .select("*")
                .eq("agent_id", agent_id)
                .order("version", desc=True)
                .execute()
            )
            return resp.data or []
        except Exception as e:
            logger.error(f"Error listando versiones de agente {agent_id}: {e}")
            return []

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS INTERNOS
    # ──────────────────────────────────────────────────────────────────────────

    def _create_version(
        self,
        agent_id: str,
        version_number: int,
        system_instructions: str,
        behavior_examples: Optional[list] = None,
        style_rules: Optional[dict] = None,
        domain_constraints: Optional[dict] = None,
        retrieval_profile: Optional[dict] = None,
    ) -> Dict[str, Any]:
        try:
            resp = (
                self.supabase.table("agent_versions")
                .insert({
                    "agent_id": agent_id,
                    "version": version_number,
                    "system_instructions": system_instructions,
                    "behavior_examples": behavior_examples or [],
                    "style_rules": style_rules or {},
                    "domain_constraints": domain_constraints or {},
                    "retrieval_profile": retrieval_profile or {},
                })
                .execute()
            )
            return resp.data[0]
        except Exception as e:
            logger.error(f"Error creando versión {version_number} del agente {agent_id}: {e}")
            raise ValueError("No se pudo guardar la versión del agente.")

    def _get_version_by_id(self, version_id: str) -> Optional[Dict[str, Any]]:
        try:
            resp = (
                self.supabase.table("agent_versions")
                .select("*")
                .eq("id", version_id)
                .single()
                .execute()
            )
            return resp.data
        except Exception:
            return None

    def _assert_owner(self, agent_id: str, user_id: str) -> None:
        """Lanza ValueError si el usuario no es el dueño del agente."""
        try:
            resp = (
                self.supabase.table("custom_agents")
                .select("user_id")
                .eq("id", agent_id)
                .is_("deleted_at", "null")
                .execute()
            )
            if not resp.data:
                raise ValueError("Agente no encontrado.")
            if resp.data[0]["user_id"] != user_id:
                raise ValueError("No tienes permiso para modificar este agente.")
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Error verificando propiedad del agente {agent_id}: {e}")
            raise ValueError("Error verificando permisos.")

    def _require_supabase(self):
        if not self.supabase:
            raise ValueError("El servicio de agentes no está disponible. Supabase no configurado.")


# Singleton global
agent_service = AgentService()
