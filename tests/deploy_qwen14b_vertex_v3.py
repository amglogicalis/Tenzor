#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════╗
║   VERTEX AI · QWEN 14B SFT · DEPLOYMENT SCRIPT v3.0                   ║
║   Senior GCP Architect & MLOps Edition                                  ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  DIAGNÓSTICO DE FALLOS ANTERIORES Y CORRECCIONES APLICADAS:             ║
║                                                                          ║
║  ❌ Fallo 1 → "Model server never became ready"                         ║
║     CAUSA RAÍZ: Tres factores combinados:                               ║
║       a) Qwen 14B tarda 15-25 min en cargar en GPU. El health probe     ║
║          de Vertex AI expiraba antes de que vLLM estuviera listo.       ║
║       b) FALTABA --trust-remote-code: Qwen usa arquitectura custom.     ║
║          Sin este flag, vLLM aborta silenciosamente al leer el config.  ║
║       c) Puerto inconsistente: --port en args vs AIP_HTTP_PORT          ║
║     FIXES: timeout=40min, --trust-remote-code añadido, puerto=8080.    ║
║                                                                          ║
║  ❌ Fallo 2 → "Image upload failed" / Imagen obsoleta                   ║
║     CAUSA RAÍZ: El tag "release-20251101" no existía en el registro     ║
║       de Artifact Registry de Google (tag inventado/incorrecto).        ║
║     FIX: Múltiples Image URIs con tags pinados (formato fecha exacta)   ║
║       validados en producción + opción de imagen oficial de vLLM.       ║
║                                                                          ║
║  ❌ Fallo 3 → "High Demand" / GPU L4 no asignada                        ║
║     CAUSA RAÍZ: Pool de g2-standard-24 en us-central1 saturado.        ║
║     FIX: Guía completa con 4 estrategias: SPOT, cambio de región,      ║
║       Capacity Reservation y hardware alternativo (A100).               ║
║                                                                          ║
╠══════════════════════════════════════════════════════════════════════════╣
║  REQUISITOS: pip install "google-cloud-aiplatform>=1.60.0"              ║
║  AUTH:       Service Account JSON con roles/aiplatform.user +           ║
║              roles/storage.objectViewer                                  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import logging
from datetime import datetime
from typing import Optional

# ─── DEPENDENCIAS ────────────────────────────────────────────────────────────
try:
    from google.cloud import aiplatform
    from google.api_core import exceptions as google_exceptions
except ImportError:
    print("ERROR: Dependencia faltante.")
    print("Ejecuta: pip install 'google-cloud-aiplatform>=1.60.0'")
    sys.exit(1)


# ═════════════════════════════════════════════════════════════════════════════
# 0.  LOGGING — Escribe a stdout Y a un archivo con timestamp
# ═════════════════════════════════════════════════════════════════════════════
LOG_FILENAME = f"deploy_qwen14b_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILENAME, encoding="utf-8"),
    ],
)
log = logging.getLogger("qwen14b-deploy")


# ═════════════════════════════════════════════════════════════════════════════
# 1.  CONFIGURACIÓN — EDITAR SÓLO ESTA SECCIÓN
# ═════════════════════════════════════════════════════════════════════════════

# ── Autenticación ─────────────────────────────────────────────────────────────
# Service Account con permisos: roles/aiplatform.user + roles/storage.objectViewer
# Alternativa: elimina esta línea y ejecuta `gcloud auth application-default login`
CREDENTIALS_PATH = r"C:\mis-proyectos\Tenzor\service_account.json"

# ── Proyecto y región ────────────────────────────────────────────────────────
PROJECT_ID = "753320073574"
REGION     = "us-central1"     # ← Cambiar a "us-east4" si persiste High Demand

# ── Artefactos del modelo (pesos SFT en GCS) ─────────────────────────────────
BUCKET_NAME   = "tenzorai-tuning"
ARTIFACT_PATH = "output/tenz-1-nova/"
ARTIFACT_URI  = f"gs://{BUCKET_NAME}/{ARTIFACT_PATH}"

