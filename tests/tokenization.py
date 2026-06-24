#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════╗
║  FIX TOKENIZER · QWEN3-14B FULL FINE-TUNE · GCS UPLOAD  v2         ║
║  Genera special_tokens_map.json via AutoTokenizer y sube todo       ║
║  al bucket usando la librería Python de GCS (sin gsutil).           ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import os
import sys
import logging
import tempfile
from pathlib import Path
from datetime import datetime

try:
    from transformers import AutoTokenizer
except ImportError:
    sys.exit("ERROR: Ejecuta: pip install transformers")

try:
    from google.cloud import storage
except ImportError:
    sys.exit("ERROR: Ejecuta: pip install google-cloud-storage")

# ── Logging ──────────────────────────────────────────────────────────────────
TS       = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = f"fix_tokenizer_{TS}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("fix-tokenizer-v2")

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════

CREDENTIALS_PATH = r"C:\mis-proyectos\Tenzor\service_account.json"
BUCKET_NAME      = "tenzorai-tuning"
MODEL_PATH       = "output/tenz-1-nova"          # path dentro del bucket, sin / final
HF_REPO_ID       = "Qwen/Qwen3-14B"

# Archivos que debe generar AutoTokenizer al hacer save_pretrained
EXPECTED_FILES = [
    "special_tokens_map.json",   # ← el crítico, generado por save_pretrained
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
]

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def sep(title: str = "", width: int = 68) -> None:
    if title:
        pad = max(width - len(title) - 7, 2)
        log.info(f"{'─' * 4} {title} {'─' * pad}")
    else:
        log.info("─" * width)


def generate_tokenizer_files(local_dir: Path) -> list[str]:
    """
    Carga el tokenizer desde HuggingFace y lo guarda localmente.
    save_pretrained() genera TODOS los archivos del tokenizer,
    incluyendo special_tokens_map.json, aunque no exista en el repo HF.
    """
    sep("Generando archivos del tokenizer via AutoTokenizer")
    log.info(f"  Cargando tokenizer desde: {HF_REPO_ID}")
    log.info("  (puede tardar unos segundos en la primera descarga)")

    tokenizer = AutoTokenizer.from_pretrained(HF_REPO_ID, trust_remote_code=True)
    tokenizer.save_pretrained(str(local_dir))
    log.info(f"  ✅  Tokenizer guardado en: {local_dir}")

    generated = [f.name for f in local_dir.iterdir() if f.is_file()]
    log.info(f"  Archivos generados ({len(generated)}):")
    for f in sorted(generated):
        log.info(f"    📄  {f}")
    return generated


def upload_to_gcs(local_dir: Path, generated: list[str]) -> None:
    """Sube todos los archivos generados al bucket usando el cliente Python de GCS."""
    sep("Subiendo a GCS")
    log.info(f"  Autenticando con: {CREDENTIALS_PATH}")

    client = storage.Client.from_service_account_json(CREDENTIALS_PATH)
    bucket = client.bucket(BUCKET_NAME)

    for filename in sorted(generated):
        local_path = local_dir / filename
        blob_path  = f"{MODEL_PATH}/{filename}"
        blob       = bucket.blob(blob_path)

        log.info(f"  ⬆️   Subiendo: {filename}  →  gs://{BUCKET_NAME}/{blob_path}")
        blob.upload_from_filename(str(local_path))
        log.info(f"  ✅  OK: {filename}")


def verify(generated: list[str]) -> None:
    """Verifica que cada archivo existe en GCS y muestra su tamaño."""
    sep("Verificación final en GCS")
    client = storage.Client.from_service_account_json(CREDENTIALS_PATH)
    bucket = client.bucket(BUCKET_NAME)

    all_ok   = True
    critical = "special_tokens_map.json"

    for filename in sorted(generated):
        blob = bucket.blob(f"{MODEL_PATH}/{filename}")
        if blob.exists():
            blob.reload()
            size_kb = (blob.size or 0) / 1024
            log.info(f"  ✅  {filename:<35}  {size_kb:>8.1f} KB")
        else:
            log.error(f"  ❌  NO encontrado: {filename}")
            all_ok = False

    sep()
    if all_ok:
        # Comprobación específica del archivo crítico
        blob_crit = bucket.blob(f"{MODEL_PATH}/{critical}")
        if blob_crit.exists():
            log.info(f"  🎉  {critical} CONFIRMADO — listo para relanzar el deploy.")
        else:
            log.error(f"  ❌  {critical} NO está. Algo falló.")
            all_ok = False

    if not all_ok:
        log.error("  Revisa los errores anteriores antes de relanzar el deploy.")
        sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    sep("FIX TOKENIZER · QWEN3-14B v2 · inicio")
    log.info(f"  Destino GCS  : gs://{BUCKET_NAME}/{MODEL_PATH}/")
    log.info(f"  Repo HF      : {HF_REPO_ID}")
    log.info(f"  Credenciales : {CREDENTIALS_PATH}")
    log.info(f"  Log          : {LOG_FILE}")
    sep()

    if not os.path.exists(CREDENTIALS_PATH):
        log.error(f"  ❌  Credenciales no encontradas: {CREDENTIALS_PATH}")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        local_dir = Path(tmp)

        generated = generate_tokenizer_files(local_dir)

        if not generated:
            log.error("  ❌  No se generó ningún archivo. Revisa la conexión a HF.")
            sys.exit(1)

        upload_to_gcs(local_dir, generated)

    verify(generated)

    sep("PROCESO COMPLETADO")
    log.info("  Próximo paso: relanza redeploy_qwen14b_vertex_v4.1.py")
    sep()


if __name__ == "__main__":
    main()