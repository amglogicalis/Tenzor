from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class Message(BaseModel):
    role: str
    content: str
    images: Optional[List[str]] = None

class ChatCompletionRequest(BaseModel):
    model: str = "tenzor-dev"
    messages: List[Message]
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = None
    stream: Optional[bool] = False

class ChatCompletionResponseChoice(BaseModel):
    index: int
    message: Message
    finish_reason: Optional[str] = "stop"

class ChatCompletionResponseUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionResponseChoice]
    usage: Optional[ChatCompletionResponseUsage] = None

# Para la gestión de API Keys en Supabase / Admin endpoints
class APIKeyCreate(BaseModel):
    owner_name: str
    rate_limit: Optional[int] = 100
    expires_in_days: Optional[int] = None
    allow_custom_model: Optional[bool] = False

class APIKeyResponse(BaseModel):
    id: str
    key: str
    owner_name: str
    is_active: bool
    rate_limit: int
    requests_today: int
    total_requests: int
    created_at: str
    expires_at: Optional[str] = None
    allow_custom_model: bool = False
