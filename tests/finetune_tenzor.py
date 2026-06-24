"""
Script de Fine-Tuning para Tenzor Nova
======================================
Sube el dataset a GCS y lanza el job de fine-tuning en Vertex AI.

Uso:
    python finetune_tenzor.py

Requisitos:
    pip install google-cloud-aiplatform google-cloud-storage

El resultado final se guardará en el archivo .env automáticamente.
"""

import os
import sys
import json
import time
import datetime
from pathlib import Path

# ─── Configuración ────────────────────────────────────────────────────────────

PROJECT_ID       = "tenzorai"
LOCATION         = "us-central1"
MODEL_DISPLAY    = "tenz-1-nova"              # Nombre visible del modelo
BASE_MODEL       = "gemini-2.0-flash-001"     # Modelo base (soporta tuning en Vertex AI)
DATASET_PATH     = "dataset.jsonl"            # Ruta local al dataset
GCS_BUCKET       = f"{PROJECT_ID}-tuning"     # Bucket GCS (se creará si no existe)
GCS_DATASET_PATH = f"gs://{GCS_BUCKET}/datasets/tenz-1-nova/dataset.jsonl"
SA_FILE          = "service_account.json"     # Service account local

# Hiperparámetros
EPOCHS           = 3      # Más épocas = más aprendizaje, más coste. 3 es ideal para 184 ejemplos
LEARNING_RATE    = 0.0001 # Tasa de aprendizaje estándar para fine-tuning

# ─── Helpers ──────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

def setup_credentials():
    """Carga las credenciales de la service account."""
    if os.path.exists(SA_FILE):
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(SA_FILE)
        log(f"✅ Credenciales cargadas desde {SA_FILE}")
        return True
    log(f"❌ No se encontró {SA_FILE}")
    return False

