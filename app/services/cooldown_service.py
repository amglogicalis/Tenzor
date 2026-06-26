"""
cooldown_service.py
Gestión de cooldowns por API key y conteo de errores 429.

Arquitectura:
  - Estado en memoria (dict) como cache rápido para evitar hits a DB en cada request.
  - Persistencia en Supabase (tabla provider_usage_events) para auditoría y métricas.
  - Thread-safe via threading.Lock().
  - Backoff exponencial con jitter completo: t = base * 2^n * rand(0.5, 1.5)

Motivos de cooldown soportados:
  - 429 Too Many Requests          → cooldown proporcional al retry-after header
  - 503 Service Unavailable        → cooldown corto + retry
  - 401/403 Auth error             → key marcada como inválida permanentemente
  - Timeout (red)                  → cooldown corto

Estrategia de ventana deslizante (RPM):
  - Por cada key se lleva un contador de peticiones en los últimos 60s.
  - Si el contador supera el límite del provider, la key entra en cooldown suave
    aunque no haya recibido un 429 real (protección preventiva).
"""
import time
import random
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from enum import Enum

from app import config

logger = logging.getLogger(__name__)


# ─── Tipos ────────────────────────────────────────────────────────────────────

class CooldownReason(str, Enum):
    RATE_LIMIT_429   = "rate_limit_429"       # 429 explícito del provider
    SERVICE_DOWN_503 = "service_down_503"     # 503 / overload
    AUTH_ERROR       = "auth_error"           # 401/403 → key inválida
    TIMEOUT          = "timeout"              # timeout de red
    PREVENTIVE       = "preventive"           # límite RPM alcanzado internamente


@dataclass
class KeyState:
    """Estado en memoria de una API key individual."""
    key_id: str
    provider: str
    model: str

    # Cooldown
    cooldown_until: float = 0.0             # timestamp UNIX hasta el que está en cooldown
    reason: Optional[CooldownReason] = None
    consecutive_errors: int = 0             # errores 429 consecutivos (para backoff)
    is_permanently_invalid: bool = False    # True si 401/403

    # Ventana deslizante RPM (últimos 60s)
    request_timestamps: List[float] = field(default_factory=list)

    # Estadísticas de vida
    total_requests: int = 0
    total_429s: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    last_used: float = 0.0

    def is_available(self, rpm_limit: int = 60) -> bool:
        """True si la key está disponible para usar ahora mismo."""
        if self.is_permanently_invalid:
            return False
        now = time.monotonic()
        if self.cooldown_until > now:
            return False
        # Limpieza de ventana deslizante
        cutoff = now - 60.0
        self.request_timestamps = [t for t in self.request_timestamps if t > cutoff]
        if len(self.request_timestamps) >= rpm_limit:
            return False
        return True

    def seconds_until_available(self) -> float:
        """Segundos restantes de cooldown (0 si disponible)."""
        remaining = self.cooldown_until - time.monotonic()
        return max(0.0, remaining)

    def record_request(self):
        self.request_timestamps.append(time.monotonic())
        self.total_requests += 1
        self.last_used = time.time()

    def record_success(self, tokens_in: int = 0, tokens_out: int = 0):
        self.consecutive_errors = 0
        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out

    def record_429(self, retry_after_seconds: Optional[float] = None):
        self.consecutive_errors += 1
        self.total_429s += 1
        cooldown = _calculate_backoff(
            consecutive=self.consecutive_errors,
            base=config.ARZOR_COOLDOWN_BASE_SECONDS,
            override_seconds=retry_after_seconds,
        )
        self.cooldown_until = time.monotonic() + cooldown
        self.reason = CooldownReason.RATE_LIMIT_429
        logger.warning(
            f"CooldownService: key '{self.key_id}' [{self.provider}] en cooldown "
            f"{cooldown:.0f}s (intento #{self.consecutive_errors})"
        )

    def record_503(self):
        cooldown = min(30.0 * (2 ** min(self.consecutive_errors, 3)), 300.0)
        self.cooldown_until = time.monotonic() + cooldown
        self.reason = CooldownReason.SERVICE_DOWN_503
        self.consecutive_errors += 1

    def record_auth_error(self):
        self.is_permanently_invalid = True
        self.reason = CooldownReason.AUTH_ERROR
        logger.error(
            f"CooldownService: key '{self.key_id}' [{self.provider}] marcada como inválida (401/403)"
        )

    def record_timeout(self):
        cooldown = 15.0
        self.cooldown_until = time.monotonic() + cooldown
        self.reason = CooldownReason.TIMEOUT


# ─── Backoff helper ───────────────────────────────────────────────────────────