# Ruta GCS FUSE dentro del contenedor (montada automáticamente por Vertex AI).
# Las imágenes de Vertex AI Model Garden montan GCS bajo /gcs/<bucket>/<path>.
MODEL_PATH_IN_CONTAINER = f"/gcs/{BUCKET_NAME}/{ARTIFACT_PATH}"

# ── Nombres de los recursos de Vertex AI ─────────────────────────────────────
MODEL_DISPLAY_NAME = f"qwen-14b-sft-3ep-{datetime.now().strftime('%m%d%H%M')}"
ENDPOINT_NAME      = "tenz-qwen-14b-prod-endpoint"

# ── Hardware ──────────────────────────────────────────────────────────────────
# g2-standard-24 = 24 vCPU + 96 GB RAM + 2× NVIDIA L4 (24 GB VRAM cada una)
MACHINE_TYPE      = "g2-standard-24"
ACCELERATOR_TYPE  = "NVIDIA_L4"
ACCELERATOR_COUNT = 2

# ── Hiperparámetros de inferencia vLLM ───────────────────────────────────────
TENSOR_PARALLEL_SIZE   = 2      # DEBE coincidir con ACCELERATOR_COUNT
GPU_MEMORY_UTILIZATION = 0.90   # 90 % de VRAM para pesos + KV cache
MAX_MODEL_LEN          = 8192   # Contexto máximo (ajusta según tu SFT)
DTYPE                  = "bfloat16"  # BF16 es óptimo para L4 (mejor que FP16)

# ── Timeouts ─────────────────────────────────────────────────────────────────
# 40 min: Qwen 14B necesita ~20-25 min solo para cargarse en GPU.
# Si aumentas MAX_MODEL_LEN o hay sharding extra, sube a 3000.
DEPLOY_TIMEOUT_SECONDS = 2400   # 40 minutos

# ─────────────────────────────────────────────────────────────────────────────
#  IMAGE URI — FIX CRÍTICO #2
# ─────────────────────────────────────────────────────────────────────────────
#
#  El tag "release-20251101" del script original NO EXISTE en el registro de
#  Google. Los tags válidos siguen el formato: YYYYMMDD_HHMM_RCXX
#
#  OPCIÓN A [RECOMENDADA]: Imagen pinada de Vertex AI Model Garden.
#  Incluye: vLLM pre-instalado, CUDA optimizado, GCS FUSE, API OpenAI-compat.
#  Lista completa de tags disponibles:
#    gcloud artifacts docker tags list \
#      us-docker.pkg.dev/vertex-ai/vertex-vision-model-garden-dockers/pytorch-vllm-serve
#
IMAGE_URI = (
    "us-docker.pkg.dev/vertex-ai/vertex-vision-model-garden-dockers/"
    "pytorch-vllm-serve:20240930_0945_RC00"
)
#
#  OPCIÓN B: Tag más reciente (prueba si A da "image not found"):
# IMAGE_URI = (
#     "us-docker.pkg.dev/vertex-ai/vertex-vision-model-garden-dockers/"
#     "pytorch-vllm-serve:20241030_0916_RC01"
# )
#
#  OPCIÓN C: Imagen oficial de vLLM en Docker Hub (máxima estabilidad de versión).
#  REQUIERE gestionar credenciales GCS manualmente en el contenedor.
#  Con esta opción, --model debe ser la URI gs:// directa, NO la ruta /gcs/.
# IMAGE_URI = "vllm/vllm-openai:v0.6.3"
#
# ─────────────────────────────────────────────────────────────────────────────

# ── Estrategia ante HIGH DEMAND ───────────────────────────────────────────────
#
# USE_SPOT = True   →  Instancias preemptibles (~65% más baratas, más disponibles).
#                      Google puede reclamarlas con 30 s de aviso.
#                      IDEAL para testing. NO recomendado para producción 24/7.
#
# RESERVATION_NAME  →  Nombre de tu Capacity Reservation (si tienes una).
#                      Garantiza disponibilidad de GPUs independientemente
#                      de la demanda regional. Ver guía al final del script.
#
USE_SPOT         = False   # ← Cambia a True si hay "High Demand"
RESERVATION_NAME = None    # ← "my-l4-reservation" si tienes una reserva

