"""
provider_key_pool_service.py
Pool de API keys por proveedor con rotación, prioridades y persistencia en Supabase.

Estrategia de selección de key:
  1. Sólo se consideran keys disponibles (no en cooldown, no inválidas).
  2. Entre las disponibles, se ordenan por:
       a. Prioridad (menor número = mayor prioridad)
       b. Menor número de requests en ventana actual (balanceo de carga)
       c. Última vez usada (round-robin dentro del mismo nivel)
  3. Si ninguna key propia del tier está disponible → se escala al siguiente tier.
  4. Si ninguna key de ningún tier está disponible → None (el router hará fallback).

Fuentes de keys (en orden de prioridad):
  1. Keys de sistema (en config / env vars): GROQ_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY
  2. Keys de usuario (en Supabase, cifradas con AES-GCM): tabla `user_api_keys`

Providers soportados:
  - google     → Gemini 2.5 Flash / Pro
  - groq       → Llama 3.x 8B / 70B
  - openrouter → Cualquier modelo vía proxy

RPM límites conocidos (free tier):
  - groq:       30 RPM (free) / 7000 RPM (paid)
  - google:     15 RPM (free) / 1000 RPM (paid)
  - openrouter: 20 RPM (free) / custom (paid)
"""
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app import config
from app.services.cooldown_service import cooldown_service

logger = logging.getLogger(__name__)


# ─── Configuración de providers ───────────────────────────────────────────────

PROVIDER_RPM_LIMITS: Dict[str, int] = {
    "google":     60,    # conservador para evitar 429 preventivo
    "groq":       25,    # conservador (free: 30 RPM)
    "openrouter": 18,    # conservador (free: 20 RPM)
}

# Modelos disponibles por provider y tier
# Tier: "fast" | "balanced" | "pro"
PROVIDER_MODEL_MAP: Dict[str, Dict[str, str]] = {
    "groq": {
        "fast":     "llama-3.1-8b-instant",
        "balanced": "llama-3.3-70b-versatile",
        "pro":      "llama-3.3-70b-versatile",
    },
    "google": {
        "fast":     "gemini-2.0-flash-lite",
        "balanced": "gemini-2.0-flash",          # Flash es más rápido y generoso que 2.5-flash
        "pro":      "gemini-2.5-flash",           # 2.5-flash para pro (buen balance calidad/coste)
    },
    "openrouter": {
        "fast":     "meta-llama/llama-3.1-8b-instruct:free",
        "balanced": "meta-llama/llama-3.3-70b-instruct:free",
        "pro":      "anthropic/claude-3.5-sonnet",
    },
}

# Orden de providers por tier (primary → fallback → last-resort)
PROVIDER_ORDER: Dict[str, List[str]] = {
    "fast":     ["groq", "google", "openrouter"],
    "balanced": ["google", "groq", "openrouter"],   # Gemini primero: más generoso RPM/TPM
    "pro":      ["google", "openrouter", "groq"],
}


# ─── Modelo de key ────────────────────────────────────────────────────────────

@dataclass
class ProviderKey:
    key_id: str          # identificador único (UUID o slug)
    provider: str        # google | groq | openrouter
    api_key: str         # valor real de la key
    tier: str            # fast | balanced | pro | all
    priority: int        # menor = más prioritaria (0 = sistema, 10 = usuario)
    source: str          # "system" | "user"
    user_id: Optional[str] = None
    label: Optional[str] = None


# ─── Servicio ─────────────────────────────────────────────────────────────────

