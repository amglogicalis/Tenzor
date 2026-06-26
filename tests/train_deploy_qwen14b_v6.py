#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════════════════════════╗
║  VERTEX AI · QWEN3-14B · FULL FINE-TUNING + DEPLOY · v6.0 — DEFINITIVO        ║
║  Tenzor Meteor — DevOps / Cloud / Programación                               ║
╚═══════════════════════════════════════════════════════════════════════════════╝

Qué hace este script, en orden:

  1. Sube el dataset final (dataset_final.jsonl, ~700 ejemplos) a GCS.
  2. Lanza el job de FULL fine-tuning (no LoRA) de Qwen3-14B directamente en
     europe-west4 (sin pasar por us-central1, que venía dando error de "alta
     demanda" en el tuning gestionado).
  3. Espera a que el job termine, sondeando el estado cada 60s.
  4. Despliega el resultado SIEMPRE en us-central1 (donde tienes cuota de
     2x L4), usando vertexai.preview.model_garden.CustomModel apuntando
     directamente a tu bucket de salida. Este método NUNCA ha mostrado el
     problema de archivos faltantes (special_tokens_map.json, vocab.json,
     merges.txt, etc.) que sí daba el método viejo de Model.upload() manual
     con argumentos de vLLM — ese problema era del MÉTODO, no de la región,
     así que aquí no hay fallback de región: si el deploy falla, es por otra
     causa real (cuota de GPU agotada, error de configuración) y el script
     te lo muestra explícitamente en vez de reintentar a ciegas.
  5. Prueba el endpoint con una predicción real.

IMPORTANTE: antes de ejecutar esto, asegúrate de tener dataset_final.jsonl
(generado por improve_dataset.py) en la ruta configurada abajo.
"""

from __future__ import annotations

import os
import sys
import time
import logging
from datetime import datetime

try:
    import vertexai
    from vertexai.tuning import sft, SourceModel
    from vertexai.preview import model_garden
    from google.cloud import storage
    from google.api_core import exceptions as gexc
except ImportError:
    sys.exit("ERROR: Ejecuta: pip install 'google-cloud-aiplatform>=1.95.0' google-cloud-storage")

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════

CREDENTIALS_PATH = r"C:\mis-proyectos\Tenzor\service_account.json"
PROJECT_ID       = "753320073574"

# Región de DEPLOY — fija, porque aquí es donde tienes cuota de 2x L4.
DEPLOY_REGION    = "us-central1"

# Región de TUNING — lanzamos directo en europe-west4, sin probar antes
# en us-central1 (ya sabemos que está saturado).
TUNING_REGIONS   = ["europe-west4"]

BUCKET_NAME      = "tenzorai-tuning"

# Dataset final ya mejorado (duplicados fuera, rechazos + GCP añadidos)
LOCAL_DATASET    = r"C:\mis-proyectos\Tenzor\dataset_final.jsonl"

RUN_NAME         = "tenz-3-final"
DATASET_GCS_URI  = f"gs://{BUCKET_NAME}/datasets/{RUN_NAME}/train.jsonl"
OUTPUT_GCS_URI   = f"gs://{BUCKET_NAME}/output/{RUN_NAME}/"

BASE_MODEL       = "qwen/qwen3@qwen3-14b"

# ── Hiperparámetros de tuning ────────────────────────────────────────────────
# ~700 ejemplos de calidad, dominio DevOps/Cloud/programación + rechazo
# fuera-de-dominio. 3 épocas en FULL fine-tuning fija bien el estilo/dominio
# sin caer en olvido catastrófico severo. learning_rate_multiplier NO se
# pasa porque Vertex lo rechaza para full fine-tuning de Qwen3 (ya probado:
# 400 INVALID_ARGUMENT "Learning rate multiplier is not supported").
EPOCHS           = 3
TUNING_MODE      = "FULL"        # "FULL" o "PEFT_ADAPTER"

# ── Configuración de deploy (serving) — 2x L4 obligatorio para 14B ─────────
MACHINE_TYPE   = "g2-standard-24"   # 24 vCPU / 96GB RAM, soporta 2x L4
ACCEL_TYPE     = "NVIDIA_L4"
ACCEL_COUNT    = 2                  # imprescindible: con 1x L4 (24GB) no
                                      # cabe un 14B en bf16 (~28GB) + KV cache

ENDPOINT_DISPLAY = f"tenz-meteor-{datetime.now().strftime('%m%d%H%M')}"
DEPLOY_TIMEOUT   = 2700  # 45 min — cargar ~28GB a VRAM puede tardar

# ══════════════════════════════════════════════════════════════════════════════

TS = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = f"train_deploy_{TS}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(LOG_FILE, encoding="utf-8")],
)
log = logging.getLogger("qwen3-train-deploy-v6")

# Errores que consideramos "de capacidad/alta demanda" -> reintentar en otra
# región. Cualquier otro error (config, IAM, dataset mal formado) NO se
# reintenta, se muestra y se detiene, porque reintentar no lo arregla.
CAPACIDAD_KEYWORDS = [
    "high demand", "alta demanda", "RESOURCE_EXHAUSTED",
    "currently experiencing", "try again in a different region",
    "capacity", "no disponible temporalmente",
]


def sep(title: str = "", width: int = 78) -> None:
    if title:
        pad = max(width - len(title) - 7, 2)
        log.info(f"{'─' * 4} {title} {'─' * pad}")
    else:
        log.info("─" * width)


def es_error_de_capacidad(exc: Exception) -> bool:
    texto = str(exc).lower()
    return any(k.lower() in texto for k in CAPACIDAD_KEYWORDS) or isinstance(
        exc, (gexc.ResourceExhausted, gexc.ServiceUnavailable)
    )


def step_upload_dataset() -> None:
    sep("PASO 1/4 · Subiendo dataset final a GCS")
    if not os.path.exists(LOCAL_DATASET):
        sys.exit(f"  ❌ No encuentro {LOCAL_DATASET}. Genera primero dataset_final.jsonl.")

    client = storage.Client.from_service_account_json(CREDENTIALS_PATH)
    bucket = client.bucket(BUCKET_NAME)
    blob_path = DATASET_GCS_URI.replace(f"gs://{BUCKET_NAME}/", "")
    blob = bucket.blob(blob_path)
    blob.upload_from_filename(LOCAL_DATASET)

    n_lineas = sum(1 for _ in open(LOCAL_DATASET, encoding="utf-8"))
    log.info(f"  ✅ Subido: {DATASET_GCS_URI} ({n_lineas} ejemplos)")


def step_launch_tuning():
    """Lanza el tuning job directamente en TUNING_REGIONS[0] (europe-west4).
    Si Vertex devuelve un error de capacidad, lo informa con claridad en vez
    de fallar con un traceback genérico; no hay fallback automático de
    región porque así lo pediste — si europe-west4 también está saturado,
    añade otra región a TUNING_REGIONS y vuelve a lanzar."""
    sep("PASO 2/4 · Lanzando job de FULL fine-tuning en europe-west4")
    log.info(f"  Modelo base : {BASE_MODEL}")
    log.info(f"  Modo        : {TUNING_MODE}")
    log.info(f"  Épocas      : {EPOCHS}")
    log.info(f"  Dataset     : {DATASET_GCS_URI}")
    log.info(f"  Output      : {OUTPUT_GCS_URI}")

    ultimo_error = None
    for i, region in enumerate(TUNING_REGIONS, start=1):
        log.info(f"\n  ── Intento {i}/{len(TUNING_REGIONS)} · región: {region} ──")
        try:
            vertexai.init(project=PROJECT_ID, location=region)
            job = sft.train(
                source_model=SourceModel(base_model=BASE_MODEL),
                tuning_mode=TUNING_MODE,
                epochs=EPOCHS,
                train_dataset=DATASET_GCS_URI,
                output_uri=OUTPUT_GCS_URI,
            )
            log.info(f"  ✅ Job aceptado en {region}: {job.resource_name}")
            return job, region
        except Exception as exc:
            ultimo_error = exc
            if es_error_de_capacidad(exc):
                log.warning(f"  ⚠️ Capacidad agotada en {region}: {exc}")
                if i < len(TUNING_REGIONS):
                    log.warning("     Probando siguiente región...")
                continue
            else:
                # Error real de configuración (dataset, IAM, parámetro
                # inválido) — no tiene sentido reintentar en otra región.
                log.error(f"  ❌ Error NO relacionado con capacidad: {exc}")
                log.error("     Esto no se arregla cambiando de región. Deteniendo.")
                raise

    log.error(f"\n  ❌ La región {TUNING_REGIONS[0]} está saturada ahora mismo.")
    log.error(f"     Último error: {ultimo_error}")
    log.error("     Prueba más tarde, o añade otra región a TUNING_REGIONS y relanza.")
    sys.exit(1)


def step_wait_for_tuning(job, region: str) -> None:
    sep("PASO 3/4 · Esperando a que termine el entrenamiento")
    log.info(f"  Región del job: {region}")
    poll_seconds = 60
    while not job.has_ended:
        job.refresh()
        log.info(f"  Estado actual: {job.state}")
        time.sleep(poll_seconds)

    job.refresh()
    if job.has_succeeded:
        log.info("  🎉 Entrenamiento completado con éxito.")
    else:
        log.error(f"  ❌ El job terminó sin éxito. Estado: {job.state}")
        if getattr(job, "error", None):
            log.error(f"     Error: {job.error}")
        sys.exit(1)


def step_deploy():
    """Despliega SIEMPRE en DEPLOY_REGION usando CustomModel. Sin fallback de
    región aquí: si esto falla, no es un problema de capacidad de tuning,
    es otra cosa (cuota de GPU, checkpoint incompleto) y hay que verlo, no
    reintentar a ciegas en otra región sin tu cuota de 2x L4."""
    sep(f"PASO 4/4 · Desplegando en {DEPLOY_REGION} (2x {ACCEL_TYPE})")

    # Re-inicializar el SDK en la región de DEPLOY, que puede ser distinta
    # a la región donde corrió el tuning.
    vertexai.init(project=PROJECT_ID, location=DEPLOY_REGION)

    checkpoint_uri = f"{OUTPUT_GCS_URI}postprocess/node-0/checkpoints/final"
    log.info(f"  Cargando pesos desde: {checkpoint_uri}")
    log.info("  (Esta ruta es TU bucket, nunca el tenant bucket temporal de Vertex)")

    try:
        model = model_garden.CustomModel(gcs_uri=checkpoint_uri)
    except Exception as exc:
        log.error(f"  ❌ No se pudo registrar el modelo desde {checkpoint_uri}: {exc}")
        log.error("     Verifica con gsutil ls que esa carpeta tiene todos los")
        log.error("     archivos (config.json, *.safetensors, tokenizer*, vocab.json).")
        raise

    log.info(f"  Desplegando en {MACHINE_TYPE} / {ACCEL_COUNT}x {ACCEL_TYPE} ...")
    log.info("  Timeout: hasta 45 min cargando ~28GB de pesos a VRAM.")

    try:
        endpoint = model.deploy(
            machine_type=MACHINE_TYPE,
            accelerator_type=ACCEL_TYPE,
            accelerator_count=ACCEL_COUNT,
            endpoint_display_name=ENDPOINT_DISPLAY,
            deploy_request_timeout=DEPLOY_TIMEOUT,
        )
    except gexc.ResourceExhausted as exc:
        log.error(f"  ❌ Cuota de {ACCEL_COUNT}x {ACCEL_TYPE} agotada en {DEPLOY_REGION}: {exc}")
        log.error("     Esto es cuota de SERVING, distinta a la de tuning.")
        log.error("     Revisa: IAM y administración > Cuotas > "
                   "'Custom model serving Nvidia L4 GPUs per region'.")
        raise

    log.info(f"  ✅ Desplegado. Endpoint: {endpoint.resource_name}")
    return endpoint, model


def step_test(endpoint) -> None:
    sep("VERIFICACIÓN · Predicción de prueba")
    try:
        resp = endpoint.predict(
            instances=[{
                "messages": [{"role": "user", "content": "¿Cómo reinicio un Deployment en Kubernetes sin downtime?"}],
                "max_tokens": 200,
            }]
        )
        log.info("  ✅ El endpoint respondió correctamente:")
        log.info(f"  {resp}")
    except Exception as e:
        log.warning(f"  ⚠️ La predicción de prueba falló (puede que vLLM aún esté arrancando): {e}")
        log.warning("  Espera 1-2 minutos y prueba con check_model_ready.py")


def main() -> None:
    sep("🚀 QWEN3-14B · FULL FINE-TUNING + DEPLOY · v6.0 DEFINITIVO")
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_PATH

    # Init inicial; se reinicializa por región dentro de cada paso.
    vertexai.init(project=PROJECT_ID, location=TUNING_REGIONS[0])

    step_upload_dataset()
    job, region_usada = step_launch_tuning()
    step_wait_for_tuning(job, region_usada)
    endpoint, model = step_deploy()
    step_test(endpoint)

    sep("🎉 TODO LISTO")
    log.info(f"  Tuning job   : {job.resource_name} (región: {region_usada})")
    log.info(f"  Endpoint     : {endpoint.resource_name} (región: {DEPLOY_REGION})")
    log.info(f"  Pesos en     : {OUTPUT_GCS_URI}postprocess/node-0/checkpoints/final")
    sep()


if __name__ == "__main__":
    main()