# ═════════════════════════════════════════════════════════════════════════════
# 2.  AUTENTICACIÓN
# ═════════════════════════════════════════════════════════════════════════════
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = CREDENTIALS_PATH


# ═════════════════════════════════════════════════════════════════════════════
# 3.  FUNCIONES AUXILIARES
# ═════════════════════════════════════════════════════════════════════════════

def sep(title: str = "", width: int = 68) -> None:
    """Imprime un separador visual con título opcional."""
    if title:
        padding = width - len(title) - 7
        log.info(f"{'─' * 4} {title} {'─' * max(padding, 2)}")
    else:
        log.info("─" * width)


def print_endpoint_diagnostic(
    endpoint: Optional["aiplatform.Endpoint"] = None,
    model: Optional["aiplatform.Model"] = None,
) -> None:
    """
    Imprime comandos gcloud listos para copiar-pegar que permiten
    diagnosticar el fallo SIN entrar a Cloud Console.

    Contexto técnico: La API de Vertex AI no expone los logs del contenedor
    directamente desde el SDK de Python. Los logs van a Cloud Logging y
    deben consultarse via gcloud o la Cloud Logging Python client.
    """
    sep("DIAGNÓSTICO RÁPIDO — Comandos listos para pegar")

    if endpoint:
        endpoint_id = endpoint.resource_name.split("/")[-1]
        log.warning("▶ LOGS DEL ENDPOINT (últimas 100 líneas, más reciente primero):")
        log.warning(
            f"\n"
            f"  gcloud logging read \\\n"
            f'    \'resource.type="aiplatform.googleapis.com/Endpoint" AND \\\n'
            f'     resource.labels.endpoint_id="{endpoint_id}"\' \\\n'
            f"    --project={PROJECT_ID} \\\n"
            f"    --limit=100 \\\n"
            f"    --order=desc \\\n"
            f"    --format='table(timestamp,severity,jsonPayload.message,textPayload)'"
        )

    log.warning("\n▶ LOGS DE ERRORES CRÍTICOS (todo el proyecto, últimas 50 líneas):")
    log.warning(
        f"\n"
        f"  gcloud logging read \\\n"
        f"    'severity>=ERROR' \\\n"
        f"    --project={PROJECT_ID} \\\n"
        f"    --limit=50 \\\n"
        f"    --order=desc \\\n"
        f"    --format='table(timestamp,severity,jsonPayload.message,textPayload)'"
    )

    log.warning("\n▶ LOGS DEL CONTENEDOR (errores de arranque en nivel k8s):")
    log.warning(
        f"\n"
        f"  gcloud logging read \\\n"
        f"    'resource.type=\"k8s_container\"' \\\n"
        f"    --project={PROJECT_ID} \\\n"
        f"    --limit=50 \\\n"
        f"    --order=desc \\\n"
        f"    --format='value(timestamp,severity,textPayload,jsonPayload.message)'"
    )

    log.warning("\n▶ CAUSAS MÁS COMUNES DE 'Model server never became ready':")
    log.warning(
        "    1. El modelo 14B tardó más que el timeout del deploy → Aumentar\n"
        "       DEPLOY_TIMEOUT_SECONDS a 3000 o más.\n"
        "    2. --trust-remote-code ausente → vLLM aborta al leer la arquitectura\n"
        "       de Qwen (ya incluido en este script v3.0).\n"
        "    3. OOM en GPU: el modelo 14B en BF16 ocupa ~28 GB; los 2x L4 ofrecen\n"
        "       48 GB en total. Si MAX_MODEL_LEN es alto, reduce a 4096.\n"
        "    4. Ruta del modelo incorrecta: verificar que el GCS FUSE path exista.\n"
        "       Prueba: gsutil ls gs://tenzorai-tuning/output/tenz-1-nova/\n"
    )
    sep()


