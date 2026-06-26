#!/usr/bin/env python3
"""
monitor_endpoint_deploy.py
Monitoriza de forma óptima el estado del deploy de Vertex AI.
Corregido con filtros nativos 'done=false' para capturar operaciones ocultas.
"""

import sys
import time
import argparse
import datetime
import json
import urllib.request
import urllib.error
import os

try:
    from google.oauth2 import service_account
    import google.auth.transport.requests as google_requests
except ImportError:
    print("\n[ERROR] Falta google-auth. Instálalo con: pip install google-auth\n")
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════
PROJECT_ID   = "tenzorai"
LOCATION     = "us-central1"
ENDPOINT_ID  = "mg-endpoint-1eae4fb8-4883-4bfc-8355-08cdb1ee1bb9"

SERVICE_ACCOUNT_JSON = r"C:\mis-proyectos\Tenzor\service_account.json"
DEFAULT_INTERVAL = 15

_CACHED_CREDS = None

# ══════════════════════════════════════════════════════════════════════════════
#  COLORES ANSI
# ══════════════════════════════════════════════════════════════════════════════
USE_COLOR = sys.stdout.isatty()

def c(code: str, text: str) -> str:
    if not USE_COLOR:
        return text
    codes = {
        "reset":  "\033[0m", "bold":   "\033[1m", "dim":    "\033[2m",
        "green":  "\033[92m", "yellow": "\033[93m", "red":    "\033[91m",
        "cyan":   "\033[96m", "blue":   "\033[94m", "gray":   "\033[90m"
    }
    return f"{codes.get(code, '')}{text}{codes['reset']}"

# ══════════════════════════════════════════════════════════════════════════════
#  ESTRUCTURAS DE DATOS
# ══════════════════════════════════════════════════════════════════════════════
class DeployedModelInfo:
    def __init__(self, d: dict):
        self.id         = d.get("id", "—")
        self.model      = d.get("model", "—")
        self.display_name = d.get("displayName", "—")
        self.version_id = d.get("modelVersionId", "")
        self.create_time = d.get("createTime", "—")
        dr = d.get("dedicatedResources", {})
        self.min_replicas = int(dr.get("minReplicaCount", 0)) if dr else 0
        self.max_replicas = int(dr.get("maxReplicaCount", 0)) if dr else 0
        self.machine_type = dr.get("machineSpec", {}).get("machineType", "—") if dr else "—"

class EndpointInfo:
    def __init__(self, d: dict):
        self.traffic_split = {k: int(v) for k, v in d.get("trafficSplit", {}).items()}

# ══════════════════════════════════════════════════════════════════════════════
#  API FETCH
# ══════════════════════════════════════════════════════════════════════════════
def _get_cached_token():
    global _CACHED_CREDS
    if _CACHED_CREDS is None:
        if SERVICE_ACCOUNT_JSON and os.path.isfile(SERVICE_ACCOUNT_JSON):
            _CACHED_CREDS = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_JSON, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        else:
            import google.auth
            _CACHED_CREDS, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not _CACHED_CREDS.valid:
        _CACHED_CREDS.refresh(google_requests.Request())
    return _CACHED_CREDS.token, None

