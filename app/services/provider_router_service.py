"""
provider_router_service.py
Router de inferencias: selecciona proveedor y modelo según el tier,
gestiona fallbacks y registra los eventos de uso.
Implementado en Fase 4.
"""
# TODO (Fase 4): inferir(messages, agent_id, user_id, tier) -> InferenceResult
# Tiers: fast | balanced | pro
# Proveedores por tier:
#   fast:     groq (llama-3.1-8b) → openrouter (fallback) → google (gemini-flash-lite, último fallback)
#   balanced: groq (llama-3.3-70b) → google (gemini-2.5-flash) → openrouter
#   pro:      google (gemini-2.5-pro) → openrouter (claude/gpt4o) → groq (70b)
# TODO (Fase 4): Si 429 → marcar cooldown → intentar siguiente key/proveedor
# TODO (Fase 4): Registrar evento en provider_usage_events
