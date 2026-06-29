"""
platform_models.py
Modelos Pydantic para la plataforma Arzor AIs Platform.
"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict
from uuid import UUID
from datetime import datetime


# ─── Auth ─────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    username: str = Field(..., min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    display_name: Optional[str] = Field(None, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class ResendConfirmationRequest(BaseModel):
    email: EmailStr


class RecoverPasswordRequest(BaseModel):
    email: EmailStr
    redirect_to: Optional[str] = None


class ResetPasswordRequest(BaseModel):
    password: str = Field(..., min_length=8)




class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str
    display_name: Optional[str] = None


class ProfileResponse(BaseModel):
    id: str
    username: str
    display_name: Optional[str] = None
    bio: Optional[str] = None
    avatar_url: Optional[str] = None
    plan: str
    created_at: datetime
    onboarding_completed: bool = False


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = Field(None, max_length=100)
    bio: Optional[str] = Field(None, max_length=500)
    avatar_url: Optional[str] = None
    onboarding_completed: Optional[bool] = None



# ─── Agents ───────────────────────────────────────────────────────────────────

VALID_CATEGORIES = {"dev", "data", "ops", "creative", "science", "custom"}
VALID_TIERS = {"fast", "balanced", "pro"}


class CreateAgentRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    category: str = Field(..., pattern=r"^(dev|data|ops|creative|science|custom)$")
    base_tier: str = Field("balanced", pattern=r"^(fast|balanced|pro)$")
    system_instructions: str = Field(..., min_length=20, max_length=8000)
    is_public: bool = False
    preferred_provider: Optional[str] = Field(None, pattern=r"^(google|groq|openrouter|deepseek|xai|perplexity|mistral|together|fireworks|cerebras|sambanova|siliconflow|cohere|anthropic|nvidia|cloudflare|huggingface|zai|novita|scaleway|watsonx)$")
    preferred_model: Optional[str] = Field(None, max_length=100)
    fallback_models: Optional[List[Dict[str, str]]] = None


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    category: Optional[str] = Field(None, pattern=r"^(dev|data|ops|creative|science|custom)$")
    base_tier: Optional[str] = Field(None, pattern=r"^(fast|balanced|pro)$")
    is_public: Optional[bool] = None
    preferred_provider: Optional[str] = Field(None, pattern=r"^(google|groq|openrouter|deepseek|xai|perplexity|mistral|together|fireworks|cerebras|sambanova|siliconflow|cohere|anthropic|nvidia|cloudflare|huggingface|zai|novita|scaleway|watsonx)$")
    preferred_model: Optional[str] = Field(None, max_length=100)
    fallback_models: Optional[List[Dict[str, str]]] = None


class AgentVersionResponse(BaseModel):
    id: str
    agent_id: str
    version: int
    system_instructions: str
    behavior_examples: list
    style_rules: dict
    domain_constraints: dict
    retrieval_profile: dict
    created_at: datetime


class AgentResponse(BaseModel):
    id: str
    user_id: str
    name: str
    description: Optional[str] = None
    category: str
    base_tier: str
    is_public: bool
    level: int
    experience: int
    current_version: Optional[AgentVersionResponse] = None
    created_at: datetime
    updated_at: datetime


class AgentListResponse(BaseModel):
    agents: list[AgentResponse]
    total: int


class NewVersionRequest(BaseModel):
    """Permite crear una nueva versión manual del agente con instrucciones actualizadas."""
    system_instructions: str = Field(..., min_length=20, max_length=8000)
    behavior_examples: Optional[list] = Field(default_factory=list)
    style_rules: Optional[dict] = Field(default_factory=dict)
    domain_constraints: Optional[dict] = Field(default_factory=dict)
    retrieval_profile: Optional[dict] = Field(default_factory=dict)
