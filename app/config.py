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

# Configuración del Modelo Personalizado Tenzor Nova (fine-tuned en Vertex AI)
CUSTOM_MODEL_NAME = os.getenv("CUSTOM_MODEL_NAME", "tenz-1-nova")
CUSTOM_MODEL_PROVIDER = os.getenv("CUSTOM_MODEL_PROVIDER", "vertexai")  # ollama, gemini, openai, vertexai
CUSTOM_MODEL_ENDPOINT = os.getenv("CUSTOM_MODEL_ENDPOINT", "http://localhost:11434/v1")
CUSTOM_MODEL_API_KEY = os.getenv("CUSTOM_MODEL_API_KEY", "")
CUSTOM_MODEL_BACKING_NAME = os.getenv("CUSTOM_MODEL_BACKING_NAME", "projects/tenzorai/locations/us-central1/endpoints/mg-endpoint-1eae4fb8-4883-4bfc-8355-08cdb1ee1bb9")

# Variables de Vertex AI para Gestión On-Demand (GCP)
VERTEX_PROJECT_ID = os.getenv("VERTEX_PROJECT_ID", "tenzorai")
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "us-central1")
VERTEX_ENDPOINT_ID = os.getenv("VERTEX_ENDPOINT_ID", "mg-endpoint-1eae4fb8-4883-4bfc-8355-08cdb1ee1bb9")
VERTEX_MODEL_ID = os.getenv("VERTEX_MODEL_ID", "mg-custom-1782292431")
VERTEX_MODEL_VERSION = os.getenv("VERTEX_MODEL_VERSION", "")
VERTEX_AUTOSHUTDOWN_MINUTES = int(os.getenv("VERTEX_AUTOSHUTDOWN_MINUTES", "15"))
VERTEX_ENDPOINT_RESOURCE = os.getenv(
    "VERTEX_ENDPOINT_RESOURCE",
    f"projects/{VERTEX_PROJECT_ID}/locations/{VERTEX_LOCATION}/endpoints/{VERTEX_ENDPOINT_ID}"
)
_DEFAULT_VERTEX_MODEL_RESOURCE = f"projects/{VERTEX_PROJECT_ID}/locations/{VERTEX_LOCATION}/models/{VERTEX_MODEL_ID}"
if VERTEX_MODEL_VERSION and not VERTEX_MODEL_ID.startswith("mg-"):
    _DEFAULT_VERTEX_MODEL_RESOURCE = f"{_DEFAULT_VERTEX_MODEL_RESOURCE}@{VERTEX_MODEL_VERSION}"
VERTEX_MODEL_RESOURCE = os.getenv("VERTEX_MODEL_RESOURCE", _DEFAULT_VERTEX_MODEL_RESOURCE)
VERTEX_DEPLOYED_MODEL_DISPLAY_NAME = os.getenv("VERTEX_DEPLOYED_MODEL_DISPLAY_NAME", "tenz-1-nova")
VERTEX_MACHINE_TYPE = os.getenv("VERTEX_MACHINE_TYPE", "g2-standard-24")
VERTEX_ACCELERATOR_TYPE = os.getenv("VERTEX_ACCELERATOR_TYPE", "NVIDIA_L4")
VERTEX_ACCELERATOR_COUNT = int(os.getenv("VERTEX_ACCELERATOR_COUNT", "2"))
