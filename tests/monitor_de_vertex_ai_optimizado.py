#!/usr/bin/env python3
"""
monitor_endpointv2.py
Monitoriza de forma óptima el estado del deploy de Vertex AI.
Fusionado con comprobaciones de logs en tiempo real (Cloud Logging), detección de
tracebacks de Python, hitos de arranque vLLM y pruebas de predicción activas.
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
    from google.cloud import logging as cloud_logging
except ImportError:
    print("\n[ERROR] Faltan dependencias de Google Cloud. Instálalas con:")
    print("pip install google-auth google-cloud-logging\n")
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
#  API FETCH Y CONEXIÓN REST
# ══════════════════════════════════════════════════════════════════════════════
def _get_cached_token():
    """Obtiene y refresca de forma segura el token y credenciales de acceso."""
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
    return _CACHED_CREDS.token, _CACHED_CREDS

def fetch_specific_operation(operation_name: str):
    """Consulta los detalles de una operación de larga duración (LRO) específica."""
    token, _ = _get_cached_token()
    if not token: return None, "Fallo de credenciales"
    
    if not operation_name.startswith("projects/"):
        operation_name = f"projects/{PROJECT_ID}/locations/{LOCATION}/operations/{operation_name}"
        
    url = f"https://{LOCATION}-aiplatform.googleapis.com/v1/{operation_name}"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} al consultar operación: {e.read().decode(errors='replace')[:150]}"
    except Exception as exc:
        return None, f"Error de red al consultar operación: {exc}"

def fetch_vertex_state():
    """Recupera el estado del endpoint, tráfico asignado y operaciones recientes."""
    token, _ = _get_cached_token()
    if not token: return None, [], [], "Fallo de credenciales", None

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

    # 2. Consultar Historial de Operaciones
    ops = []
    op_err_msg = None
    try:
        url_ops = f"{base_url}/operations?pageSize=10"
        req_ops = urllib.request.Request(url_ops, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req_ops, timeout=10) as resp:
            raw_ops = json.loads(resp.read().decode("utf-8"))
            for op in raw_ops.get("operations", []):
                metadata_str = json.dumps(op.get("metadata", {}))
                if ENDPOINT_ID in metadata_str or ENDPOINT_ID in op.get("name", ""):
                    ops.append(op)
    except urllib.error.HTTPError as e:
        op_err_msg = f"HTTP {e.code} al obtener operaciones."
    except Exception as exc:
        op_err_msg = f"Error al buscar operaciones: {exc}"

    return ep, models, ops, None, op_err_msg

# ══════════════════════════════════════════════════════════════════════════════
#  ESCÁNER DE LOGS Y PRUEBA DE PREDICCIÓN REST
# ══════════════════════════════════════════════════════════════════════════════
def scan_cloud_logs(hours=3):
    """Escanea Cloud Logging en busca de señales de arranque o tracebacks."""
    _, creds = _get_cached_token()
    if not creds:
        return [], "No se pudieron resolver credenciales para logs"
        
    try:
        log_client = cloud_logging.Client(credentials=creds, project=PROJECT_ID)
        time_filter = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)).isoformat()
        
        # Filtro consolidado para el Endpoint
        filtro = f'''
        resource.type="aiplatform.googleapis.com/Endpoint"
        resource.labels.endpoint_id="{ENDPOINT_ID}"
        timestamp>="{time_filter}"
        '''
        
        entries = list(log_client.list_entries(filter_=filtro, order_by=cloud_logging.ASCENDING, max_results=150))
        return entries, None
    except Exception as e:
        return [], str(e)

def test_rest_prediction():
    """Ejecuta una predicción de prueba REST real sin necesidad del SDK pesado de Vertex."""
    token, _ = _get_cached_token()
    url = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/endpoints/{ENDPOINT_ID}:predict"
    
    payload = {
        "instances": [{"prompt": "Hola", "max_tokens": 5}]
    }
    
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
            return raw, None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode(errors='replace')[:150]}"
    except Exception as exc:
        return None, str(exc)

# ══════════════════════════════════════════════════════════════════════════════
#  RENDER E INTERFAZ DE USUARIO (CLI)
# ══════════════════════════════════════════════════════════════════════════════
def progress_bar(current: int, total: int) -> str:
    filled = int(30 * current / total)
    return f"[{'█' * filled}{'░' * (30 - filled)}] {int(100 * current / total):3d}%"

def run_monitor(interval: int, once: bool, tracked_op_id: str = None) -> None:
    start_time = time.time()
    attempts = 0
    test_prediction_completed = False
    
    if tracked_op_id and "/" in tracked_op_id and not tracked_op_id.startswith("projects/"):
        if "operations/" in tracked_op_id:
            tracked_op_id = "projects/" + tracked_op_id.split("projects/")[1]

    while True:
        attempts += 1
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not once and attempts > 1: print("\033[2J\033[H", end="")

        print(c("cyan", "═" * 62))
        print(c("bold", f"  Vertex AI Real-Time Monitor & Diagnóstico  ·  {ts}"))
        print(c("cyan", "═" * 62))

        # 1. FETCH DE ESTADO GLOBAL
        ep, models, ops, err, op_err = fetch_vertex_state()

        if err:
            print(c("red", f"  [ERROR CRÍTICO EN ENDPOINT] {err}\n"))
            if once: break
            time.sleep(interval)
            continue

        # 2. SEGUIMIENTO DE OPERACIÓN ESPECÍFICA (Modo Wake/Sleep LRO)
        target_op = None
        op_error_details = None
        
        if tracked_op_id:
            print(f"  {c('blue', '🔍')} Monitoreando operación activa:")
            print(f"     {c('dim', tracked_op_id)}")
            print(c("cyan", "─" * 62))
            
            op_data, op_fetch_err = fetch_specific_operation(tracked_op_id)
            if op_fetch_err:
                print(c("red", f"     [Aviso] No se pudo leer la operación: {op_fetch_err}"))
            else:
                target_op = op_data
        elif ops:
            target_op = ops[0]

        # 3. ANÁLISIS DE ERRORES EN LA OPERACIÓN
        is_failed = False
        if target_op:
            if "error" in target_op:
                is_failed = True
                op_error_details = target_op["error"]
            elif target_op.get("done", False) and not models and "response" not in target_op:
                is_failed = True
                op_error_details = {"message": "La operación se completó pero no hay réplicas asociadas al Endpoint."}

        # 4. DETERMINACIÓN DE FASES Y PROGRESO REAL
        active_ops_list = [o for o in ops if not o.get("done", False)]
        
        has_traffic = False
        if ep and models:
            # Comprobamos si el modelo cargado tiene tráfico activo asignado
            active_model_id = models[0].id
            has_traffic = ep.traffic_split.get(active_model_id, 0) > 0

        if is_failed:
            phase = "DESPLIEGUE FALLIDO (Se detectaron errores en la nube)"
            pct_idx = 0
        elif ep and len(models) > 0 and not active_ops_list and has_traffic:
            phase = "ESTABLE / LISTO (Sirviendo tráfico normalmente)"
            pct_idx = 4
        elif ep and len(models) > 0 and not active_ops_list and not has_traffic:
            phase = "CARGANDO MODELO (Esperando a que pase el Health Check)"
            pct_idx = 3
        elif target_op and not target_op.get("done", False):
            phase = "PROCESANDO DEPLOY (Asignando Hardware y Red)"
            pct_idx = 2
        else:
            phase = "ESPERANDO CAMBIOS (No hay despliegues activos)"
            pct_idx = 4

        # RENDERIZADO COHERENTE DE FASES
        if is_failed:
            print(f"  {c('green','✔')} Fase 1/4: Endpoint activo")
            print(f"  {c('red','❌')} Fase 2/4: {phase}")
            print(f"  {c('dim','○')} Fase 3/4: Réplicas estables")
            print(f"  {c('dim','○')} Fase 4/4: Enrutamiento de tráfico")
        else:
            print(f"  {c('green','✔')} Fase 1/4: Endpoint activo")
            print(f"  {(c('yellow','▶') if pct_idx == 2 else c('green','✔'))} Fase 2/4: {phase}")
            print(f"  {(c('yellow','▶') if pct_idx == 3 else (c('green','✔') if pct_idx > 3 else c('dim','○')))} Fase 3/4: Réplicas levantadas")
            print(f"  {(c('green','✔') if pct_idx >= 4 else c('dim','○'))} Fase 4/4: Tráfico enrutado")
            
        print(f"\n  Progreso Real: {c('red' if is_failed else 'cyan', progress_bar(pct_idx, 4))}\n")

        # 5. DETALLE DE OPERACIONES / CRONÓMETRO
        if pct_idx < 4 and not is_failed:
            elapsed = int(time.time() - start_time)
            mins, secs = divmod(elapsed, 60)
            print(c("yellow", f"  ⏳ TRABAJANDO EN LA NUBE:"))
            print(f"     Google Cloud está compilando la máquina y desplegando vLLM.")
            print(f"     Tiempo transcurrido en sesión: {c('bold', f'{mins}m {secs}s')}")
            print()

        # 6. PANEL DE DETALLE DE ERRORES DEL LRO
        if is_failed and op_error_details:
            print(c("red", "  ⚠️  FALLO DE INFRAESTRUCTURA DETECTADO:"))
            print(f"     Código: {op_error_details.get('code', 'DESCONOCIDO')} | Mensaje: {op_error_details.get('message', '—')}")
            print()

        # 7. ESTADO DE LOS MODELOS CONECTADOS Y TRÁFICO
        if models:
            print(c("bold", "  MODELOS CONECTADOS AL ENDPOINT:"))
            for dm in models:
                traffic = ep.traffic_split.get(dm.id, 0)
                traffic_text = f"{traffic}% de tráfico" if traffic > 0 else "0% (Esperando Health Check)"
                print(f"    • {c('green', dm.display_name)} [v{dm.version_id}] -> {c('bold', traffic_text)}")
                print(f"      ID interno: {dm.id} | Máquina: {dm.machine_type}")
            print()

        # 8. ANÁLISIS DE LOGS DE SERVIDOR EN TIEMPO REAL (Fusión Inteligente)
        print(c("bold", "  📋 SEÑALES RECIENTES DETECTADAS EN LOS LOGS (Últimas 3h):"))
        entries, log_err = scan_cloud_logs()
        if log_err:
            print(f"     {c('gray', '[Aviso] No se pudieron obtener logs:')} {log_err}")
        elif not entries:
            print("     No se registran logs en las últimas 3 horas.")
        else:
            claves_exito = ["Uvicorn running", "Application startup complete", "Started server process", "Avg prompt throughput", "Loading safetensors"]
            claves_fallo = ["Traceback (most recent call last)", "raise ", "OSError", "FileNotFoundError", "RuntimeError", "CUDA out of memory", "ValidationError"]
            
            exito_encontrado = False
            fallo_encontrado = False
            
            # Mostramos un resumen limpio de los logs críticos
            for entry in entries:
                payload = entry.payload
                texto = payload if isinstance(payload, str) else str(payload.get("message", payload))
                
                # Resaltar éxitos de arranque
                if any(k in texto for k in claves_exito):
                    exito_encontrado = True
                    # Limpiamos escapes ANSI para el renderizado
                    limpio = texto.replace("[0;36m", "").replace("[0;0m", "").strip()[:120]
                    print(f"     {c('green', '✔')} {limpio}...")
                
                # Resaltar fallos críticos o excepciones
                if any(k in texto for k in claves_fallo):
                    fallo_encontrado = True
                    print(f"     {c('red', '❌')} {texto.strip()[:140]}...")

            if not exito_encontrado and not fallo_encontrado:
                print("     ⏳ Servidor inicializando. Descargando pesos desde Cloud Storage a VRAM...")
        print()

        # 9. PRUEBA DE PREDICCIÓN EN VIVO AUTOMÁTICA
        if pct_idx == 4 and not test_prediction_completed:
            print(c("cyan", "  🚀 REALIZANDO PRUEBA DE PREDICCIÓN ACTIVA..."))
            resp, pred_err = test_rest_prediction()
            if pred_err:
                print(f"     {c('yellow', '⚠️')} La predicción falló (es normal si está terminando de inicializar):")
                print(f"        {pred_err}")
            else:
                print(f"     {c('green', '✅')} ¡El modelo respondió con éxito! El endpoint está 100% operativo.")
                print(f"        Respuesta: {json.dumps(resp.get('predictions', ['Sin respuesta']), ensure_ascii=False)}")
                test_prediction_completed = True
            print()

        print(c("cyan", "─" * 62))
        print(f"  Estado Global: {c('red' if is_failed else ('yellow' if pct_idx < 4 else 'green'), phase)}")
        print(c("cyan", "═" * 62))

        if once: break
        
        # Detenerse elegantemente si completamos la operación seguida con éxito
        if target_op and target_op.get("done", False) and not is_failed and pct_idx == 4:
            print(c("green", "\n  🎉 [COMPLETADO] El despliegue ha finalizado de forma correcta y está validado.\n"))
            break
            
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print(c("cyan", "\n\n  Monitor detenido.\n"))
            sys.exit(0)

def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor optimizado Vertex AI con logs y predicciones.")
    parser.add_argument("--interval", "-i", type=int, default=DEFAULT_INTERVAL, help="Intervalo de refresco en segundos.")
    parser.add_argument("--once", "-1", action="store_true", help="Ejecutar una sola vez y salir.")
    parser.add_argument("--operation", "-op", type=str, default=None, help="ID o nombre de la operación a monitorear.")
    args = parser.parse_args()
    
    run_monitor(interval=args.interval, once=args.once, tracked_op_id=args.operation)

if __name__ == "__main__":
    main()