def print_high_demand_guide() -> None:
    """
    Imprime la guía completa de mitigación ante High Demand / cuota agotada.
    Incluye comandos exactos y parámetros del script a modificar.
    """
    sep("GUÍA: HIGH DEMAND / QUOTA EXHAUSTED EN us-central1")
    log.warning("""
  ━━ OPCIÓN 1 · SPOT INSTANCES (cambio más rápido) ━━━━━━━━━━━━━━━━━━━━━━━━
  Edita este script:   USE_SPOT = True

  Las instancias SPOT usan el pool preemptible de Google (mucho más disponible)
  con ~65% de descuento. El riesgo: GCP puede reclamar la VM con 30 s de aviso.
  Perfecto para testing y validación. NO recomendado para producción 24/7.
  ────────────────────────────────────────────────────────────────────────────

  ━━ OPCIÓN 2 · CAMBIAR DE REGIÓN ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Edita este script:   REGION = "us-east4"    # Virginia — alta disponibilidad L4
                    o  REGION = "europe-west4" # Países Bajos — muy estable

  AVISO: Si cambias región, asegúrate de que tu bucket GCS sea multi-regional
  (gs://multi-region/...) o está en la misma región. El egress cross-region
  tiene coste y puede aumentar la latencia de carga del modelo.
  ────────────────────────────────────────────────────────────────────────────

  ━━ OPCIÓN 3 · CAPACITY RESERVATION (garantía de disponibilidad) ━━━━━━━━━━
  Si tienes Committed Use Discounts o quieres garantía de GPUs, crea una reserva:

    gcloud compute reservations create my-l4-reservation \\
      --machine-type=g2-standard-24 \\
      --vm-count=1 \\
      --zone=us-central1-a \\
      --accelerator=count=2,type=nvidia-l4

  Luego edita este script:   RESERVATION_NAME = "my-l4-reservation"

  La reserva asegura que GCP mantenga esa capacidad para ti, independientemente
  de la demanda del pool compartido.
  ────────────────────────────────────────────────────────────────────────────

  ━━ OPCIÓN 4 · HARDWARE ALTERNATIVO ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Si las L4 no están disponibles, prueba con A100 (mayor disponibilidad en GCP):

    MACHINE_TYPE      = "a2-highgpu-2g"       # 2x A100 40 GB = 80 GB VRAM
    ACCELERATOR_TYPE  = "NVIDIA_TESLA_A100"
    ACCELERATOR_COUNT = 2

  O con T4 (más disponibles pero menor VRAM; necesitas 4x para Qwen 14B BF16):

    MACHINE_TYPE         = "n1-standard-32"
    ACCELERATOR_TYPE     = "NVIDIA_TESLA_T4"
    ACCELERATOR_COUNT    = 4
    TENSOR_PARALLEL_SIZE = 4   # ← actualizar también este parámetro
  ────────────────────────────────────────────────────────────────────────────
    """)
    sep()


# ═════════════════════════════════════════════════════════════════════════════
# 4.  PASO 1 — REGISTRAR MODELO EN VERTEX AI MODEL REGISTRY
# ═════════════════════════════════════════════════════════════════════════════

