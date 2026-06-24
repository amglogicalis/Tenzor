"""
Comprueba si el DeployedModel ya está listo para servir tráfico,
y si no, busca en los logs evidencia de arranque de vLLM
(Uvicorn / Application startup) o de un traceback real de Python.

Uso:
    python check_model_ready.py
"""

from google.cloud import aiplatform
from google.oauth2 import service_account
from google.cloud import logging as cloud_logging
import datetime

CREDS       = r"C:\mis-proyectos\Tenzor\service_account.json"
PROJECT_ID  = "tenzorai"
LOCATION    = "us-central1"
ENDPOINT_ID = "5328700090888486912"
DEPLOYED_MODEL_ID = "331969498460454912"

credentials = service_account.Credentials.from_service_account_file(CREDS)
aiplatform.init(project=PROJECT_ID, location=LOCATION, credentials=credentials)

# ── 1. Estado del endpoint / tráfico ────────────────────────────────
print("=" * 70)
print("  ESTADO DEL ENDPOINT")
print("=" * 70)

ep = aiplatform.Endpoint(endpoint_name=ENDPOINT_ID)
traffic_split = ep.traffic_split
print(f"Traffic split: {traffic_split}")

if traffic_split.get(DEPLOYED_MODEL_ID, 0) > 0:
    print("✅ El DeployedModel tiene tráfico asignado -> normalmente significa que pasó el health check.")
else:
    print("⏳ Sin tráfico asignado todavía -> el modelo sigue cargando o no ha pasado el health check.")

# ── 2. Probar predicción real (esto es la prueba definitiva) ───────
print("\n" + "=" * 70)
print("  PROBANDO PREDICCIÓN DE PRUEBA")
print("=" * 70)
try:
    resp = ep.predict(instances=[{"prompt": "Hola", "max_tokens": 5}])
    print("✅ ¡El modelo respondió! Está vivo y sirviendo.")
    print(resp)
except Exception as e:
    print(f"⚠️ La predicción de prueba falló (puede ser normal si aún está cargando): {e}")

# ── 3. Buscar en logs evidencia de arranque exitoso o traceback real ─
print("\n" + "=" * 70)
print("  BUSCANDO 'ARRANQUE EXITOSO' O TRACEBACK REAL EN LOGS")
print("=" * 70)

log_client = cloud_logging.Client(credentials=credentials, project=PROJECT_ID)

filtro = f'''
resource.type="aiplatform.googleapis.com/Endpoint"
resource.labels.endpoint_id="{ENDPOINT_ID}"
labels.deployed_model_id="{DEPLOYED_MODEL_ID}"
timestamp>="{(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=3)).isoformat()}"
'''

entries = list(log_client.list_entries(filter_=filtro, order_by=cloud_logging.ASCENDING))
print(f"Total de líneas de log en las últimas 3h: {len(entries)}\n")

claves_exito = ["Uvicorn running", "Application startup complete", "Started server process", "Avg prompt throughput"]
claves_fallo = ["Traceback (most recent call last)", "raise ", "OSError", "FileNotFoundError", "RuntimeError", "CUDA out of memory"]

exito_encontrado = False
fallo_encontrado = False

for entry in entries:
    payload = entry.payload
    texto = payload if isinstance(payload, str) else str(payload.get("message", payload))

    if any(k in texto for k in claves_exito):
        exito_encontrado = True
        print(f"✅ [{entry.timestamp}] {texto[:300]}")

    if any(k in texto for k in claves_fallo):
        fallo_encontrado = True
        print(f"❌ [{entry.timestamp}] {texto[:500]}")

print()
if exito_encontrado and not fallo_encontrado:
    print("✅ Encontré señales de arranque exitoso del servidor de inferencia.")
elif fallo_encontrado:
    print("❌ Encontré una excepción real de Python -- pégamela y la revisamos.")
else:
    print("⏳ No hay ni señal de éxito ni de traceback todavía.")
    print("   Con un modelo de 14B (~28GB) cargando en 2xL4, lo normal es que")
    print("   tarde entre 5 y 15 minutos solo en cargar los pesos a VRAM.")
    print("   Vuelve a ejecutar este script en unos minutos.")