from google.cloud import aiplatform
from google.cloud import logging
from google.cloud.logging import DESCENDING
import os

# Credenciales y configuración
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"C:\mis-proyectos\Tenzor\service_account.json"

PROJECT_ID = "753320073574"
REGION = "us-central1"
ENDPOINT_ID = "21770879985778688"

def revisar_estado_y_logs():
    print("=" * 60)
    print("🔍 INICIANDO DIAGNÓSTICO DE VERTEX AI")
    print("=" * 60)

    # 1. Revisar el estado del Endpoint
    aiplatform.init(project=PROJECT_ID, location=REGION)
    
    try:
        endpoint = aiplatform.Endpoint(endpoint_name=ENDPOINT_ID)
        modelos_desplegados = endpoint.list_models()
        
        if modelos_desplegados:
            print("✅ ESTADO: ¡El modelo está desplegado y funcionando!")
            print(f"Modelo ID: {modelos_desplegados[0].id}")
            return
        else:
            print("⏳ ESTADO: El modelo no está montado en el endpoint.")
            print("Buscando los registros más recientes del contenedor...\n")
            
    except Exception as e:
        print(f"❌ Error al consultar el Endpoint: {e}\n")

    # 2. Buscar en Cloud Logging si hay errores o registros recientes
    print("-" * 60)
    print("📋 EXTRAYENDO LOGS DEL CONTENEDOR/ENDPOINT...")
    print("-" * 60)
    
    try:
        # Inicializar cliente de logs
        logging_client = logging.Client(project=PROJECT_ID)
        
        # Filtro: Buscamos en Vertex AI para tu Endpoint específico, quitando la restricción de severity >= WARNING
        # para capturar la salida estándar (stdout/stderr) del contenedor vLLM (que suele venir como DEFAULT o INFO)
        filtro_logs = (
            f'resource.type="aiplatform.googleapis.com/Endpoint" '
            f'AND resource.labels.endpoint_id="{ENDPOINT_ID}"'
        )
        
        # Extraer las últimas 100 entradas que coincidan con el filtro
        print(f"Buscando entradas con filtro:\n{filtro_logs}\n")
        entradas = list(logging_client.list_entries(filter_=filtro_logs, order_by=DESCENDING, max_results=100))
        
        if not entradas:
            print("🟢 No se encontraron registros para este Endpoint.")
            print("Verifica que el ENDPOINT_ID y la región sean correctos.")
        else:
            # Los ordenamos cronológicamente (de más antiguo a más reciente) para leer la bitácora
            entradas.reverse()
            print(f"Se encontraron {len(entradas)} líneas de log. Mostrando en orden cronológico:\n")
            for entrada in entradas:
                fecha = entrada.timestamp.strftime("%Y-%m-%d %H:%M:%S")
                severidad = entrada.severity
                
                # Intentamos extraer el payload en cualquiera de sus formatos
                payload = entrada.payload
                
                if isinstance(payload, dict):
                    # Si es JSON, intentamos obtener el mensaje del contenedor o el dict formateado
                    mensaje = payload.get("message") or payload.get("text") or json.dumps(payload)
                else:
                    mensaje = str(payload)
                
                # Quitar saltos de línea sobrantes al final para un formato más limpio
                mensaje = mensaje.strip()
                
                print(f"[{fecha}] [{severidad}] {mensaje}")
                
    except Exception as e:
        print(f"❌ No se pudieron extraer los logs: {e}")

if __name__ == "__main__":
    revisar_estado_y_logs()