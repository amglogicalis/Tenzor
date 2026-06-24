#!/usr/bin/env python3
"""
monitor_endpoint_deploy.py
Monitoriza el estado del deploy de un modelo en un endpoint de Vertex AI.
Muestra fases, barra de progreso y diagnostica errores si los hay.

Uso:
    python monitor_endpoint_deploy.py
    python monitor_endpoint_deploy.py --interval 15   # polling cada 15s
    python monitor_endpoint_deploy.py --once           # snapshot único, sin loop
"""

import sys
import time
import argparse
import datetime
import json
import urllib.request
import urllib.error
import os

# ── Dependencia: google-auth (mucho más ligera que google-cloud-aiplatform) ──
try:
    from google.oauth2 import service_account
    import google.auth.transport.requests as google_requests
except ImportError:
    print(
        "\n[ERROR] Falta google-auth.\n"
        "Instálalo con:\n"
        "    pip install google-auth\n"
    )
    sys.exit(1)

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN
# ══════════════════════════════════════════════════════════════════════════════
PROJECT_ID   = "tenzorai"
LOCATION     = "us-central1"
ENDPOINT_ID  = "mg-endpoint-1eae4fb8-4883-4bfc-8355-08cdb1ee1bb9"

# Ruta al fichero de credenciales de la cuenta de servicio (.json)
# Pon None para usar Application Default Credentials (gcloud auth login)
SERVICE_ACCOUNT_JSON = r"C:\mis-proyectos\Tenzor\service_account.json"

# Tiempo entre polls (segundos). Sobreescribible con --interval
DEFAULT_INTERVAL = 20

# ══════════════════════════════════════════════════════════════════════════════
#  COLORES ANSI
# ══════════════════════════════════════════════════════════════════════════════
USE_COLOR = sys.stdout.isatty()

def c(code: str, text: str) -> str:
    if not USE_COLOR:
        return text
    codes = {
        "reset":  "\033[0m",
        "bold":   "\033[1m",
        "dim":    "\033[2m",
        "green":  "\033[92m",
        "yellow": "\033[93m",
        "red":    "\033[91m",
        "cyan":   "\033[96m",
        "blue":   "\033[94m",
        "white":  "\033[97m",
        "gray":   "\033[90m",
    }
    return f"{codes.get(code, '')}{text}{codes['reset']}"

# ══════════════════════════════════════════════════════════════════════════════
#  ESTRUCTURAS DE DATOS (parsean el JSON de la API REST)
# ══════════════════════════════════════════════════════════════════════════════

class MachineSpec:
    def __init__(self, d: dict):
        self.machine_type        = d.get("machineType", "—")
        self.accelerator_type    = d.get("acceleratorType", "")
        self.accelerator_count   = d.get("acceleratorCount", 0)

class DedicatedResources:
    def __init__(self, d: dict):
        self.machine_spec      = MachineSpec(d.get("machineSpec", {}))
        self.min_replica_count = int(d.get("minReplicaCount", 0))
        self.max_replica_count = int(d.get("maxReplicaCount", 0))

class DeployedModelInfo:
    def __init__(self, d: dict):
        self.id                          = d.get("id", "—")
        self.model                       = d.get("model", "—")
        self.deployed_model_display_name = d.get("displayName", "—")
        self.model_version_id            = d.get("modelVersionId", "")
        self.create_time                 = d.get("createTime", "—")
        dr = d.get("dedicatedResources", {})
        self.dedicated_resources         = DedicatedResources(dr) if dr else None

class EndpointInfo:
    def __init__(self, d: dict):
        self.name          = d.get("name", "—")
        self.display_name  = d.get("displayName", "—")
        self.create_time   = d.get("createTime", "—")
        self.update_time   = d.get("updateTime", "—")
        raw_ts             = d.get("trafficSplit", {})
        self.traffic_split = {k: int(v) for k, v in raw_ts.items()}

# ══════════════════════════════════════════════════════════════════════════════
#  FASES DEL DEPLOY
# ══════════════════════════════════════════════════════════════════════════════
DEPLOY_PHASES = [
    {
        "id": 1,
        "name": "Endpoint activo",
        "description": "El endpoint existe y está registrado en Vertex AI.",
        "check": lambda ep, dm: ep is not None,
    },
    {
        "id": 2,
        "name": "Modelo asignado",
        "description": "Hay al menos un modelo vinculado al endpoint.",
        "check": lambda ep, dm: dm is not None,
    },
    {
        "id": 3,
        "name": "Tráfico configurado",
        "description": "El modelo tiene tráfico asignado (>0 %).",
        "check": lambda ep, dm: (
            dm is not None
            and ep.traffic_split.get(dm.id, 0) > 0
        ),
    },
    {
        "id": 4,
        "name": "Réplicas configuradas",
        "description": "El modelo tiene al menos 1 réplica mínima configurada.",
        "check": lambda ep, dm: (
            dm is not None
            and dm.dedicated_resources is not None
            and dm.dedicated_resources.min_replica_count > 0
        ),
    },
    {
        "id": 5,
        "name": "Deploy completado",
        "description": "Endpoint con modelo, tráfico y réplicas — listo para predicciones.",
        "check": lambda ep, dm: (
            dm is not None
            and ep.traffic_split.get(dm.id, 0) > 0
            and dm.dedicated_resources is not None
            and dm.dedicated_resources.min_replica_count > 0
            and dm.model_version_id != ""
        ),
    },
]
TOTAL_PHASES = len(DEPLOY_PHASES)

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS RENDER
# ══════════════════════════════════════════════════════════════════════════════

