"""
1) Muestra el artifactUri del Model desplegado (para confirmar si apunta
   al tenant bucket o a tu bucket).
2) Lista las últimas entradas de log del endpoint filtrando por errores
   reales (excepciones, 404, exit code != 0), no solo por severity=ERROR.

Uso:
    pip install google-cloud-aiplatform google-cloud-logging
    python check_model_and_real_errors.py
"""

from google.cloud import aiplatform
from google.oauth2 import service_account
from google.cloud import logging as cloud_logging
import datetime

CREDS       = r"C:\mis-proyectos\Tenzor\service_account.json"
PROJECT_ID  = "tenzorai"
LOCATION    = "us-central1"
ENDPOINT_ID = "5328700090888486912"          # del log que pegaste
DEPLOYED_MODEL_ID = "331969498460454912"     # también del log

credentials = service_account.Credentials.from_service_account_file(CREDS)
aiplatform.init(project=PROJECT_ID, location=LOCATION, credentials=credentials)

# ── 1. Artifact URI del modelo ──────────────────────────────────────
print("=" * 70)
print("  ARTIFACT URI DEL MODELO DESPLEGADO")
print("=" * 70)

ep = aiplatform.Endpoint(endpoint_name=ENDPOINT_ID)
for dm in ep.list_models():
    print(f"\nDeployedModel ID : {dm.id}")
    print(f"Model resource   : {dm.model}")
    try:
        model = aiplatform.Model(model_name=dm.model)
        print(f"artifactUri      : {model.uri}")
        if "caip-tenant" in (model.uri or ""):
            print("⚠️  CONFIRMADO: el Model apunta al tenant bucket, no a tu bucket.")
            print("    Por eso el deploy ignora todos los cambios en tenzorai-tuning.")
        elif "tenzorai-tuning" in (model.uri or ""):
            print("✅ El Model SÍ apunta a tu bucket. El problema sería otro.")
    except Exception as e:
        print(f"  No se pudo leer el Model resource: {e}")

# ── 2. Buscar errores reales en los logs (no solo severity=ERROR) ──
print("\n" + "=" * 70)
print("  BUSCANDO ERRORES REALES (excepciones, 404, fallos de copia)")
print("=" * 70)

log_client = cloud_logging.Client(credentials=credentials, project=PROJECT_ID)

filtro = f'''
resource.type="aiplatform.googleapis.com/Endpoint"
resource.labels.endpoint_id="{ENDPOINT_ID}"
labels.deployed_model_id="{DEPLOYED_MODEL_ID}"
timestamp>="{(datetime.datetime.utcnow() - datetime.timedelta(hours=2)).isoformat("T")}Z"
'''

entries = log_client.list_entries(filter_=filtro, order_by=cloud_logging.DESCENDING)

palabras_clave = [
    "Traceback", "Exception", "FileNotFoundError", "404",
    "No such file", "failed", "Failed", "CRITICAL", "exit code",
    "OSError", "not found", "could not", "Error copying", "Error opening"
]

encontrados = 0
for entry in entries:
    if encontrados >= 30:
        break
    payload = entry.payload
    texto = payload if isinstance(payload, str) else str(payload.get("message", payload))
    if any(k.lower() in texto.lower() for k in palabras_clave):
        encontrados += 1
        print(f"\n[{entry.timestamp}] severity={entry.severity}")
        print(texto[:500])

if encontrados == 0:
    print("\n(No se encontraron excepciones/404 explícitos en las últimas 2h.")
    print(" Puede que el deploy siga copiando ~28GB de pesos — eso tarda.")
    print(" Si el mensaje 'Copying ... vocab.json' fue el último log y no hay")
    print(" nada más después de varios minutos, lo normal es que siga en curso.)")