def fetch_vertex_state():
    token, err = _get_cached_token()
    if err: return None, [], [], f"Fallo de credenciales: {err}", None

    base_url = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}"
    
    # 1. Consultar Endpoint
    ep, models = None, []
    try:
        req = urllib.request.Request(f"{base_url}/endpoints/{ENDPOINT_ID}", headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
            ep = EndpointInfo(raw)
            deployed_list = raw.get("deployedModels", [])
            deployed_list.sort(key=lambda x: x.get("createTime", ""), reverse=True)
            models = [DeployedModelInfo(m) for m in deployed_list]
    except urllib.error.HTTPError as e:
        return None, [], [], f"HTTP {e.code} en Endpoint: {e.read().decode(errors='replace')[:150]}", None
    except Exception as exc:
        return None, [], [], f"Error de red en Endpoint: {exc}", None

    # 2. Consultar Operaciones ACTIVAS con filtro nativo en Google Cloud
    active_ops = []
    op_err_msg = None
    try:
        # Filtro 'done=false' para que Google solo devuelva lo que se está ejecutando AHORA
        url_ops = f"{base_url}/operations?filter=done%3Dfalse&pageSize=50"
        req_ops = urllib.request.Request(url_ops, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req_ops, timeout=10) as resp:
            raw_ops = json.loads(resp.read().decode("utf-8"))
            for op in raw_ops.get("operations", []):
                if ENDPOINT_ID in json.dumps(op.get("metadata", {})) or ENDPOINT_ID in op.get("name", ""):
                    active_ops.append(op)
    except urllib.error.HTTPError as e:
        op_err_msg = f"HTTP {e.code} al filtrar operaciones activas."
    except Exception as exc:
        op_err_msg = f"Error al buscar operaciones vivas: {exc}"

    return ep, models, active_ops, None, op_err_msg

# ══════════════════════════════════════════════════════════════════════════════
#  RENDER E INTERFAZ DE USUARIO
# ══════════════════════════════════════════════════════════════════════════════
def progress_bar(current: int, total: int) -> str:
    filled = int(30 * current / total)
    return f"[{'█' * filled}{'░' * (30 - filled)}] {int(100 * current / total):3d}%"

def run_monitor(interval: int, once: bool) -> None:
    start_time = time.time()
    attempts = 0
    
    while True:
        attempts += 1
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not once and attempts > 1: print("\033[2J\033[H", end="")

        print(c("cyan", "═" * 62))
        print(c("bold", f"  Vertex AI Real-Time Monitor  ·  {ts}"))
        print(c("cyan", "═" * 62))

        ep, models, active_ops, err, op_err = fetch_vertex_state()

        if err:
            print(c("red", f"  [ERROR CRÍTICO] {err}\n"))
        else:
            # DETERMINACIÓN INTELIGENTE DE LA FASE REAL
            if ep and len(models) > 0 and not active_ops:
                # Caso ideal: El modelo ya está y no hay nada ejecutándose
                phase = "ESTABLE / LISTO"
                pct_idx = 4
            else:
                # Si no hay modelos creados aún, forzosamente está aprovisionando la nube
                phase = "PROCESANDO DEPLOY (Aprovisionando Máquinas y Red)"
                pct_idx = 2

            # Renderizado coherente y limpio de fases
            print(f"  {c('green','✔')} Fase 1/4: Endpoint activo y accesible")
            print(f"  {(c('yellow','▶') if pct_idx == 2 else c('green','✔'))} Fase 2/4: {phase}")
            print(f"  {(c('green','✔') if pct_idx >= 4 else c('dim','○'))} Fase 3/4: Réplicas levantadas y estables")
            print(f"  {(c('green','✔') if pct_idx >= 4 else c('dim','○'))} Fase 4/4: Tráfico enrutado al modelo nuevo")
            
            print(f"\n  Progreso Real: {c('cyan', progress_bar(pct_idx, 4))}\n")

            # Cronómetro activo durante el deploy
            if pct_idx == 2:
                elapsed = int(time.time() - start_time)
                mins, secs = divmod(elapsed, 60)
                print(c("yellow", f"  ⏳ TRABAJANDO EN LA NUBE:"))
                print(f"     Google Cloud está descargando tu imagen Docker y asignando hardware.")
                print(f"     Tiempo transcurrido en esta sesión: {c('bold', f'{mins}m {secs}s')}")
                print(c("gray", "     (Nota: Vertex AI suele tardar entre 10 y 20 minutos en finalizar)"))
                print()

            # Estado de los modelos conectados
            if models:
                print(c("bold", "  MODELOS CONECTADOS AL ENDPOINT:"))
                for dm in models:
                    traffic = ep.traffic_split.get(dm.id, 0)
                    print(f"    • {c('green', dm.display_name)} [v{dm.version_id}] -> Tráfico: {c('bold', f'{traffic}%')}")
                    print(f"      ID interno: {dm.id} | Máquina: {dm.machine_type} (Mín: {dm.min_replicas})")
                print()
            else:
                print(c("gray", "  ℹ Info: Esperando a que el primer nodo del contenedor responda para listar el modelo.\n"))

            print(c("cyan", "─" * 62))
            print(f"  Estado Global: {c('yellow' if pct_idx == 2 else 'green', phase)}")
            print(c("cyan", "═" * 62))

        if once: break
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print(c("cyan", "\n\n  Monitor detenido.\n"))
            sys.exit(0)

def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor optimizado Vertex AI con soporte LRO.")
    parser.add_argument("--interval", "-i", type=int, default=DEFAULT_INTERVAL)
    parser.add_argument("--once", "-1", action="store_true")
    args = parser.parse_args()
    run_monitor(interval=args.interval, once=args.once)

if __name__ == "__main__":
    main()