def validate_dataset():
    """Valida el dataset antes de subirlo."""
    log("🔍 Validando dataset...")
    errors = []
    count = 0
    with open(DATASET_PATH, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "contents" not in obj:
                    errors.append(f"Línea {i}: falta 'contents'")
                    continue
                contents = obj["contents"]
                if len(contents) < 2:
                    errors.append(f"Línea {i}: 'contents' necesita al menos 2 mensajes (user + model)")
                    continue
                roles = [c.get("role") for c in contents]
                if "user" not in roles or "model" not in roles:
                    errors.append(f"Línea {i}: se requieren roles 'user' y 'model'")
                count += 1
            except json.JSONDecodeError as e:
                errors.append(f"Línea {i}: JSON inválido - {e}")

    if errors:
        log(f"⚠️  Encontrados {len(errors)} errores:")
        for err in errors[:10]:
            log(f"   {err}")
        if len(errors) > 10:
            log(f"   ... y {len(errors) - 10} más.")
        return False, count

    log(f"✅ Dataset válido: {count} ejemplos correctos")
    return True, count

def create_bucket_if_not_exists(storage_client, bucket_name: str):
    """Crea el bucket GCS si no existe."""
    from google.cloud import exceptions as gcs_exceptions
    try:
        bucket = storage_client.get_bucket(bucket_name)
        log(f"✅ Bucket GCS ya existe: gs://{bucket_name}")
        return bucket
    except gcs_exceptions.NotFound:
        log(f"📦 Creando bucket GCS: gs://{bucket_name}...")
        bucket = storage_client.create_bucket(bucket_name, location=LOCATION)
        log(f"✅ Bucket creado: gs://{bucket_name}")
        return bucket

def upload_dataset_to_gcs():
    """Sube el dataset.jsonl a Google Cloud Storage."""
    from google.cloud import storage

    log("⬆️  Subiendo dataset a Google Cloud Storage...")
    storage_client = storage.Client(project=PROJECT_ID)

    bucket = create_bucket_if_not_exists(storage_client, GCS_BUCKET)

    blob_path = f"datasets/tenz-1-nova/dataset.jsonl"
    blob = bucket.blob(blob_path)
    blob.upload_from_filename(DATASET_PATH, content_type="application/jsonl")

    gcs_uri = f"gs://{GCS_BUCKET}/{blob_path}"
    log(f"✅ Dataset subido a: {gcs_uri}")
    return gcs_uri

def launch_tuning_job(gcs_uri: str):
    """Lanza el job de fine-tuning en Vertex AI."""
    import vertexai
    from vertexai.tuning import sft

    log("🚀 Iniciando job de fine-tuning en Vertex AI...")
    log(f"   Modelo base: {BASE_MODEL}")
    log(f"   Dataset: {gcs_uri}")
    log(f"   Épocas: {EPOCHS}")
    log(f"   Learning rate: {LEARNING_RATE}")

    vertexai.init(project=PROJECT_ID, location=LOCATION)

    tuning_job = sft.train(
        source_model=BASE_MODEL,
        train_dataset=gcs_uri,
        validation_dataset=None,          # Opcional: puedes añadir un dataset de validación
        epochs=EPOCHS,
        learning_rate_multiplier=LEARNING_RATE,
        tuned_model_display_name=MODEL_DISPLAY,
    )

    log(f"✅ Job lanzado con éxito.")
    log(f"   Job ID: {tuning_job.name}")
    log(f"   Estado inicial: {tuning_job.state.name}")

    return tuning_job

def wait_for_job(tuning_job):
    """Espera a que el job complete y muestra el progreso."""
    from google.cloud.aiplatform_v1.types import JobState

    log("⏳ Esperando que el job de tuning complete...")
    log("   (Este proceso puede tardar entre 30 minutos y 2 horas)")
    log("   Puedes cerrar este script y comprobar el estado en la consola de Google Cloud.")
    log("")

    start_time = time.time()
    last_state = None

    while True:
        tuning_job.refresh()
        state = tuning_job.state.name
        elapsed = int(time.time() - start_time)
        elapsed_str = f"{elapsed // 60}m {elapsed % 60}s"

        if state != last_state:
            log(f"   Estado: {state} (transcurrido: {elapsed_str})")
            last_state = state

        # Estados finales
        if state == "JOB_STATE_SUCCEEDED":
            log(f"🎉 ¡Fine-tuning completado con éxito! Tiempo total: {elapsed_str}")
            return True
        elif state in ["JOB_STATE_FAILED", "JOB_STATE_CANCELLED"]:
            log(f"❌ El job terminó con estado: {state}")
            log(f"   Mensaje de error: {getattr(tuning_job, 'error', 'Sin detalle')}")
            return False

        time.sleep(30)  # Revisar cada 30 segundos

def get_tuned_model_resource(tuning_job):
    """Obtiene el resource name del modelo tuneado."""
    try:
        tuned_model = tuning_job.tuned_model
        if tuned_model:
            resource_name = tuned_model.model
            endpoint = tuned_model.endpoint
            log(f"📦 Modelo tuneado:")
            log(f"   Resource: {resource_name}")
            log(f"   Endpoint: {endpoint}")
            return resource_name, endpoint
    except Exception as e:
        log(f"⚠️  No se pudo obtener el resource name: {e}")
    return None, None

def update_env_file(model_resource: str, endpoint: str):
    """Actualiza el .env con el nuevo modelo."""
    env_path = ".env"
    if not os.path.exists(env_path):
        log(f"⚠️  No se encontró {env_path}")
        return

    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Actualizar CUSTOM_MODEL_NAME
    lines = content.splitlines()
    new_lines = []
    updated = {"name": False, "backing": False, "provider": False}

    for line in lines:
        if line.startswith("CUSTOM_MODEL_NAME="):
            new_lines.append(f"CUSTOM_MODEL_NAME={MODEL_DISPLAY}")
            updated["name"] = True
        elif line.startswith("CUSTOM_MODEL_BACKING_NAME="):
            # Usar el endpoint si está disponible, sino el resource name
            value = endpoint if endpoint else model_resource
            new_lines.append(f"CUSTOM_MODEL_BACKING_NAME={value}")
            updated["backing"] = True
        elif line.startswith("CUSTOM_MODEL_PROVIDER="):
            new_lines.append("CUSTOM_MODEL_PROVIDER=vertexai")
            updated["provider"] = True
        else:
            new_lines.append(line)

    # Añadir las líneas que no existían
    if not updated["name"]:
        new_lines.append(f"CUSTOM_MODEL_NAME={MODEL_DISPLAY}")
    if not updated["backing"]:
        value = endpoint if endpoint else model_resource
        new_lines.append(f"CUSTOM_MODEL_BACKING_NAME={value}")
    if not updated["provider"]:
        new_lines.append("CUSTOM_MODEL_PROVIDER=vertexai")

    with open(env_path, "w", encoding="utf-8") as f:
        f.write("\n".join(new_lines))

    log(f"✅ .env actualizado con el nuevo modelo {MODEL_DISPLAY}")
    log(f"   CUSTOM_MODEL_BACKING_NAME={endpoint if endpoint else model_resource}")

def print_summary(tuning_job, model_resource, endpoint):
    """Imprime un resumen final."""
    print("\n" + "═" * 60)
    print("  🌟 RESUMEN FINAL - TENZOR METEOR 1.5")
    print("═" * 60)
    print(f"  Modelo: {MODEL_DISPLAY}")
    print(f"  Job ID: {tuning_job.name}")
    print(f"  Resource: {model_resource or 'Pendiente'}")
    print(f"  Endpoint: {endpoint or 'Pendiente'}")
    print("")
    print("  PRÓXIMOS PASOS:")
    print("  1. El .env ha sido actualizado automáticamente")
    print("  2. Reinicia el servidor: python -m uvicorn app.main:app --reload")
    print("  3. Selecciona 'tenz-1-nova' en la interfaz de Tenzor")
    print("═" * 60 + "\n")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "═" * 60)
    print("  🚀 TENZOR METEOR 1.5 — FINE-TUNING EN VERTEX AI")
    print("═" * 60 + "\n")

    # 1. Verificar dependencias
    log("📦 Verificando dependencias...")
    missing = []
    try:
        import google.cloud.aiplatform
        import google.cloud.storage
        import vertexai
    except ImportError as e:
        missing.append(str(e).split("'")[1] if "'" in str(e) else str(e))

    if missing:
        log(f"❌ Dependencias faltantes: {', '.join(missing)}")
        log("   Instálalas con:")
        log("   pip install google-cloud-aiplatform google-cloud-storage vertexai")
        sys.exit(1)
    log("✅ Dependencias OK")

    # 2. Credenciales
    if not setup_credentials():
        sys.exit(1)

    # 3. Validar dataset
    valid, count = validate_dataset()
    if not valid:
        log("❌ El dataset tiene errores. Corrígelos antes de continuar.")
        sys.exit(1)

    log(f"📊 Se usarán {count} ejemplos para el entrenamiento")

    # 4. Confirmación
    print("")
    print(f"  Modelo base:  {BASE_MODEL}")
    print(f"  Modelo final: {MODEL_DISPLAY}")
    print(f"  Ejemplos:     {count}")
    print(f"  Épocas:       {EPOCHS}")
    print(f"  Proyecto GCP: {PROJECT_ID}")
    print(f"  Región:       {LOCATION}")
    print("")
    confirm = input("  ¿Confirmas el lanzamiento del fine-tuning? (s/N): ").strip().lower()
    if confirm not in ["s", "si", "sí", "y", "yes"]:
        log("❌ Operación cancelada por el usuario.")
        sys.exit(0)
    print("")

    # 5. Subir dataset a GCS
    gcs_uri = upload_dataset_to_gcs()

    # 6. Lanzar job
    tuning_job = launch_tuning_job(gcs_uri)

    # 7. Esperar (opcional — el usuario puede cancelar con Ctrl+C)
    print("")
    print("  Puedes dejar este script corriendo para esperar el resultado,")
    print("  o presionar Ctrl+C para salir (el job seguirá corriendo en la nube).")
    print("")

    try:
        success = wait_for_job(tuning_job)
    except KeyboardInterrupt:
        log("⏸️  Script interrumpido. El job sigue corriendo en Google Cloud.")
        log(f"   Job ID: {tuning_job.name}")
        log(f"   Comprueba el estado en: https://console.cloud.google.com/vertex-ai/training/custom-jobs?project={PROJECT_ID}")
        sys.exit(0)

    # 8. Obtener resource y actualizar .env
    if success:
        model_resource, endpoint = get_tuned_model_resource(tuning_job)
        if model_resource or endpoint:
            update_env_file(model_resource, endpoint)
        print_summary(tuning_job, model_resource, endpoint)
    else:
        log("❌ El fine-tuning falló. Revisa los logs en Google Cloud Console.")
        log(f"   https://console.cloud.google.com/vertex-ai/training/custom-jobs?project={PROJECT_ID}")
        sys.exit(1)

if __name__ == "__main__":
    main()