def progress_bar(current: int, total: int, width: int = 30) -> str:
    filled = int(width * current / total)
    bar    = "█" * filled + "░" * (width - filled)
    pct    = int(100 * current / total)
    return f"[{bar}] {pct:3d}%"

def phase_icon(passed: bool, active: bool) -> str:
    if passed:  return c("green",  "✔")
    if active:  return c("yellow", "▶")
    return c("dim", "○")

def print_header(ts: str) -> None:
    line = "═" * 62
    print()
    print(c("cyan", line))
    print(c("bold", f"  Vertex AI  ·  Deploy Monitor  ·  {ts}"))
    print(c("cyan", line))
    print(f"  {c('gray','Endpoint:')} {ENDPOINT_ID[:46]}…")
    print(f"  {c('gray','Proyecto:')} {PROJECT_ID}   {c('gray','Región:')} {LOCATION}")
    print(c("cyan", "─" * 62))

def print_phases(current_phase: int) -> None:
    print(c("bold", "\n  FASES DEL DEPLOY\n"))
    for ph in DEPLOY_PHASES:
        passed = ph["id"] < current_phase
        active = ph["id"] == current_phase
        icon   = phase_icon(passed, active)
        label  = ph["name"]
        desc   = c("dim", ph["description"])

        if active:
            label = c("yellow", c("bold", label)) + c("yellow", "  ← en curso")
        elif passed:
            label = c("green", label)
        else:
            label = c("dim", label)

        print(f"  {icon}  Fase {ph['id']}/{TOTAL_PHASES}  {label}")
        if active:
            print(f"         {desc}")

    print()
    done = min(current_phase - 1, TOTAL_PHASES)
    bar  = progress_bar(done, TOTAL_PHASES)
    print(f"  Progreso: {c('cyan', bar)}")
    print()

def print_model_info(dm) -> None:
    if dm is None:
        print(c("yellow", "  ⚠  No se encontró ningún modelo desplegado en el endpoint.\n"))
        return
    print(c("bold", "  MODELO DESPLEGADO\n"))
    rows = [
        ("ID desplegado",  dm.id),
        ("Model resource", dm.model),
        ("Display name",   dm.deployed_model_display_name or "—"),
        ("Versión",        dm.model_version_id or "—"),
        ("Creado",         dm.create_time),
    ]
    if dm.dedicated_resources:
        dr = dm.dedicated_resources
        rows += [
            ("Máquina",        dr.machine_spec.machine_type),
            ("Réplicas mín.",  str(dr.min_replica_count)),
            ("Réplicas máx.",  str(dr.max_replica_count)),
        ]
        if dr.machine_spec.accelerator_type:
            rows.append(("Acelerador", dr.machine_spec.accelerator_type))
    for k, v in rows:
        print(f"    {c('gray', k+':'): <22} {v}")
    print()

def print_traffic(ep) -> None:
    if not ep.traffic_split:
        print(c("yellow", "  ⚠  Sin reparto de tráfico configurado.\n"))
        return
    print(c("bold", "  REPARTO DE TRÁFICO\n"))
    for model_id, pct in ep.traffic_split.items():
        bar = progress_bar(pct, 100, width=20)
        print(f"    {c('gray','ID:')} {model_id[:36]}  {c('cyan', bar)}")
    print()

def diagnose_error(ep, dm) -> None:
    problems = []
    if ep is None:
        problems.append("El endpoint no existe o PROJECT_ID/LOCATION son incorrectos.")
    if dm is None and ep is not None:
        problems.append(
            "El endpoint existe pero no tiene modelos desplegados.\n"
            "     → Comprueba que el deploy se lanzó correctamente en la consola."
        )
    if dm is not None and not ep.traffic_split.get(dm.id, 0):
        problems.append(
            "El modelo está vinculado pero con tráfico = 0 %.\n"
            "     → El deploy puede estar en curso o el tráfico no fue asignado."
        )
    if dm is not None and dm.dedicated_resources and dm.dedicated_resources.min_replica_count == 0:
        problems.append(
            "Réplicas mínimas = 0.\n"
            "     → El endpoint puede estar en modo 'sleep' sin recursos activos."
        )

    if problems:
        print(c("red", "  ✖  DIAGNÓSTICO DE PROBLEMAS\n"))
        for i, p in enumerate(problems, 1):
            print(f"  {i}. {c('yellow', p)}")
        print()
    else:
        print(c("green", "  ✔  No se detectaron problemas obvios en la configuración.\n"))

