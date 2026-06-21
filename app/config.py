import os
from dotenv import load_dotenv

# Cargar variables del archivo .env si existe (local)
load_dotenv()

PORT = int(os.getenv("PORT", 8000))
HOST = os.getenv("HOST", "0.0.0.0")

ADMIN_SECRET_KEY = os.getenv("ADMIN_SECRET_KEY", "admin-default-key-cambiar")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

DEFAULT_CLIENT_KEY = os.getenv("DEFAULT_CLIENT_KEY", "")

# Configuración del Modelo Personalizado Tenzor Meteor
CUSTOM_MODEL_NAME = os.getenv("CUSTOM_MODEL_NAME", "tenz-1-meteor")
CUSTOM_MODEL_PROVIDER = os.getenv("CUSTOM_MODEL_PROVIDER", "ollama")  # ollama, gemini, openai
CUSTOM_MODEL_ENDPOINT = os.getenv("CUSTOM_MODEL_ENDPOINT", "http://localhost:11434/v1")
CUSTOM_MODEL_API_KEY = os.getenv("CUSTOM_MODEL_API_KEY", "")
CUSTOM_MODEL_BACKING_NAME = os.getenv("CUSTOM_MODEL_BACKING_NAME", "qwen2.5-coder:7b")