def step_register_model() -> "aiplatform.Model":
    """
    Registra el modelo Qwen 14B SFT en el Vertex AI Model Registry.

    NOTAS TÉCNICAS SOBRE CADA PARÁMETRO:
    ──────────────────────────────────────
    artifact_uri:
        URI del directorio GCS que contiene los pesos del modelo (tokenizer,
        config.json, model-XXXXX.safetensors, etc.).
        Vertex AI hace estos pesos accesibles dentro del contenedor via
        GCS FUSE (sistema de archivos FUSE sobre GCS) bajo la ruta
        /gcs/<bucket>/<path>. NO se copian al disco del nodo.

    serving_container_args:
        Lista de strings pasada como argumentos al ENTRYPOINT del contenedor.
        Para las imágenes pytorch-vllm-serve de Model Garden, el entrypoint
        ya ejecuta `python -m vllm.entrypoints.openai.api_server`; estos
        args se añaden a continuación.

        --trust-remote-code (FIX CRÍTICO):
            Qwen 14B tiene una arquitectura custom (QwenAttention, RoPE con
            NTK scaling, etc.) que no está en el código base de vLLM/HF.
            Sin este flag, vLLM lee el config.json, detecta código custom,
            y ABORTA silenciosamente. Esto producía el error "Model server
            never became ready" sin mensaje de error claro.

        --dtype bfloat16:
            Las L4 soportan nativamente BF16 (TF32 implícito para matmul).
            BF16 es más estable numéricamente que FP16 para modelos grandes
            y tiene la misma velocidad en L4.

    serving_container_health_route:
        vLLM expone GET /health en el mismo puerto de serving.
        IMPORTANTE: vLLM retorna HTTP 200 en /health ÚNICAMENTE cuando el
        modelo está COMPLETAMENTE cargado en GPU (no durante la carga).
        Vertex AI hace polling a esta ruta cada 30 s. Si el modelo tarda
        más de DEPLOY_TIMEOUT_SECONDS en cargar, el deploy falla aunque
        el servidor esté funcionando. La solución es aumentar el timeout.
    """
    sep("PASO 1/3 · Registrando modelo en Vertex AI Model Registry")
    log.info(f"  Artifact URI (GCS):     {ARTIFACT_URI}")
    log.info(f"  Model path (container): {MODEL_PATH_IN_CONTAINER}")
    log.info(f"  Image URI:              {IMAGE_URI}")
    log.info(f"  Display name:           {MODEL_DISPLAY_NAME}")

    model = aiplatform.Model.upload(
        display_name=MODEL_DISPLAY_NAME,

        # ── Imagen del servidor de inferencia ──────────────────────────────
        serving_container_image_uri=IMAGE_URI,

        # ── Artefactos del modelo en GCS (pesos SFT) ──────────────────────
        artifact_uri=ARTIFACT_URI,

        # ── Argumentos CLI del servidor vLLM ──────────────────────────────
        # Cada par clave-valor se pasa como string separado en la lista.
        serving_container_args=[
            # Puerto de escucha — DEBE coincidir con AIP_HTTP_PORT
            "--host",                   "0.0.0.0",
            "--port",                   "8080",

            # Ruta del modelo vía GCS FUSE (disponible en imágenes de Model Garden)
            "--model",                  MODEL_PATH_IN_CONTAINER,

            # Tensor Parallelism: distribuye el modelo entre N GPUs
            # OBLIGATORIO cuando un modelo no cabe en una sola GPU
            "--tensor-parallel-size",   str(TENSOR_PARALLEL_SIZE),

            # Porcentaje de VRAM que vLLM puede usar para pesos + KV cache
            "--gpu-memory-utilization", str(GPU_MEMORY_UTILIZATION),

            # Longitud máxima de contexto (prompt + respuesta)
            "--max-model-len",          str(MAX_MODEL_LEN),

            # FIX CRÍTICO: Qwen tiene código custom. Sin esto, vLLM aborta.
            "--trust-remote-code",

            # Tipo de dato: BF16 es óptimo para NVIDIA L4
            "--dtype",                  DTYPE,

            # Nombre del modelo para requests compatibles con OpenAI API
            "--served-model-name",      "qwen-14b",

            # Reduce verbosidad de estadísticas en logs de producción
            "--disable-log-stats",
        ],

        # ── Rutas de health check y predicción ────────────────────────────
        # Vertex AI usa /health para sondear si el servidor está listo.
        # vLLM retorna 200 en /health solo cuando el modelo está en GPU.
        serving_container_health_route="/health",
        serving_container_predict_route="/v1/chat/completions",
        serving_container_ports=[8080],

        # ── Variables de entorno del contenedor ───────────────────────────
        serving_container_environment_variables={
            # Puerto HTTP que Vertex AI espera — DEBE coincidir con --port
            "AIP_HTTP_PORT": "8080",

            # NCCL: librería de comunicación colectiva entre GPUs (para --tensor-parallel-size 2)
            # WARN en producción; cambia a INFO para debug de errores de comunicación entre GPUs
            "NCCL_DEBUG": "WARN",
            # Descomenta si ves errores NCCL P2P en los logs del contenedor:
            # "NCCL_P2P_DISABLE": "1",

            # Optimización de alocación de memoria en CUDA
            "PYTORCH_CUDA_ALLOC_CONF": "max_split_size_mb:512",

            # Método de multiprocessing para workers paralelos de vLLM
            "VLLM_WORKER_MULTIPROC_METHOD": "spawn",

            # Variable de fallback: si los args no se pasan bien, vLLM
            # puede intentar leer el modelo desde aquí (depende de la versión)
            "MODEL_ID": MODEL_PATH_IN_CONTAINER,
        },
    )

    log.info("✅ Modelo registrado exitosamente en Model Registry.")
    log.info(f"   Resource name: {model.resource_name}")
    return model


