import os
from google.cloud import logging

# --- CONFIGURACIÓN DE CREDENCIALES ---
NOMBRE_ARCHIVO_JSON = "service_account.json"  
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = NOMBRE_ARCHIVO_JSON

# --- CONFIGURACIÓN DE VERTEX AI ---
PROJECT_ID = "tenzorai"  
ENDPOINT_ID = "mg-endpoint-1eae4fb8-4883-4bfc-8355-08cdb1ee1bb9"
REGION = "us-central1"
OUTPUT_FILE = "errores_deploy.txt"

def obtener_errores_deploy():
    try:
        client = logging.Client(project=PROJECT_ID)
        
        # Filtro estructurado para Vertex AI Endpoints buscando fallos graves
        filter_str = (
            f'resource.type="aiplatform.googleapis.com/Endpoint" AND '
            f'resource.labels.endpoint_id="{ENDPOINT_ID}" AND '
            f'resource.labels.location="{REGION}" AND '
            f'severity>=ERROR'
        )
        
        print(f"Conectando con Google Cloud... Buscando errores en {ENDPOINT_ID}")
        
        # Obtenemos las últimas 500 entradas de error
        entries = client.list_entries(filter_=filter_str, max_results=500)
        
        count = 0
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            f.write(f"=== REPORTE DE ERRORES - ENDPOINT: {ENDPOINT_ID} ===\n\n")
            
            for entry in entries:
                timestamp = entry.timestamp.strftime("%Y-%m-%d %H:%M:%S") if entry.timestamp else "N/A"
                severity = entry.severity
                
                # Extracción segura que tolera tanto TextEntry como StructEntry de Vertex AI
                payload = ""
                if hasattr(entry, 'text_payload') and entry.text_payload:
                    payload = entry.text_payload
                elif hasattr(entry, 'json_payload') and entry.json_payload:
                    payload = entry.json_payload
                elif hasattr(entry, 'payload') and entry.payload:
                    payload = entry.payload
                
                # Si el payload es un diccionario/JSON estructurado, extrae el mensaje interno
                if isinstance(payload, dict):
                    payload = payload.get("message", payload.get("textPayload", str(payload)))
                
                f.write(f"[{timestamp}] [{severity}] {payload}\n")
                f.write("-" * 80 + "\n")
                count += 1
                
        print(f"¡Listo! Se han extraído {count} líneas de error y se guardaron en '{OUTPUT_FILE}'.")
        
    except Exception as e:
        print(f"\n❌ Ocurrió un error al conectar o autenticar: {e}")
        print("Revisa que el ID del proyecto sea correcto y que tu JSON tenga los permisos necesarios.")

if __name__ == "__main__":
    obtener_errores_deploy()