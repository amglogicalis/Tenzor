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