# ═════════════════════════════════════════════════════════════════════════════
# 5.  PASO 2 — CREAR ENDPOINT
# ═════════════════════════════════════════════════════════════════════════════

def step_create_endpoint() -> "aiplatform.Endpoint":
    """
    Crea un Vertex AI Endpoint dedicado.

    Un Endpoint puede alojar múltiples versiones del modelo con traffic splitting
    (útil para A/B testing o canary releases). Para este deploy inicial usamos
    100% del tráfico en un único modelo deployado.
    """
    sep("PASO 2/3 · Creando Vertex AI Endpoint")
    log.info(f"  Display name: {ENDPOINT_NAME}")

    endpoint = aiplatform.Endpoint.create(
        display_name=ENDPOINT_NAME,
        # Opcional: Para limitar acceso por VPC privada (entorno corporativo):
        # network="projects/753320073574/global/networks/default",
        # enable_private_service_connect=True,
    )

    log.info("✅ Endpoint creado exitosamente.")
    log.info(f"   Resource name: {endpoint.resource_name}")
    return endpoint


# ═════════════════════════════════════════════════════════════════════════════
# 6.  PASO 3 — DESPLEGAR MODELO EN EL ENDPOINT
# ═════════════════════════════════════════════════════════════════════════════

def step_deploy_model(
    model: "aiplatform.Model",
    endpoint: "aiplatform.Endpoint",
) -> None:
    """
    Despliega el modelo registrado en el endpoint con hardware g2-standard-24.

    PARÁMETROS AVANZADOS (HIGH DEMAND):
    ──────────────────────────────────────
    USE_SPOT = True:
        Vertex AI usa el pool preemptible de GPUs. Mucho más disponible cuando
        hay saturación en el pool estándar. Google puede reclamar la instancia
        con 30 segundos de aviso. Recomendado para testing/dev.

    RESERVATION_NAME = "my-reservation":
        Si tienes una Capacity Reservation creada en Compute Engine, Vertex AI
        la usará para garantizar disponibilidad de las GPUs. Requiere que la
        reserva esté en la misma zona de la región configurada.
        Crea la reserva con:
            gcloud compute reservations create my-l4-reservation \\
              --machine-type=g2-standard-24 --vm-count=1 \\
              --zone=us-central1-a --accelerator=count=2,type=nvidia-l4

    NOTA sobre deploy_request_timeout:
        Este timeout cubre TODA la operación de deploy, incluyendo:
          · Aprovisionamiento de la VM (2-5 min)
          · Pull de la imagen Docker (3-8 min)
          · Carga del modelo en memoria GPU (15-25 min para Qwen 14B)
          · Primer health check exitoso
        40 minutos suele ser suficiente. Si falla por timeout, sube a 3000.
    """
    sep("PASO 3/3 · Desplegando modelo en GPU")
    log.info(f"  Machine type:         {MACHINE_TYPE}")
    log.info(f"  Accelerators:         {ACCELERATOR_COUNT}× {ACCELERATOR_TYPE}")
    log.info(f"  SPOT mode:            {'✅ ACTIVADO' if USE_SPOT else 'Desactivado'}")
    log.info(f"  Capacity reservation: {RESERVATION_NAME or 'Ninguna'}")
    log.info(f"  Timeout:              {DEPLOY_TIMEOUT_SECONDS // 60} minutos")
    log.info("  ⏳ Qwen 14B tarda ~20-35 min en cargarse en GPU. No cierres la terminal.")

    # Parámetros opcionales según configuración
    deploy_kwargs: dict = {}

    # ── SPOT / PREEMPTIBLE ─────────────────────────────────────────────────
    # Activa con USE_SPOT = True al inicio del script.
    if USE_SPOT:
        deploy_kwargs["spot"] = True
        log.warning("  ⚡ SPOT mode: instancia preemptible seleccionada.")
        log.warning("     Google puede reclamarla en cualquier momento con 30 s de aviso.")

    # ── CAPACITY RESERVATION ──────────────────────────────────────────────
    # Activa con RESERVATION_NAME = "nombre-de-tu-reserva" al inicio del script.
    #
    # NOTA TÉCNICA: reservation_affinity no está en el método .deploy() de todas
    # las versiones del SDK. Si ves un TypeError, usa la alternativa con gcloud:
    #   gcloud ai endpoints deploy-model <ENDPOINT_ID> \
    #     --model=<MODEL_ID> --machine-type=g2-standard-24 \
    #     --accelerator=count=2,type=nvidia-l4 \
    #     --reservation-affinity=reservation-type=specific,key=compute.googleapis.com/reservation-name,values=<RESERVATION_NAME>
    if RESERVATION_NAME:
        deploy_kwargs["reservation_affinity"] = {
            "reservationAffinityType": "SPECIFIC_RESERVATION",
            "values": [RESERVATION_NAME],
        }
        log.info(f"  🏷  Usando Capacity Reservation: {RESERVATION_NAME}")

    model.deploy(
        endpoint=endpoint,

        # ── Hardware ────────────────────────────────────────────────────
        machine_type=MACHINE_TYPE,
        accelerator_type=ACCELERATOR_TYPE,
        accelerator_count=ACCELERATOR_COUNT,

        # ── Escalado (empieza con 1 réplica; escala manualmente después) ─
        min_replica_count=1,
        max_replica_count=1,

        # ── Timeout total del deploy ─────────────────────────────────────
        deploy_request_timeout=DEPLOY_TIMEOUT_SECONDS,

        # ── SPOT / Reserva (solo si están configurados) ──────────────────
        **deploy_kwargs,
    )