def _calculate_backoff(
    consecutive: int,
    base: float = 60.0,
    override_seconds: Optional[float] = None,
) -> float:
    """
    Backoff exponencial con jitter completo.
    Si el provider envía un Retry-After, lo usamos como suelo.

    Fórmula: base * 2^(n-1) * rand(0.5, 1.5)
    Caps: mínimo 10s, máximo 900s (15 min).
    """
    if override_seconds and override_seconds > 0:
        # Respetar el Retry-After del provider + jitter pequeño
        return min(override_seconds * random.uniform(1.0, 1.2), 180.0)

    exponent = min(consecutive - 1, 4)   # cap en 2^4 = 16
    backoff = base * (2 ** exponent) * random.uniform(0.5, 1.2)
    return max(5.0, min(backoff, 180.0))


# ─── Servicio principal ────────────────────────────────────────────────────────

class CooldownService:
    """
    Gestiona el estado de cooldown de todas las API keys en memoria.
    Thread-safe.

    No requiere Supabase para funcionar (estado en RAM).
    Los eventos de uso se persisten en Supabase de forma asíncrona
    si está disponible.
    """

    def __init__(self):
        self._states: Dict[str, KeyState] = {}
        self._lock = threading.Lock()
        logger.info("CooldownService: inicializado.")

    # ──────────────────────────────────────────────────────────────────────────
    # API PÚBLICA
    # ──────────────────────────────────────────────────────────────────────────

    def register_key(self, key_id: str, provider: str, model: str) -> None:
        """Registra una key en el estado (si no existe ya)."""
        with self._lock:
            if key_id not in self._states:
                self._states[key_id] = KeyState(
                    key_id=key_id, provider=provider, model=model
                )

    def is_available(self, key_id: str, rpm_limit: int = 60) -> bool:
        """True si la key puede usarse ahora mismo."""
        with self._lock:
            state = self._states.get(key_id)
            if state is None:
                return True   # key desconocida: asumir disponible
            return state.is_available(rpm_limit=rpm_limit)

    def record_request(self, key_id: str) -> None:
        """Registra que se va a usar la key (ventana deslizante RPM)."""
        with self._lock:
            state = self._states.get(key_id)
            if state:
                state.record_request()

    def record_success(self, key_id: str, tokens_in: int = 0, tokens_out: int = 0) -> None:
        with self._lock:
            state = self._states.get(key_id)
            if state:
                state.record_success(tokens_in=tokens_in, tokens_out=tokens_out)

    def record_429(self, key_id: str, retry_after: Optional[float] = None) -> None:
        with self._lock:
            state = self._states.get(key_id)
            if state:
                state.record_429(retry_after_seconds=retry_after)

    def record_503(self, key_id: str) -> None:
        with self._lock:
            state = self._states.get(key_id)
            if state:
                state.record_503()

    def record_auth_error(self, key_id: str) -> None:
        with self._lock:
            state = self._states.get(key_id)
            if state:
                state.record_auth_error()

    def record_timeout(self, key_id: str) -> None:
        with self._lock:
            state = self._states.get(key_id)
            if state:
                state.record_timeout()

    def seconds_until_available(self, key_id: str) -> float:
        with self._lock:
            state = self._states.get(key_id)
            if state is None:
                return 0.0
            return state.seconds_until_available()

    def get_stats(self, key_id: str) -> Optional[dict]:
        """Devuelve estadísticas de la key (útil para dashboards)."""
        with self._lock:
            state = self._states.get(key_id)
            if not state:
                return None
            return {
                "key_id": state.key_id,
                "provider": state.provider,
                "is_available": state.is_available(),
                "is_permanently_invalid": state.is_permanently_invalid,
                "cooldown_remaining_s": round(state.seconds_until_available(), 1),
                "consecutive_errors": state.consecutive_errors,
                "total_requests": state.total_requests,
                "total_429s": state.total_429s,
                "total_tokens_in": state.total_tokens_in,
                "total_tokens_out": state.total_tokens_out,
                "last_used": state.last_used,
            }

    def reset_key(self, key_id: str) -> bool:
        """Reinicia el cooldown de una key (uso administrativo)."""
        with self._lock:
            state = self._states.get(key_id)
            if not state:
                return False
            state.cooldown_until = 0.0
            state.consecutive_errors = 0
            state.is_permanently_invalid = False
            state.reason = None
            return True

    def get_all_stats(self) -> List[dict]:
        """Estadísticas de todas las keys registradas."""
        with self._lock:
            return [
                {
                    "key_id": s.key_id,
                    "provider": s.provider,
                    "available": s.is_available(),
                    "invalid": s.is_permanently_invalid,
                    "cooldown_s": round(s.seconds_until_available(), 1),
                    "errors": s.consecutive_errors,
                    "requests": s.total_requests,
                    "rate_429s": s.total_429s,
                }
                for s in self._states.values()
            ]


# Singleton global
cooldown_service = CooldownService()
