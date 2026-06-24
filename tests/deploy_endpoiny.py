import os
from datetime import datetime
try:
    import vertexai
    from vertexai.preview import model_garden
except ImportError:
    import sys
    sys.exit("ERROR: Ejecuta: pip install 'google-cloud-aiplatform>=1.95.0'")

# --- CONFIGURACIÓN EXACTA EXTRAÍDA DE TU SCRIPT V5 ---
CREDENTIALS_PATH = r"C:\mis-proyectos\Tenzor\service_account.json"
PROJECT_ID       = "753320073574"
REGION           = "us-central1"

BUCKET_NAME      = "tenzorai-tuning"
RUN_NAME         = "tenz-2-meteor"
OUTPUT_GCS_URI   = f"gs://{BUCKET_NAME}/output/{RUN_NAME}/"

# Esta es la ruta a TU bucket donde el entrenamiento dejará los pesos finales.
# Usar esto evita el "bug del tenant bucket" de Google.
CHECKPOINT_URI   = f"{OUTPUT_GCS_URI}postprocess/node-0/checkpoints/final"

MACHINE_TYPE     = "g2-standard-24"
ACCEL_TYPE       = "NVIDIA_L4"
ACCEL_COUNT      = 2

# Le añado "-recovery-" al nombre para que lo distingas fácilmente en la consola
ENDPOINT_DISPLAY = f"tenz-meteor-recovery-{datetime.now().strftime('%m%d%H%M')}"

def main():
    print("🔄 Inicializando credenciales y Vertex AI...")
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_PATH
    vertexai.init(project=PROJECT_ID, location=REGION)

    print(f"📦 Preparando el modelo directamente desde TU bucket seguro:")
    print(f"   Ruta: {CHECKPOINT_URI}")
    
    # CustomModel es la clave aquí: carga desde tu GCS en lugar del registro de Vertex
    model = model_garden.CustomModel(gcs_uri=CHECKPOINT_URI)

    print(f"🚀 Iniciando el despliegue en {MACHINE_TYPE} con {ACCEL_COUNT}x {ACCEL_TYPE}...")
    print("⏳ Esto tardará entre 15 y 20 minutos (tiene que cargar ~28GB a VRAM).")
    print("⚠️ Por favor, no cierres esta consola. Esperando respuesta de Google...")

    try:
        # Desplegamos el modelo creando un endpoint nuevo
        endpoint = model.deploy(
            machine_type=MACHINE_TYPE,
            accelerator_type=ACCEL_TYPE,
            accelerator_count=ACCEL_COUNT,
            endpoint_display_name=ENDPOINT_DISPLAY,
            deploy_request_timeout=2700, # 45 minutos de timeout
        )
        print("======================================================")
        print(f"🎉 ¡DESPLIEGUE RECUPERADO Y COMPLETADO CON ÉXITO! 🎉")
        print(f"📍 Endpoint ID: {endpoint.resource_name}")
        print("======================================================")
        
        print("\nPrueba de predicción rápida...")
        resp = endpoint.predict(
            instances=[{
                "messages": [{"role": "user", "content": "¿Cómo despliego un contenedor en Cloud Run con Terraform?"}],
                "max_tokens": 200,
            }]
        )
        print(f"✅ Respuesta del modelo:\n{resp}")

    except Exception as e:
        print(f"\n❌ Error durante el despliegue: {e}")

if __name__ == "__main__":
    main()