"""
Vuelca SIN FILTRAR las últimas N líneas de log del deploy, en orden
cronológico, para ver exactamente qué está haciendo el contenedor.

Uso:
    python dump_raw_logs.py
"""

from google.oauth2 import service_account
from google.cloud import logging as cloud_logging
import datetime

CREDS       = r"C:\mis-proyectos\Tenzor\service_account.json"
PROJECT_ID  = "tenzorai"
LOCATION    = "us-central1"
ENDPOINT_ID = "5328700090888486912"
DEPLOYED_MODEL_ID = "331969498460454912"

N_LINEAS = 100   # cuántas líneas mostrar (las más recientes)

credentials = service_account.Credentials.from_service_account_file(CREDS)
log_client = cloud_logging.Client(credentials=credentials, project=PROJECT_ID)

filtro = f'''
resource.type="aiplatform.googleapis.com/Endpoint"
resource.labels.endpoint_id="{ENDPOINT_ID}"
labels.deployed_model_id="{DEPLOYED_MODEL_ID}"
timestamp>="{(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=4)).isoformat()}"
'''

# Traemos en orden DESCENDENTE (más reciente primero) y nos quedamos con N,
# luego invertimos para imprimir en orden cronológico.
entries = list(log_client.list_entries(filter_=filtro, order_by=cloud_logging.DESCENDING, page_size=N_LINEAS))
entries = entries[:N_LINEAS]
entries.reverse()

print(f"Mostrando las últimas {len(entries)} líneas (orden cronológico):\n")
print("=" * 100)

for entry in entries:
    payload = entry.payload
    texto = payload if isinstance(payload, str) else str(payload.get("message", payload))
    ts = entry.timestamp.strftime("%H:%M:%S")
    sev = entry.severity or "DEFAULT"
    print(f"[{ts}] {sev:8s} | {texto[:300]}")

print("=" * 100)
print(f"\nTotal mostrado: {len(entries)} líneas")