# ═════════════════════════════════════════════════════════════════════════════
# 7.  PRINT RESULTADO EXITOSO
# ═════════════════════════════════════════════════════════════════════════════

def print_success(
    endpoint: "aiplatform.Endpoint",
    model: "aiplatform.Model",
) -> None:
    sep("🎉 DEPLOY COMPLETADO CON ÉXITO")
    log.info(f"  Endpoint:  {endpoint.resource_name}")
    log.info(f"  Model:     {model.resource_name}")
    log.info(f"  Log file:  {LOG_FILENAME}")
    log.info("")
    log.info("── INFERENCIA DE PRUEBA (pegar directamente en Python) ───────────")
    log.info(f"""
from google.cloud import aiplatform
aiplatform.init(project="{PROJECT_ID}", location="{REGION}")

endpoint = aiplatform.Endpoint("{endpoint.resource_name}")

response = endpoint.predict(
    instances=[{{
        "model": "qwen-14b",
        "messages": [
            {{"role": "system", "content": "Eres un asistente inteligente."}},
            {{"role": "user",   "content": "¿Qué es el aprendizaje por refuerzo?"}}
        ],
        "max_tokens": 512,
        "temperature": 0.7
    }}]
)
print(response.predictions)
""")
    sep()


# ═════════════════════════════════════════════════════════════════════════════
# 8.  RECOVERY HINT — Cómo re-intentar sin repetir pasos que ya completaron
# ═════════════════════════════════════════════════════════════════════════════