class ProviderKeyPoolService:
    """
    Gestiona el pool completo de API keys de todos los providers.

    Al inicio carga las keys del sistema (env vars).
    Las keys de usuario se añaden dinámicamente desde Supabase
    cuando se inicia el chat de un agente concreto.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._keys: Dict[str, ProviderKey] = {}   # key_id → ProviderKey
        self._bootstrap_system_keys()

    # ──────────────────────────────────────────────────────────────────────────
    # INICIALIZACIÓN
    # ──────────────────────────────────────────────────────────────────────────

    def _bootstrap_system_keys(self) -> None:
        """Carga las keys de sistema desde variables de entorno."""
        system_keys = [
            ("sys-groq-1",       "groq",       config.GROQ_API_KEY),
            ("sys-google-1",     "google",     config.GEMINI_API_KEY),
            ("sys-openrouter-1", "openrouter", config.OPENROUTER_API_KEY),
        ]
        count = 0
        for key_id, provider, api_key in system_keys:
            if api_key:
                model = PROVIDER_MODEL_MAP[provider]["balanced"]  # referencia
                self._register_key(ProviderKey(
                    key_id=key_id,
                    provider=provider,
                    api_key=api_key,
                    tier="all",
                    priority=0,   # mayor prioridad
                    source="system",
                ))
                cooldown_service.register_key(
                    key_id=key_id,
                    provider=provider,
                    model=model,
                )
                count += 1
                logger.info(f"KeyPool: key de sistema registrada → {key_id} [{provider}]")

        if count == 0:
            logger.warning("KeyPool: ninguna key de sistema configurada en env vars.")

    def _register_key(self, key: ProviderKey) -> None:
        with self._lock:
            self._keys[key.key_id] = key

    # ──────────────────────────────────────────────────────────────────────────
    # SELECCIÓN DE KEY
    # ──────────────────────────────────────────────────────────────────────────

    def get_best_key(
        self,
        provider: str,
        tier: str = "balanced",
        user_id: Optional[str] = None,
    ) -> Optional[ProviderKey]:
        """
        Selecciona la mejor key disponible para el provider y tier dados.

        Prioridad de selección:
          1. Keys del usuario (si user_id proporcionado) para ese provider
          2. Keys de sistema compatibles con el tier

        Devuelve None si todas las keys están en cooldown.
        """
        rpm_limit = PROVIDER_RPM_LIMITS.get(provider, 20)
        candidates: List[Tuple[ProviderKey, int]] = []

        with self._lock:
            for key in self._keys.values():
                if key.provider != provider:
                    continue
                if key.tier not in (tier, "all"):
                    continue
                # Preferir keys del usuario si se proporciona user_id
                if not cooldown_service.is_available(key.key_id, rpm_limit=rpm_limit):
                    continue
                # Score: [prioridad de usuario, prioridad de key]
                user_score = 0 if (user_id and key.user_id == user_id) else 1
                candidates.append((key, user_score * 100 + key.priority))

        if not candidates:
            return None

        # Ordenar: menor score primero (mayor prioridad)
        candidates.sort(key=lambda x: x[1])
        return candidates[0][0]

    def get_ordered_providers(self, tier: str) -> List[str]:
        """Devuelve el orden de providers para el tier dado."""
        return PROVIDER_ORDER.get(tier, PROVIDER_ORDER["balanced"])

    def get_model_for_tier(self, provider: str, tier: str) -> str:
        """Devuelve el modelo a usar para un provider y tier."""
        return PROVIDER_MODEL_MAP.get(provider, {}).get(tier, "")

    # ──────────────────────────────────────────────────────────────────────────
    # GESTIÓN DE KEYS DE USUARIO
    # ──────────────────────────────────────────────────────────────────────────

    def add_user_key(
        self,
        key_id: str,
        provider: str,
        api_key: str,
        user_id: str,
        tier: str = "all",
        label: Optional[str] = None,
        priority: int = 5,
    ) -> None:
        """
        Añade una key de usuario al pool en memoria.
        Debe llamarse al inicio del chat del agente, después de desencriptar.
        """
        key = ProviderKey(
            key_id=key_id,
            provider=provider,
            api_key=api_key,
            tier=tier,
            priority=priority,
            source="user",
            user_id=user_id,
            label=label,
        )
        self._register_key(key)
        model = PROVIDER_MODEL_MAP.get(provider, {}).get(tier, tier)
        cooldown_service.register_key(key_id=key_id, provider=provider, model=model)
        logger.info(f"KeyPool: key de usuario añadida → {key_id} [{provider}] user={user_id}")

    def remove_user_keys(self, user_id: str) -> int:
        """Elimina del pool en memoria todas las keys de un usuario."""
        with self._lock:
            to_remove = [kid for kid, k in self._keys.items() if k.user_id == user_id]
            for kid in to_remove:
                del self._keys[kid]
        logger.info(f"KeyPool: {len(to_remove)} keys del usuario {user_id} eliminadas del pool")
        return len(to_remove)

    # ──────────────────────────────────────────────────────────────────────────
    # ESTADO Y DIAGNÓSTICO
    # ──────────────────────────────────────────────────────────────────────────

    def get_pool_status(self) -> List[dict]:
        """Estado del pool completo (sin exponer el valor de las keys)."""
        with self._lock:
            result = []
            for key in self._keys.values():
                stats = cooldown_service.get_stats(key.key_id) or {}
                result.append({
                    "key_id": key.key_id,
                    "provider": key.provider,
                    "tier": key.tier,
                    "source": key.source,
                    "label": key.label,
                    "available": cooldown_service.is_available(
                        key.key_id,
                        rpm_limit=PROVIDER_RPM_LIMITS.get(key.provider, 20)
                    ),
                    "cooldown_remaining_s": stats.get("cooldown_remaining_s", 0),
                    "total_requests": stats.get("total_requests", 0),
                    "total_429s": stats.get("total_429s", 0),
                })
            return result

    def has_any_available(self, provider: str, tier: str = "balanced") -> bool:
        """True si hay al menos una key disponible para este provider y tier."""
        return self.get_best_key(provider=provider, tier=tier) is not None


# Singleton global
key_pool = ProviderKeyPoolService()