# ══════════════════════════════════════════════════════════════════════════════
#  CREDENCIALES Y LLAMADA A LA API REST
# ══════════════════════════════════════════════════════════════════════════════

def _get_token() -> tuple:
    """
    Devuelve (access_token, error_msg).
    Carga desde SERVICE_ACCOUNT_JSON o usa ADC si es None.
    """
    if SERVICE_ACCOUNT_JSON:
        if not os.path.isfile(SERVICE_ACCOUNT_JSON):
            return None, (
                f"Fichero de credenciales no encontrado:\n"
                f"  {SERVICE_ACCOUNT_JSON}"
            )
        try:
            creds = service_account.Credentials.from_service_account_file(
                SERVICE_ACCOUNT_JSON,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        except Exception as exc:
            return None, f"Error leyendo credenciales: {exc}"
    else:
        # Application Default Credentials
        import google.auth
        try:
            creds, _ = google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
        except Exception as exc:
            return None, f"No se pudieron cargar las ADC: {exc}"

    try:
        creds.refresh(google_requests.Request())
        return creds.token, None
    except Exception as exc:
        return None, f"Error refrescando el token: {exc}"


def fetch_state():
    """
    Llama a la API REST de Vertex AI y devuelve
    (EndpointInfo | None, DeployedModelInfo | None, error_msg | None).
    """
    token, err = _get_token()
    if err:
        return None, None, err

    url = (
        f"https://{LOCATION}-aiplatform.googleapis.com/v1/"
        f"projects/{PROJECT_ID}/locations/{LOCATION}/endpoints/{ENDPOINT_ID}"
    )
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:400]
        if e.code == 404:
            return None, None, f"Endpoint no encontrado (404).\n  {body}"
        if e.code == 403:
            return None, None, f"Permiso denegado (403). Verifica los roles de la cuenta de servicio.\n  {body}"
        if e.code == 401:
            return None, None, f"Credenciales inválidas o expiradas (401).\n  {body}"
        return None, None, f"HTTP {e.code} al llamar a la API.\n  {body}"
    except Exception as exc:
        return None, None, f"Error de red: {exc}"

    ep = EndpointInfo(raw)
    deployed_list = raw.get("deployedModels", [])
    dm = DeployedModelInfo(deployed_list[0]) if deployed_list else None
    return ep, dm, None

# ══════════════════════════════════════════════════════════════════════════════
#  LÓGICA DE FASES Y LOOP PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def compute_phase(ep, dm) -> int:
    for ph in reversed(DEPLOY_PHASES):
        try:
            if ph["check"](ep, dm):
                return ph["id"] + 1
        except Exception:
            pass
    return 1

def run_monitor(interval: int, once: bool) -> None:
    attempts = 0
    while True:
        attempts += 1
        ts = datetime.datetime.now().strftime("%Y-%m-%d  %H:%M:%S")

        if not once and attempts > 1:
            print("\033[2J\033[H", end="")

        print_header(ts)

        ep, dm, err = fetch_state()

        if err:
            print(c("red", f"\n  [ERROR]  {err}\n"))
            print(c("gray", f"  Intento #{attempts}  ·  próximo en {interval}s…\n"))
        else:
            current_phase = min(compute_phase(ep, dm), TOTAL_PHASES + 1)

            print_phases(current_phase)
            print_model_info(dm)
            print_traffic(ep)

            if current_phase <= TOTAL_PHASES:
                diagnose_error(ep, dm)
            else:
                print(c("green", c("bold", "  ✔  DEPLOY COMPLETADO — el endpoint está listo.\n")))

            status_label = (
                c("green", "LISTO") if current_phase > TOTAL_PHASES
                else c("yellow", "EN PROGRESO")
            )
            print(c("cyan", "─" * 62))
            print(f"  Estado: {status_label}   Fase {min(current_phase, TOTAL_PHASES)}/{TOTAL_PHASES}")
            print(c("cyan", "═" * 62))

            if current_phase > TOTAL_PHASES and once:
                break
            if current_phase > TOTAL_PHASES:
                print(c("gray", "\n  Endpoint listo. Monitorización activa (Ctrl+C para salir).\n"))

        if once:
            break

        print(c("gray", f"\n  Próxima actualización en {interval}s  (Ctrl+C para salir)…"))
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print(c("cyan", "\n\n  Monitor detenido.\n"))
            sys.exit(0)

# ══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monitoriza el deploy de un modelo en un endpoint de Vertex AI."
    )
    parser.add_argument(
        "--interval", "-i",
        type=int,
        default=DEFAULT_INTERVAL,
        help=f"Segundos entre actualizaciones (default: {DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--once", "-1",
        action="store_true",
        help="Muestra el estado una sola vez y sale.",
    )
    args = parser.parse_args()
    run_monitor(interval=args.interval, once=args.once)


if __name__ == "__main__":
    main()