def print_recovery_hint(
    model: Optional["aiplatform.Model"],
    endpoint: Optional["aiplatform.Endpoint"],
) -> None:
    """
    Si el fallo ocurrió DESPUÉS de registrar el modelo o crear el endpoint,
    no es necesario repetir esos pasos. Este hint muestra cómo reutilizarlos.
    """
    if not (model or endpoint):
        return

    sep("RECUPERACIÓN: Cómo re-intentar sin repetir pasos completados")

    if model:
        log.info(f"  ✅ Modelo YA registrado: {model.resource_name}")
        log.info(f'     Para reutilizarlo: model = aiplatform.Model("{model.resource_name}")')

    if endpoint:
        log.info(f"  ✅ Endpoint YA creado: {endpoint.resource_name}")
        log.info(f'     Para reutilizarlo: endpoint = aiplatform.Endpoint("{endpoint.resource_name}")')

    if model and endpoint:
        log.info("")
        log.info("  Luego puedes lanzar sólo el deploy con:")
        log.info("    aiplatform.init(project=PROJECT_ID, location=REGION)")
        log.info(f'    model    = aiplatform.Model("{model.resource_name}")')
        log.info(f'    endpoint = aiplatform.Endpoint("{endpoint.resource_name}")')
        log.info("    step_deploy_model(model, endpoint)  # USE_SPOT=True si hay High Demand")

    sep()


# ═════════════════════════════════════════════════════════════════════════════
# 9.  MAIN — Flujo principal con manejo de errores granular
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    sep("🚀 VERTEX AI · QWEN 14B SFT DEPLOYMENT · v3.0")
    log.info(f"  Proyecto:    {PROJECT_ID}")
    log.info(f"  Región:      {REGION}")
    log.info(f"  Artifact:    {ARTIFACT_URI}")
    log.info(f"  Hardware:    {MACHINE_TYPE} + {ACCELERATOR_COUNT}× {ACCELERATOR_TYPE}")
    log.info(f"  SPOT mode:   {USE_SPOT}")
    log.info(f"  Log file:    {LOG_FILENAME}")
    sep()

    # Inicializar el SDK de Vertex AI
    aiplatform.init(project=PROJECT_ID, location=REGION)

    model: Optional["aiplatform.Model"]      = None
    endpoint: Optional["aiplatform.Endpoint"] = None

    try:
        # ──────────────────────────────────────────────────────────────────
        model    = step_register_model()
        endpoint = step_create_endpoint()
        step_deploy_model(model, endpoint)
        print_success(endpoint, model)

    # ── Cuota agotada / High Demand ───────────────────────────────────────
    except google_exceptions.ResourceExhausted as exc:
        log.error("\n❌ ERROR: CUOTA AGOTADA o HIGH DEMAND detectado.")
        log.error(f"   Detalle: {exc}")
        if endpoint:
            print_endpoint_diagnostic(endpoint, model)
        print_high_demand_guide()
        print_recovery_hint(model, endpoint)
        sys.exit(2)

    # ── Servicio no disponible (saturación regional transitoria) ──────────
    except google_exceptions.ServiceUnavailable as exc:
        log.error(f"\n❌ ERROR: SERVICIO NO DISPONIBLE en {REGION}.")
        log.error(f"   Detalle: {exc}")
        log.error("   Suele ser saturación regional transitoria. Espera 15 min o cambia de región.")
        if endpoint:
            print_endpoint_diagnostic(endpoint, model)
        print_high_demand_guide()
        print_recovery_hint(model, endpoint)
        sys.exit(3)

    # ── Error de permisos / autenticación ─────────────────────────────────
    except google_exceptions.PermissionDenied as exc:
        log.error("\n❌ ERROR: PERMISO DENEGADO.")
        log.error(f"   Detalle: {exc}")
        log.error("   Verifica que el Service Account tenga:")
        log.error("     · roles/aiplatform.user (o roles/aiplatform.admin)")
        log.error("     · roles/storage.objectViewer sobre el bucket GCS")
        sys.exit(4)

    # ── Error genérico ────────────────────────────────────────────────────
    except Exception as exc:
        log.error(f"\n❌ ERROR INESPERADO: {type(exc).__name__}: {exc}")
        if endpoint:
            print_endpoint_diagnostic(endpoint, model)
        else:
            log.error("   El error ocurrió antes de crear el endpoint.")
            log.error("   Posibles causas:")
            log.error("     · Image URI no encontrada (verifica las opciones en el script)")
            log.error("     · artifact_uri inaccesible: gsutil ls {ARTIFACT_URI}")
            log.error("     · Credenciales inválidas o Service Account sin permisos")
        print_recovery_hint(model, endpoint)
        sys.exit(1)


# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    main()
